from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import Field

from .media import (
    DEFAULT_ENCODER_SPEC,
    EncoderSpec,
    MediaInfo,
    OutputSpec,
    encode_frames,
    normalize_video,
    probe_media,
    validate_media,
)
from .models import StrictModel
from .production_models import (
    CompositeShot,
    GenerationContract,
    GeneratedShot,
    MotionKeyframe,
    ProductionPlan,
    ProductionShot,
    RenderMode,
    SimulationShot,
    StillMotionContract,
    StillMotionShot,
)
from .storage import atomic_write, shot_filename


class MediaRecord(StrictModel):
    video_codec: str
    audio_codec: str | None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    frame_count: int | None = Field(default=None, gt=0)
    pixel_format: str | None = None

    @classmethod
    def from_media_info(cls, info: MediaInfo) -> "MediaRecord":
        return cls(
            video_codec=info.video_codec,
            audio_codec=info.audio_codec,
            width=info.width,
            height=info.height,
            fps=info.fps,
            duration_seconds=info.duration_seconds,
            frame_count=info.frame_count,
            pixel_format=info.pixel_format,
        )


class ShotRenderRecord(StrictModel):
    shot_id: str
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_file: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media: MediaRecord


class ShotReviewRecord(StrictModel):
    shot_id: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending", "approved", "rejected"]
    invariant_results: dict[str, bool]
    note: str = ""


class ShotBackend(Protocol):
    version: str

    def render(self, shot: ProductionShot, context: "ShotContext") -> Path: ...


