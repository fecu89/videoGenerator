from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .media import (
    DEFAULT_ENCODER_SPEC,
    EncoderSpec,
    MediaInfo,
    OutputSpec,
    capture_preview_frames,
    concat_videos,
    encode_frames,
    mux_audio,
)
from .models import Scene
from .settings import HarnessSettings
from .simulation import PhysicsSettings, SimulationConfig, load_simulation
from .storage import RunStore, atomic_write, fingerprint, scene_filename


@dataclass(frozen=True)
class RenderedScene:
    scene_id: int
    title: str
    video_file: str
    original_video_file: str
    preview_files: list[str]
    frame_count: int
    duration_seconds: float
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class RenderReport:
    quality: str
    config_sha256: str
    science_checks: dict[str, bool | float]
    scenes: list[RenderedScene]
    final_file: str | None
    final_original_file: str | None

    def to_dict(self) -> dict:
        return {
            "quality": self.quality,
            "config_sha256": self.config_sha256,
            "science_checks": self.science_checks,
            "scenes": [asdict(scene) for scene in self.scenes],
            "final_file": self.final_file,
            "final_original_file": self.final_original_file,
        }


class RenderBackend(Protocol):
    def check_dependencies(self) -> None: ...

    def render_frames(self, job: dict, cache_dir: Path) -> None: ...

    def encode_original(
        self,
        cache_dir: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        duration_seconds: float,
    ) -> MediaInfo: ...

    def encode_scene(
        self,
        original_path: Path,
        audio_path: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        duration_seconds: float,
    ) -> MediaInfo: ...

    def create_previews(
        self,
        source_path: Path,
        output_directory: Path,
        timestamps: Sequence[float],
    ) -> list[Path]: ...

    def concatenate(
        self,
        scene_paths: list[Path],
        output_path: Path,
        *,
        expected_duration: float,
        require_audio: bool,
        transition_seconds: float = 0.0,
        transition_fade_seconds: float = 0.0,
    ) -> MediaInfo: ...


def parse_scene_ids(value: str) -> set[int]:
    try:
        ids = {int(part.strip()) for part in value.split(",") if part.strip()}
    except ValueError as error:
        raise argparse.ArgumentTypeError("씬 번호는 쉼표로 구분한 정수여야 합니다.") from error
    if not ids or any(scene_id < 1 for scene_id in ids):
        raise argparse.ArgumentTypeError("씬 번호는 1 이상의 정수여야 합니다.")
    return ids


def _orbit_position(radius: float, period: float, day: float, opposition: float) -> tuple[float, float]:
    angle = 2 * math.pi * (day - opposition) / period
    return radius * math.cos(angle), radius * math.sin(angle)


def _apparent_longitude(day: float, physics: PhysicsSettings) -> float:
    earth = _orbit_position(
        physics.earth_orbit_radius,
        physics.earth_period_days,
        day,
        physics.opposition_day,
    )
    mars = _orbit_position(
        physics.mars_orbit_radius,
        physics.mars_period_days,
        day,
        physics.opposition_day,
    )
    return math.atan2(mars[1] - earth[1], mars[0] - earth[0])


def _longitude_rate(day: float, physics: PhysicsSettings, half_step: float = 0.01) -> float:
    before = _apparent_longitude(day - half_step, physics)
    after = _apparent_longitude(day + half_step, physics)
    delta = math.atan2(math.sin(after - before), math.cos(after - before))
    return delta / (2 * half_step)


def build_science_checks(config: SimulationConfig) -> dict[str, bool | float]:
    physics = config.physics
    center = physics.opposition_day
    before_rate = _longitude_rate(center - 60, physics)
    center_rate = _longitude_rate(center, physics)
    after_rate = _longitude_rate(center + 60, physics)
    return {
        "physical_orbits_forward": (
            physics.earth_period_days > 0 and physics.mars_period_days > 0
        ),
        "earth_angular_speed_exceeds_mars": (
            physics.earth_period_days < physics.mars_period_days
        ),
        "projection_reverses_near_opposition": (
            before_rate > 0 and center_rate < 0 and after_rate > 0
        ),
        "apparent_rate_before": round(before_rate, 9),
        "apparent_rate_at_opposition": round(center_rate, 9),
        "apparent_rate_after": round(after_rate, 9),
    }