@dataclass
class ShotContext:
    run_dir: Path
    plan: ProductionPlan
    backend_versions: dict[str, str]
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC
    media_probe: Callable[[Path], MediaInfo] = probe_media

    def __post_init__(self) -> None:
        self.run_dir = self.run_dir.resolve()

    @staticmethod
    def file_sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def safe_path(self, relative: str | Path) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute():
            raise ValueError(f"absolute path is not allowed: {relative}")
        candidate = (self.run_dir / relative_path).resolve()
        if self.run_dir not in candidate.parents:
            raise ValueError(f"path escapes run directory: {relative}")
        return candidate

    def asset_path(self, relative: str) -> Path:
        if not relative.startswith("shotAssets/"):
            raise ValueError(f"asset must be under shotAssets/: {relative}")
        return self.safe_path(relative)

    def output_path(self, shot: ProductionShot) -> Path:
        return self.safe_path(
            Path("shotFiles") / shot_filename(shot.shot_id, shot.title, ".mp4")
        )

    def record_path(self, shot: ProductionShot) -> Path:
        return self.safe_path(f"shotFiles/{shot.shot_id}.render.json")

    def review_path(self, shot: ProductionShot) -> Path:
        return self.safe_path(f"shotFiles/reviews/{shot.shot_id}.json")

    def _asset_hashes(self, shot: ProductionShot) -> dict[str, str]:
        payload = shot.model_dump(mode="json", exclude_none=True)
        paths: set[str] = set()

        def visit(value: object) -> None:
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, str) and value.startswith("shotAssets/"):
                paths.add(value)

        visit(payload)
        return {
            relative: self.file_sha256(self.asset_path(relative))
            for relative in sorted(paths)
        }

    def _dependency_hashes(self, shot: ProductionShot) -> dict[str, str]:
        by_id = {
            candidate.shot_id: candidate
            for scene in self.plan.scenes
            for candidate in scene.shots
        }
        hashes: dict[str, str] = {}
        for dependency in shot.dependencies:
            source = by_id[dependency.shot_id]
            path = self.output_path(source)
            hashes[f"{dependency.shot_id}:{dependency.artifact}"] = (
                self.file_sha256(path) if path.is_file() else "missing"
            )
        return hashes

    def input_fingerprint(self, shot: ProductionShot) -> str:
        payload = {
            "schema_version": self.plan.schema_version,
            "defaults": self.plan.defaults.model_dump(mode="json"),
            "style_bible": self.plan.style_bible.model_dump(mode="json"),
            "shot": shot.model_dump(mode="json"),
            "assets": self._asset_hashes(shot),
            "dependencies": self._dependency_hashes(shot),
            "backend_version": self.backend_versions.get(shot.render_mode, "unregistered"),
            "encoder": {"preset": self.encoder.preset, "crf": self.encoder.crf},
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def can_reuse(self, shot: ProductionShot, record: ShotRenderRecord) -> bool:
        if record.shot_id != shot.shot_id:
            return False
        if record.input_fingerprint != self.input_fingerprint(shot):
            return False
        output = self.safe_path(record.output_file)
        if output != self.output_path(shot) or not output.is_file():
            return False
        if self.file_sha256(output) != record.output_sha256:
            return False
        try:
            current = MediaRecord.from_media_info(self.media_probe(output))
        except Exception:
            return False
        expected_frames = round(shot.duration_seconds * self.plan.defaults.fps)
        return (
            current == record.media
            and current.video_codec == "h264"
            and current.audio_codec is None
            and current.width == self.plan.defaults.width
            and current.height == self.plan.defaults.height
            and abs(current.fps - self.plan.defaults.fps) <= 0.01
            and (
                current.frame_count is None or current.frame_count == expected_frames
            )
        )

    def is_review_approved(
        self,
        shot: ProductionShot,
        review: ShotReviewRecord,
    ) -> bool:
        output = self.output_path(shot)
        return (
            review.shot_id == shot.shot_id
            and review.status == "approved"
            and output.is_file()
            and review.output_sha256 == self.file_sha256(output)
            and all(review.invariant_results.get(item) is True for item in shot.invariants)
        )

    def write_render_record(
        self,
        shot: ProductionShot,
        output: Path,
        info: MediaInfo,
    ) -> ShotRenderRecord:
        record = ShotRenderRecord(
            shot_id=shot.shot_id,
            input_fingerprint=self.input_fingerprint(shot),
            output_file=output.relative_to(self.run_dir).as_posix(),
            output_sha256=self.file_sha256(output),
            media=MediaRecord.from_media_info(info),
        )
        path = self.record_path(shot)
        atomic_write(path, record.model_dump_json(indent=2) + "\n")
        return record

    def write_pending_review(
        self,
        shot: ProductionShot,
        output: Path,
    ) -> ShotReviewRecord:
        review = ShotReviewRecord(
            shot_id=shot.shot_id,
            output_sha256=self.file_sha256(output),
            status="pending",
            invariant_results={},
            note="",
        )
        path = self.review_path(shot)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, review.model_dump_json(indent=2) + "\n")
        return review


@dataclass
class ShotBackendRegistry:
    backends: dict[RenderMode, ShotBackend] = field(default_factory=dict)

    def register(self, mode: RenderMode, backend: ShotBackend) -> None:
        self.backends[mode] = backend

    def get(self, mode: RenderMode) -> ShotBackend:
        try:
            return self.backends[mode]
        except KeyError as error:
            raise ValueError(f"등록되지 않은 샷 렌더 모드입니다: {mode}") from error


def _output_spec(shot: ProductionShot, context: ShotContext) -> OutputSpec:
    return OutputSpec(
        width=context.plan.defaults.width,
        height=context.plan.defaults.height,
        fps=context.plan.defaults.fps,
        duration_seconds=shot.duration_seconds,
    )


def _require_generation_references(
    shot: ProductionShot,
    generation: GenerationContract,
    context: ShotContext,
) -> None:
    required = []
    if generation.mode in {"i2v", "first_last"}:
        required.append(shot.assets.start_image)
    if generation.mode == "first_last":
        required.append(shot.assets.end_image)
    for relative in required:
        if relative is None:
            raise ValueError(f"shot {shot.shot_id} generation reference is not declared")
        path = context.asset_path(relative)
        if not path.is_file():
            raise FileNotFoundError(path)


def _normalize_generated_contract(
    shot: ProductionShot,
    generation: GenerationContract,
    context: ShotContext,
    destination: Path,
) -> MediaInfo:
    _require_generation_references(shot, generation, context)
    source = context.safe_path(generation.inbox_file)
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(
            f"외부 생성 클립이 없습니다: {source}. 이 경로에 승인 전 원본을 넣으세요."
        )
    source_info = probe_media(source)
    tolerance = 1 / context.plan.defaults.fps
    if source_info.duration_seconds + tolerance < shot.duration_seconds:
        raise ValueError(
            f"샷 {shot.shot_id} 원본이 짧습니다: "
            f"{source_info.duration_seconds:.3f}초 / {shot.duration_seconds:.3f}초"
        )
    return normalize_video(
        source,
        destination,
        _output_spec(shot, context),
        encoder=context.encoder,
    )


class GeneratedClipBackend:
    version = "generated-intake-v1"

    def render(self, shot: ProductionShot, context: ShotContext) -> Path:
        if not isinstance(shot, GeneratedShot):
            raise TypeError("GeneratedClipBackend requires a GeneratedShot")
        output = context.output_path(shot)
        info = _normalize_generated_contract(
            shot,
            shot.generation,
            context,
            output,
        )
        context.write_render_record(shot, output, info)
        context.write_pending_review(shot, output)
        return output


def _keyframe_expression(
    keyframes: list[MotionKeyframe],
    attribute: str,
    *,
    duration: float,
    frame_count: int,
    variable: str,
    component: int | None = None,
) -> str:
    def value(keyframe: MotionKeyframe) -> float:
        raw = getattr(keyframe, attribute)
        return float(raw[component]) if component is not None else float(raw)

    if len(keyframes) == 1:
        return f"{value(keyframes[0]):.9f}"
    frame_at = [
        round(keyframe.at_seconds / duration * max(frame_count - 1, 1))
        for keyframe in keyframes
    ]
    expression = f"{value(keyframes[-1]):.9f}"
    for index in range(len(keyframes) - 2, -1, -1):
        start_frame = frame_at[index]
        end_frame = frame_at[index + 1]
        start_value = value(keyframes[index])
        end_value = value(keyframes[index + 1])
        span = max(end_frame - start_frame, 1)
        linear = (
            f"({start_value:.9f}+({end_value - start_value:.9f})*"
            f"({variable}-{start_frame})/{span})"
        )
        expression = f"if(lte({variable},{end_frame}),{linear},{expression})"
    return expression