class LocalRenderBackend:
    def __init__(self, *, encoder: EncoderSpec = DEFAULT_ENCODER_SPEC) -> None:
        self.renderer_dir = Path(__file__).resolve().parent / "science_renderer"
        self.encoder = encoder

    def check_dependencies(self) -> None:
        missing = [name for name in ("npm", "ffmpeg", "ffprobe") if shutil.which(name) is None]
        if missing:
            raise RuntimeError(f"필요한 명령이 없습니다: {', '.join(missing)}")
        if not (self.renderer_dir / "node_modules").is_dir():
            raise RuntimeError(
                f"렌더러 의존성이 없습니다: cd {self.renderer_dir} && npm install"
            )

    def render_frames(self, job: dict, cache_dir: Path) -> None:
        job_path = cache_dir / "render-job.json"
        atomic_write(job_path, json.dumps(job, ensure_ascii=False, indent=2) + "\n")
        subprocess.run(
            ["npm", "run", "render", "--silent", "--", str(job_path)],
            cwd=self.renderer_dir,
            text=True,
            capture_output=True,
            check=True,
        )

    def encode_original(
        self,
        cache_dir: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        duration_seconds: float,
    ) -> MediaInfo:
        return encode_frames(
            cache_dir / "frame-%06d.png",
            output_path,
            OutputSpec(
                width=width,
                height=height,
                fps=fps,
                duration_seconds=duration_seconds,
                frames=math.ceil(duration_seconds * fps),
            ),
            encoder=self.encoder,
        )

    def encode_scene(
        self,
        original_path: Path,
        audio_path: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        duration_seconds: float,
    ) -> MediaInfo:
        return mux_audio(
            original_path,
            audio_path,
            output_path,
            OutputSpec(
                width=width,
                height=height,
                fps=fps,
                duration_seconds=duration_seconds,
                frames=math.ceil(duration_seconds * fps),
            ),
            encoder=self.encoder,
        )

    def create_previews(
        self,
        source_path: Path,
        output_directory: Path,
        timestamps: Sequence[float],
    ) -> list[Path]:
        return capture_preview_frames(
            source_path,
            output_directory,
            timestamps,
            [f"{round(timestamp * 1000):04d}ms.png" for timestamp in timestamps],
        )

    def concatenate(
        self,
        scene_paths: list[Path],
        output_path: Path,
        *,
        expected_duration: float,
        require_audio: bool,
        transition_seconds: float = 0.0,
        transition_fade_seconds: float = 0.0,
    ) -> MediaInfo:
        return concat_videos(
            scene_paths,
            output_path,
            expected_duration=expected_duration,
            require_audio=require_audio,
            transition_seconds=transition_seconds,
            transition_fade_seconds=transition_fade_seconds,
            encoder=self.encoder,
        )


def _output_dimensions(
    config: SimulationConfig,
    quality: str,
    settings: HarnessSettings,
) -> tuple[int, int]:
    if quality == "draft":
        return settings.render.draft_width, settings.render.draft_height
    return config.output.width, config.output.height


def _scene_output_path(
    run_dir: Path,
    scene: Scene,
    quality: str,
) -> Path:
    directory = run_dir / "videoFiles"
    if quality == "draft":
        directory /= "draft"
    return directory / scene_filename(scene, ".mp4")


def _scene_original_output_path(
    run_dir: Path,
    scene: Scene,
    quality: str,
) -> Path:
    directory = run_dir / "videoFiles"
    if quality == "draft":
        directory /= "draft"
    return directory / "original" / scene_filename(scene, ".mp4")


def _scene_preview_directory(
    run_dir: Path,
    scene: Scene,
    quality: str,
) -> Path:
    directory = run_dir / "videoFiles"
    if quality == "draft":
        directory /= "draft"
    scene_directory = Path(scene_filename(scene, ".mp4")).stem
    return directory / "previews" / scene_directory