class StillMotionBackend:
    version = "still-motion-ffmpeg-v1"

    def _render_command(
        self,
        shot: ProductionShot,
        contract: StillMotionContract,
        context: ShotContext,
        temporary: Path,
    ) -> list[str]:
        spec = _output_spec(shot, context)
        base = context.asset_path(contract.source_image)
        if not base.is_file():
            raise FileNotFoundError(base)
        keyframes = contract.camera_keyframes or [
            MotionKeyframe(at_seconds=0.0),
            MotionKeyframe(at_seconds=shot.duration_seconds),
        ]
        scale = _keyframe_expression(
            keyframes,
            "scale",
            duration=shot.duration_seconds,
            frame_count=spec.frame_count,
            variable="on",
        )
        center_x = _keyframe_expression(
            keyframes,
            "center",
            duration=shot.duration_seconds,
            frame_count=spec.frame_count,
            variable="on",
            component=0,
        )
        center_y = _keyframe_expression(
            keyframes,
            "center",
            duration=shot.duration_seconds,
            frame_count=spec.frame_count,
            variable="on",
            component=1,
        )
        rotation = _keyframe_expression(
            keyframes,
            "rotation_degrees",
            duration=shot.duration_seconds,
            frame_count=spec.frame_count,
            variable="n",
        )
        if any(keyframe.scale < 1 for keyframe in keyframes):
            raise ValueError("still_motion camera scale must be at least 1.0")

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(spec.fps),
            "-i",
            str(base),
        ]
        for layer in contract.layers:
            layer_path = context.asset_path(layer.source_image)
            if not layer_path.is_file():
                raise FileNotFoundError(layer_path)
            if layer.mask and not context.asset_path(layer.mask).is_file():
                raise FileNotFoundError(context.asset_path(layer.mask))
            command.extend(
                ["-loop", "1", "-framerate", str(spec.fps), "-i", str(layer_path)]
            )

        base_filter = (
            f"[0:v]format=rgba,zoompan=z='{scale}':"
            f"x='max(0,min(iw-iw/zoom,iw*({center_x})-iw/zoom/2))':"
            f"y='max(0,min(ih-ih/zoom,ih*({center_y})-ih/zoom/2))':"
            f"d=1:s={spec.width}x{spec.height}:fps={spec.fps},"
            f"rotate=angle='({rotation})*PI/180':ow=iw:oh=ih:c=black@0[base0]"
        )
        filters = [base_filter]
        current = "base0"
        for index, layer in enumerate(sorted(contract.layers, key=lambda item: item.z_index), 1):
            opacity_values = {round(keyframe.opacity, 9) for keyframe in layer.keyframes}
            if len(opacity_values) != 1:
                raise ValueError(
                    "still_motion schema version 1 requires constant layer opacity"
                )
            layer_scale = _keyframe_expression(
                layer.keyframes,
                "scale",
                duration=shot.duration_seconds,
                frame_count=spec.frame_count,
                variable="n",
            )
            layer_x = _keyframe_expression(
                layer.keyframes,
                "center",
                duration=shot.duration_seconds,
                frame_count=spec.frame_count,
                variable="n",
                component=0,
            )
            layer_y = _keyframe_expression(
                layer.keyframes,
                "center",
                duration=shot.duration_seconds,
                frame_count=spec.frame_count,
                variable="n",
                component=1,
            )
            layer_rotation = _keyframe_expression(
                layer.keyframes,
                "rotation_degrees",
                duration=shot.duration_seconds,
                frame_count=spec.frame_count,
                variable="n",
            )
            opacity = next(iter(opacity_values))
            filters.append(
                f"[{index}:v]format=rgba,fps={spec.fps},"
                f"scale=w='iw*({layer_scale})':h='ih*({layer_scale})':eval=frame,"
                f"rotate=angle='({layer_rotation})*PI/180':ow=rotw(iw):oh=roth(ih):c=none,"
                f"colorchannelmixer=aa={opacity:.9f}[layer{index}]"
            )
            output_label = f"composite{index}"
            filters.append(
                f"[{current}][layer{index}]overlay="
                f"x='{spec.width}*({layer_x})-overlay_w/2':"
                f"y='{spec.height}*({layer_y})-overlay_h/2':"
                f"shortest=1:eof_action=pass[{output_label}]"
            )
            current = output_label
        filters.append(f"[{current}]format=yuv420p[vout]")
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-frames:v",
                str(spec.frame_count),
                "-c:v",
                "libx264",
                "-preset",
                context.encoder.preset,
                "-crf",
                str(context.encoder.crf),
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(temporary),
            ]
        )
        return command

    def render_contract(
        self,
        shot: ProductionShot,
        contract: StillMotionContract,
        context: ShotContext,
        destination: Path,
        *,
        write_record: bool,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp.mp4")
        if temporary.exists():
            temporary.unlink()
        try:
            subprocess.run(
                self._render_command(shot, contract, context, temporary),
                check=True,
            )
            info = probe_media(temporary)
            validate_media(info, _output_spec(shot, context), require_audio=False)
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        if write_record:
            context.write_render_record(shot, destination, info)
        return destination

    def render(self, shot: ProductionShot, context: ShotContext) -> Path:
        if not isinstance(shot, StillMotionShot):
            raise TypeError("StillMotionBackend requires a StillMotionShot")
        output = context.output_path(shot)
        return self.render_contract(
            shot,
            shot.still_motion,
            context,
            output,
            write_record=True,
        )


SIMULATION_TEMPLATE_RELATIONSHIPS: dict[str, set[str]] = {
    "sky-orbit-reveal": {"projection_intersection"},
    "retrograde-track": {"projection_intersection"},
    "moving-observer": {"path_membership"},
    "sightline-angle": {"attached_line"},
    "speed-comparison": {"path_membership"},
    "earth-overtake": {"fixed_distance"},
    "projection-proof": {"projection_intersection"},
    "return-to-direct": {"projection_intersection"},
    "same-direction-arrows": {"path_membership"},
    "local-overtake": {"fixed_distance"},
    "cumulative-sightlines": {"attached_line", "projection_intersection"},
    "stationary-points": {"projection_intersection"},
    "monthly-cycle-hook": {"path_membership"},
    "top-view-alignment": {"path_membership"},
    "tilt-reveal": {"path_membership"},
    "new-moon-miss": {"projection_intersection"},
    "full-moon-miss": {"projection_intersection"},
    "node-crossing": {"path_membership", "relative_placement"},
    "solar-eclipse-alignment": {"occlusion_alignment"},
    "lunar-eclipse-alignment": {"occlusion_alignment"},
    "two-condition-summary": {"path_membership", "occlusion_alignment"},
}

SIMULATION_TEMPLATE_CAPABILITIES: dict[str, set[str]] = {
    "sky-orbit-reveal": {"sky_to_orbit"},
    "retrograde-track": {"apparent_retrograde_track"},
    "moving-observer": {"moving_observer"},
    "sightline-angle": {"single_sightline"},
    "speed-comparison": {"equal_time_speed_trails"},
    "earth-overtake": {"whole_orbit_overtake"},
    "projection-proof": {"projection_history", "star_projection"},
    "return-to-direct": {"orbit_sky_payoff"},
    "same-direction-arrows": {"orbit_direction_arrows"},
    "local-overtake": {"local_overtake"},
    "cumulative-sightlines": {"cumulative_sightlines", "star_projection"},
    "stationary-points": {"two_stationary_markers"},
}

ECLIPSE_SIMULATION_MODEL = "sun-earth-moon-eclipse-teaching-model-v1"


class SimulationBackend:
    version = "science-renderer-v3"

    def __init__(self) -> None:
        self.renderer_dir = Path(__file__).resolve().parent / "science_renderer"

    def build_job(
        self,
        shot: ProductionShot,
        context: ShotContext,
        cache_dir: Path,
    ) -> dict:
        if not isinstance(shot, SimulationShot):
            raise TypeError("SimulationBackend requires a SimulationShot")
        supported = SIMULATION_TEMPLATE_RELATIONSHIPS.get(shot.simulation.template)
        if supported is None:
            raise ValueError(f"등록되지 않은 시뮬레이션 템플릿: {shot.simulation.template}")
        declared = {relationship.type for relationship in shot.relationships}
        unsupported = declared - supported
        if unsupported:
            raise ValueError(
                f"템플릿 {shot.simulation.template}이 소유하지 않는 관계: {sorted(unsupported)}"
            )
        requested_features = set(
            shot.simulation.renderer_options.get("required_features", [])
        )
        supported_features = SIMULATION_TEMPLATE_CAPABILITIES.get(
            shot.simulation.template,
            set(),
        )
        missing_features = requested_features - supported_features
        if missing_features:
            raise ValueError(
                f"템플릿 {shot.simulation.template}이 지원하지 않는 시각 기능: "
                f"{sorted(missing_features)}"
            )
        if shot.simulation.model == ECLIPSE_SIMULATION_MODEL:
            parameters = shot.simulation.parameters
            required = ("moon_orbit_inclination_degrees", "moon_orbit_radius")
            missing = [name for name in required if name not in parameters]
            if missing:
                raise ValueError(f"식현상 시뮬레이션 파라미터가 없습니다: {', '.join(missing)}")
            style = shot.simulation.renderer_options.get("style", {})
            required_style = ("seed", "earth_scale", "moon_scale", "sun_scale")
            missing_style = [name for name in required_style if name not in style]
            if missing_style:
                raise ValueError(f"식현상 시뮬레이션 스타일 값이 없습니다: {', '.join(missing_style)}")

            start = next(
                (
                    parameters[name]
                    for name in (
                        "moon_cycle_start_degrees",
                        "moon_longitude_start_degrees",
                        "sun_longitude_start_degrees",
                        "camera_reveal_start",
                    )
                    if name in parameters
                ),
                0.0,
            )
            end = next(
                (
                    parameters[name]
                    for name in (
                        "moon_cycle_end_degrees",
                        "moon_longitude_end_degrees",
                        "sun_longitude_end_degrees",
                        "camera_reveal_end",
                    )
                    if name in parameters
                ),
                1.0,
            )
            return {
                "scene_id": int(shot.shot_id[:-1]),
                "title": shot.title,
                "template": shot.simulation.template,
                "simulation_day_start": float(start),
                "simulation_day_end": float(end),
                "duration_seconds": shot.duration_seconds,
                "frame_count": round(shot.duration_seconds * context.plan.defaults.fps),
                "output_directory": str(cache_dir),
                "output": {
                    "width": context.plan.defaults.width,
                    "height": context.plan.defaults.height,
                    "fps": context.plan.defaults.fps,
                },
                "style": {
                    "seed": int(style["seed"]),
                    "earth_scale": float(style["earth_scale"]),
                    "moon_scale": float(style["moon_scale"]),
                    "sun_scale": float(style["sun_scale"]),
                },
                "eclipse": {
                    "parameters": parameters,
                    "renderer_options": shot.simulation.renderer_options,
                },
            }
        parameters = shot.simulation.parameters
        required = (
            "earth_period_days",
            "mars_period_days",
            "earth_orbit_radius",
            "mars_orbit_radius",
            "opposition_day",
            "simulation_day_start",
            "simulation_day_end",
        )
        missing = [name for name in required if name not in parameters]
        if missing:
            raise ValueError(f"시뮬레이션 파라미터가 없습니다: {', '.join(missing)}")
        style = shot.simulation.renderer_options.get("style", {})
        required_style = ("seed", "earth_scale", "mars_scale")
        missing_style = [name for name in required_style if name not in style]
        if missing_style:
            raise ValueError(f"시뮬레이션 스타일 값이 없습니다: {', '.join(missing_style)}")
        return {
            "scene_id": int(shot.shot_id[:-1]),
            "title": shot.title,
            "template": shot.simulation.template,
            "simulation_day_start": float(parameters["simulation_day_start"]),
            "simulation_day_end": float(parameters["simulation_day_end"]),
            "duration_seconds": shot.duration_seconds,
            "frame_count": round(shot.duration_seconds * context.plan.defaults.fps),
            "output_directory": str(cache_dir),
            "output": {
                "width": context.plan.defaults.width,
                "height": context.plan.defaults.height,
                "fps": context.plan.defaults.fps,
            },
            "physics": {name: float(parameters[name]) for name in required[:5]},
            "style": {
                "seed": int(style["seed"]),
                "earth_scale": float(style["earth_scale"]),
                "mars_scale": float(style["mars_scale"]),
            },
            "camera": shot.camera.model_dump(mode="json", exclude_none=True),
            "renderer_options": shot.simulation.renderer_options,
        }

    def render(self, shot: ProductionShot, context: ShotContext) -> Path:
        if not (self.renderer_dir / "node_modules").is_dir():
            raise RuntimeError(
                f"렌더러 의존성이 없습니다: cd {self.renderer_dir} && npm install"
            )
        cache_dir = context.safe_path(f".render-cache/production/{shot.shot_id}")
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True)
        output = context.output_path(shot)
        try:
            job = self.build_job(shot, context, cache_dir)
            job_path = cache_dir / "render-job.json"
            atomic_write(job_path, json.dumps(job, ensure_ascii=False, indent=2) + "\n")
            result = subprocess.run(
                ["npm", "run", "render", "--silent", "--", str(job_path)],
                cwd=self.renderer_dir,
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise RuntimeError(
                    f"시뮬레이션 렌더 실패 ({shot.shot_id}): {result.stderr.strip()}"
                )
            info = encode_frames(
                cache_dir / "frame-%06d.png",
                output,
                _output_spec(shot, context),
                encoder=context.encoder,
            )
            context.write_render_record(shot, output, info)
            return output
        finally:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)


class CompositeBackend:
    version = "deterministic-composite-v1"

    def __init__(self) -> None:
        self.renderer_dir = Path(__file__).resolve().parent / "science_renderer"

    def build_overlay_job(
        self,
        shot: CompositeShot,
        context: ShotContext,
        frame_dir: Path,
    ) -> dict:
        return {
            "width": context.plan.defaults.width,
            "height": context.plan.defaults.height,
            "frame_count": round(shot.duration_seconds * context.plan.defaults.fps),
            "duration_seconds": shot.duration_seconds,
            "output_directory": str(frame_dir),
            "overlays": [
                overlay.model_dump(mode="json", exclude_none=True)
                for overlay in shot.overlays
            ],
        }

    def _render_base(
        self,
        shot: CompositeShot,
        context: ShotContext,
        destination: Path,
    ) -> None:
        if shot.base.mode == "generated" and shot.base.generation is not None:
            _normalize_generated_contract(
                shot,
                shot.base.generation,
                context,
                destination,
            )
            return
        if shot.base.mode == "still_motion" and shot.base.still_motion is not None:
            StillMotionBackend().render_contract(
                shot,
                shot.base.still_motion,
                context,
                destination,
                write_record=False,
            )
            return
        raise ValueError(f"샷 {shot.shot_id} 합성 베이스 계약이 완전하지 않습니다.")

    def render(self, shot: ProductionShot, context: ShotContext) -> Path:
        if not isinstance(shot, CompositeShot):
            raise TypeError("CompositeBackend requires a CompositeShot")
        if not (self.renderer_dir / "node_modules").is_dir():
            raise RuntimeError(
                f"오버레이 렌더러 의존성이 없습니다: cd {self.renderer_dir} && npm install"
            )
        cache_dir = context.safe_path(f".render-cache/composite/{shot.shot_id}")
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        frame_dir = cache_dir / "overlays"
        frame_dir.mkdir(parents=True)
        base_path = cache_dir / "base.mp4"
        output = context.output_path(shot)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp.mp4")
        try:
            self._render_base(shot, context, base_path)
            job = self.build_overlay_job(shot, context, frame_dir)
            job_path = cache_dir / "overlay-job.json"
            atomic_write(job_path, json.dumps(job, ensure_ascii=False, indent=2) + "\n")
            result = subprocess.run(
                ["npm", "run", "render-overlay", "--silent", "--", str(job_path)],
                cwd=self.renderer_dir,
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise RuntimeError(
                    f"오버레이 렌더 실패 ({shot.shot_id}): {result.stderr.strip()}"
                )
            spec = _output_spec(shot, context)
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(base_path),
                    "-framerate",
                    str(spec.fps),
                    "-i",
                    str(frame_dir / "overlay-%06d.png"),
                    "-filter_complex",
                    "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[vout]",
                    "-map",
                    "[vout]",
                    "-frames:v",
                    str(spec.frame_count),
                    "-c:v",
                    "libx264",
                    "-preset",
                    context.encoder.preset,
                    "-crf",
                    str(context.encoder.crf),
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ],
                check=True,
            )
            info = probe_media(temporary)
            validate_media(info, spec, require_audio=False)
            temporary.replace(output)
            context.write_render_record(shot, output, info)
            if shot.base.mode == "generated":
                context.write_pending_review(shot, output)
            return output
        finally:
            if temporary.exists():
                temporary.unlink()
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