def render_run(
    run_dir: Path,
    scene_ids: set[int] | None = None,
    quality: str = "final",
    force: bool = False,
    backend: RenderBackend | None = None,
    settings: HarnessSettings | None = None,
) -> RenderReport:
    from .creative_gates import require_legacy_render_gate
    require_legacy_render_gate(run_dir, quality)

    if quality not in {"draft", "final"}:
        raise ValueError("quality must be draft or final")
    store = RunStore.open(run_dir)
    settings = settings or HarnessSettings()
    script = store.read_script()
    config = load_simulation(store.root, script)
    known_ids = {scene.scene_id for scene in script.scenes}
    requested_ids = scene_ids or known_ids
    unknown = requested_ids - known_ids
    if unknown:
        raise ValueError(f"대본에 없는 씬 번호입니다: {sorted(unknown)}")
    selected = [scene for scene in script.scenes if scene.scene_id in requested_ids]

    preflight: list[tuple[Scene, Path, Path, Path]] = []
    for scene in selected:
        if scene.duration_seconds is None or not scene.audio_file:
            raise ValueError(f"씬 {scene.scene_id}의 음성 메타데이터가 없습니다.")
        audio_path = store.path(scene.audio_file)
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise FileNotFoundError(audio_path)
        output_path = _scene_output_path(store.root, scene, quality)
        original_path = _scene_original_output_path(store.root, scene, quality)
        existing = next(
            (path for path in (output_path, original_path) if path.exists()),
            None,
        )
        if existing is not None and not force:
            raise FileExistsError(
                f"이미 영상이 있습니다: {existing}. 덮어쓰려면 --force를 사용하세요."
            )
        preflight.append((scene, audio_path, output_path, original_path))

    encoder = EncoderSpec(
        preset=settings.render.x264_preset,
        crf=settings.render.x264_crf,
    )
    active_backend = backend or LocalRenderBackend(encoder=encoder)
    active_backend.check_dependencies()
    width, height = _output_dimensions(config, quality, settings)
    fps = settings.render.draft_fps if quality == "draft" else config.output.fps
    config_path = store.root / "simulation.json"
    config_sha = fingerprint(config_path.read_bytes())
    rendered: list[RenderedScene] = []

    for scene, audio_path, output_path, original_path in preflight:
        simulation_scene = config.scenes[scene.scene_id - 1]
        frame_count = math.ceil(scene.duration_seconds * fps)
        cache_dir = store.path(f".render-cache/{quality}/{scene.scene_id:02d}")
        cache_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.parent.mkdir(parents=True, exist_ok=True)
        job = {
            "scene_id": scene.scene_id,
            "title": scene.title,
            "template": simulation_scene.template,
            "simulation_day_start": simulation_scene.simulation_day_start,
            "simulation_day_end": simulation_scene.simulation_day_end,
            "duration_seconds": scene.duration_seconds,
            "frame_count": frame_count,
            "output_directory": str(cache_dir),
            "output": {"width": width, "height": height, "fps": fps},
            "physics": {
                "earth_period_days": config.physics.earth_period_days,
                "mars_period_days": config.physics.mars_period_days,
                "earth_orbit_radius": config.physics.earth_orbit_radius,
                "mars_orbit_radius": config.physics.mars_orbit_radius,
                "opposition_day": config.physics.opposition_day,
            },
            "style": {
                "seed": config.style.seed,
                "earth_scale": config.style.earth_scale,
                "mars_scale": config.style.mars_scale,
            },
        }
        active_backend.render_frames(job, cache_dir)
        active_backend.encode_original(
            cache_dir,
            original_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=scene.duration_seconds,
        )
        preview_paths = active_backend.create_previews(
            original_path,
            _scene_preview_directory(store.root, scene, quality),
            [
                index * settings.render.preview_interval_seconds
                for index in range(
                    math.ceil(scene.duration_seconds / settings.render.preview_interval_seconds)
                )
            ],
        )
        info = active_backend.encode_scene(
            original_path,
            audio_path,
            output_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=scene.duration_seconds,
        )
        rendered.append(
            RenderedScene(
                scene_id=scene.scene_id,
                title=scene.title,
                video_file=output_path.relative_to(store.root).as_posix(),
                original_video_file=original_path.relative_to(store.root).as_posix(),
                preview_files=[
                    path.relative_to(store.root).as_posix() for path in preview_paths
                ],
                frame_count=frame_count,
                duration_seconds=info.duration_seconds,
                width=info.width,
                height=info.height,
                fps=info.fps,
            )
        )
        if cache_dir.is_dir() and store.root in cache_dir.resolve().parents:
            shutil.rmtree(cache_dir)

    full_render = requested_ids == known_ids
    final_relative: str | None = None
    final_original_relative: str | None = None
    if full_render:
        scene_paths = [_scene_output_path(store.root, scene, quality) for scene in script.scenes]
        original_scene_paths = [
            _scene_original_output_path(store.root, scene, quality)
            for scene in script.scenes
        ]
        final_path = store.root / ("final-draft.mp4" if quality == "draft" else "final.mp4")
        final_original_path = store.root / (
            "video-only-draft.mp4" if quality == "draft" else "video-only.mp4"
        )
        existing_final = next(
            (path for path in (final_path, final_original_path) if path.exists()),
            None,
        )
        if existing_final is not None and not force:
            raise FileExistsError(
                f"이미 합본이 있습니다: {existing_final}. 덮어쓰려면 --force를 사용하세요."
            )
        transition = config.output.scene_transition
        transition_seconds = (
            transition.duration_seconds if transition.mode == "dip_to_black" else 0.0
        )
        transition_fade_seconds = (
            transition.fade_seconds if transition.mode == "dip_to_black" else 0.0
        )
        transition_frames = (
            max(4, round(transition_seconds * fps)) if transition_seconds > 0 else 0
        )
        total_duration = sum(
            math.ceil((scene.duration_seconds or 0) * fps) / fps
            for scene in script.scenes
        ) + max(0, len(script.scenes) - 1) * transition_frames / fps
        active_backend.concatenate(
            original_scene_paths,
            final_original_path,
            expected_duration=total_duration,
            require_audio=False,
            transition_seconds=transition_seconds,
            transition_fade_seconds=transition_fade_seconds,
        )
        active_backend.concatenate(
            scene_paths,
            final_path,
            expected_duration=total_duration,
            require_audio=True,
            transition_seconds=transition_seconds,
            transition_fade_seconds=transition_fade_seconds,
        )
        final_relative = final_path.relative_to(store.root).as_posix()
        final_original_relative = final_original_path.relative_to(store.root).as_posix()

    report = RenderReport(
        quality=quality,
        config_sha256=config_sha,
        science_checks=build_science_checks(config),
        scenes=rendered,
        final_file=final_relative,
        final_original_file=final_original_relative,
    )
    atomic_write(
        store.root / "render-report.json",
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="과학 시뮬레이션을 계산해 씬별 영상과 합본을 렌더합니다."
    )
    parser.add_argument("run_directory", type=Path, help="runs 아래의 실행 폴더")
    parser.add_argument(
        "--quality",
        choices=("draft", "final"),
        default="final",
        help="draft는 설정 해상도, final은 simulation.json 해상도",
    )
    parser.add_argument("--scenes", type=parse_scene_ids, help="렌더할 씬 번호: 2,5,7")
    parser.add_argument("--force", action="store_true", help="기존 영상을 덮어쓰기")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = render_run(
            args.run_directory,
            scene_ids=args.scenes,
            quality=args.quality,
            force=args.force,
        )
    except Exception as error:
        print(f"렌더 실패: {error}", file=sys.stderr)
        return 1
    for scene in report.scenes:
        print(f"SCENE {scene.scene_id:02d}: {scene.video_file}")
        print(f"ORIGINAL {scene.scene_id:02d}: {scene.original_video_file}")
    if report.final_file:
        print(f"음성 합본: {report.final_file}")
    if report.final_original_file:
        print(f"무음 합본: {report.final_original_file}")
    return 0
