from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Protocol, Sequence

from mutagen.mp3 import MP3

from .voice_audio import AudioResult
from .models import Scene, ScriptArtifact
from .settings import VoiceSettings
from .storage import atomic_write, scene_filename, scene_narration_text

if TYPE_CHECKING:
    from .settings import ResolvedHarnessSettings

_DEFAULT_VOICE_SETTINGS = VoiceSettings()
MIN_SCENE_SECONDS = _DEFAULT_VOICE_SETTINGS.min_scene_seconds
MAX_SCENE_SECONDS = _DEFAULT_VOICE_SETTINGS.max_scene_seconds


class SceneDurationError(RuntimeError):
    def __init__(self, report: DurationReport):
        self.report = report
        selected = ", ".join(str(scene_id) for scene_id in report.invalid_scene_ids)
        super().__init__(f"scene durations are outside the configured range: {selected}")


FileReplacer = Callable[[Path, Path], None]


def _replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


def _stage_next_to_destination(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    staged = Path(raw_path)
    try:
        shutil.copy2(source, staged)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def publish_files_atomically(
    publications: Mapping[Path, Path],
    *,
    replacer: FileReplacer | None = None,
) -> None:
    active_replacer = _replace_file if replacer is None else replacer
    ordered = sorted(publications.items(), key=lambda item: str(item[1]))
    with tempfile.TemporaryDirectory(prefix="video-generator-voice-publish-") as name:
        backup_root = Path(name)
        local_staged: dict[Path, Path] = {}
        backups: dict[Path, Path] = {}
        published: list[Path] = []
        try:
            for index, (source, destination) in enumerate(ordered):
                if not source.is_file():
                    raise RuntimeError(f"게시할 음성 산출물이 없습니다: {source}")
                if destination.exists():
                    if not destination.is_file() or destination.is_symlink():
                        raise RuntimeError(
                            f"최종 음성 산출물 경로가 일반 파일이 아닙니다: {destination}"
                        )
                    backup = backup_root / f"{index:04d}.backup"
                    shutil.copy2(destination, backup)
                    backups[destination] = backup
                local_staged[destination] = _stage_next_to_destination(
                    source,
                    destination,
                )

            try:
                for _, destination in ordered:
                    published.append(destination)
                    active_replacer(local_staged[destination], destination)
            except BaseException as publication_error:
                rollback_errors: list[BaseException] = []
                for destination in reversed(published):
                    try:
                        backup = backups.get(destination)
                        if backup is None:
                            destination.unlink(missing_ok=True)
                            continue
                        restoration = _stage_next_to_destination(backup, destination)
                        try:
                            active_replacer(restoration, destination)
                        finally:
                            restoration.unlink(missing_ok=True)
                    except BaseException as rollback_error:
                        rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise RuntimeError(
                        "voice publication failed and rollback was incomplete"
                    ) from publication_error
                raise
        finally:
            for path in local_staged.values():
                path.unlink(missing_ok=True)


@dataclass(frozen=True)
class SceneDuration:
    scene_id: int
    duration_seconds: float | None
    status: str
    audio_file: str | None


@dataclass(frozen=True)
class DurationReport:
    minimum_seconds: float
    maximum_seconds: float
    scenes: list[SceneDuration]

    @property
    def valid_scene_ids(self) -> list[int]:
        return [scene.scene_id for scene in self.scenes if scene.status == "valid"]

    @property
    def invalid_scene_ids(self) -> list[int]:
        return [scene.scene_id for scene in self.scenes if scene.status != "valid"]

    def to_dict(self) -> dict:
        return {
            "minimum_seconds": self.minimum_seconds,
            "maximum_seconds": self.maximum_seconds,
            "valid_scene_ids": self.valid_scene_ids,
            "invalid_scene_ids": self.invalid_scene_ids,
            "scenes": [asdict(scene) for scene in self.scenes],
        }


class SceneSynthesizer(Protocol):
    def synthesize(
        self,
        scenes: list[Scene],
        destinations: Mapping[int, Path],
    ) -> list[AudioResult]: ...


def create_synthesizer(settings: VoiceSettings, *, duration_reader=None, language_voice=None,
                       scene_target_seconds=None) -> SceneSynthesizer:
    reader = read_mp3_duration if duration_reader is None else duration_reader
    extra = {"scene_target_seconds": scene_target_seconds} if scene_target_seconds is not None else {}
    if settings.engine == "qwen3":
        from .mlx_voice import MLXAudioSynthesizer
        return MLXAudioSynthesizer(settings, duration_reader=reader, **extra)
    if settings.engine == "voxcpm2":
        raise ValueError("VoxCPM2 has been removed; refresh this run with Qwen settings before regenerating voice")
    if settings.engine == "kokoro":
        if language_voice is None or language_voice.engine != "kokoro":
            raise ValueError("kokoro engine requires a language voice (language-voices.json entry)")
        from .kokoro_voice import KokoroSynthesizer
        return KokoroSynthesizer(settings, voice=language_voice.voice, lang_code=language_voice.lang_code,
                                 model_id=language_voice.model_id, revision=language_voice.revision,
                                 duration_reader=reader, **extra)
    raise ValueError(f"unsupported voice engine: {settings.engine}")


def read_mp3_duration(path: Path) -> float:
    return float(MP3(path).info.length)


def duration_is_valid(
    duration: float,
    minimum: float = MIN_SCENE_SECONDS,
    maximum: float = MAX_SCENE_SECONDS,
) -> bool:
    return minimum <= duration <= maximum


def parse_scene_ids(value: str) -> set[int]:
    try:
        scene_ids = {int(part.strip()) for part in value.split(",") if part.strip()}
    except ValueError as error:
        raise ValueError("Scene IDs must be comma-separated integers") from error
    if not scene_ids or any(scene_id <= 0 for scene_id in scene_ids):
        raise ValueError("Scene IDs must be positive integers")
    return scene_ids


def synthesize_scenes(
    scenes: Iterable[Scene],
    output_dir: Path,
    synthesizer: SceneSynthesizer,
    force: bool = False,
) -> list[AudioResult]:
    scene_list = sorted(scenes, key=lambda scene: scene.scene_id)
    if not scene_list:
        return []
    width = max(2, len(str(max(scene.scene_id for scene in scene_list))))
    destinations = {
        scene.scene_id: output_dir / scene_filename(scene, ".mp3", width)
        for scene in scene_list
    }
    if not force:
        existing = [path for path in destinations.values() if path.exists()]
        if existing:
            raise FileExistsError(
                f"이미 음성이 있습니다: {existing[0]}. 덮어쓰려면 --force를 사용하세요."
            )

    results = synthesizer.synthesize(scene_list, destinations)
    result_by_id = {result.scene_id: result for result in results}
    if set(result_by_id) != set(destinations) or len(results) != len(result_by_id):
        raise RuntimeError("음성 합성 결과의 씬 목록이 요청과 다릅니다.")
    return [result_by_id[scene.scene_id] for scene in scene_list]


def _safe_audio_path(run_dir: Path, relative: str) -> Path:
    path = (run_dir / relative).resolve()
    if run_dir.resolve() not in path.parents:
        raise ValueError(f"Audio path escapes run directory: {relative}")
    return path


def build_duration_report(
    script: ScriptArtifact,
    run_dir: Path,
    duration_reader: Callable[[Path], float],
    minimum: float = MIN_SCENE_SECONDS,
    maximum: float = MAX_SCENE_SECONDS,
    audio_overrides: Mapping[int, Path] | None = None,
) -> DurationReport:
    entries: list[SceneDuration] = []
    overrides = audio_overrides or {}
    for scene in script.scenes:
        if not scene.audio_file:
            scene.duration_seconds = None
            entries.append(SceneDuration(scene.scene_id, None, "missing", None))
            continue

        audio_path = overrides.get(scene.scene_id)
        if audio_path is None:
            audio_path = _safe_audio_path(run_dir, scene.audio_file)
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            scene.duration_seconds = None
            entries.append(
                SceneDuration(scene.scene_id, None, "missing", scene.audio_file)
            )
            continue

        duration = round(float(duration_reader(audio_path)), 3)
        scene.duration_seconds = duration
        if duration < minimum:
            status = "short"
        elif duration > maximum:
            status = "long"
        else:
            status = "valid"
        entries.append(
            SceneDuration(scene.scene_id, duration, status, scene.audio_file)
        )

    return DurationReport(minimum, maximum, entries)


def _qwen_generation_scene_entry(result: AudioResult, settings) -> dict[str, object]:
    from .settings import PROJECT_ROOT
    from .mlx_voice import CONSISTENT_SAMPLING

    generation = result.generation
    configured_instruction = Path(settings.voice.instructions_file).expanduser()
    instruction_path = (
        configured_instruction
        if configured_instruction.is_absolute()
        else PROJECT_ROOT / configured_instruction
    )
    try:
        instruction_bytes = instruction_path.read_bytes()
    except OSError as error:
        raise RuntimeError(
            f"음성 전달 지시 파일을 읽을 수 없습니다: {instruction_path}: {error}"
        ) from error
    if settings.voice.generation_preset == "consistent":
        temperature, top_k, top_p, repetition_penalty = CONSISTENT_SAMPLING
    else:
        temperature = settings.voice.temperature
        top_k = settings.voice.top_k
        top_p = settings.voice.top_p
        repetition_penalty = settings.voice.repetition_penalty
    return {
        "scene_id": result.scene_id,
        "engine": "qwen3",
        "loudness": {key: value for key, value in settings.voice.model_dump().items() if key.startswith("loudness_")},
        "speed_mode": "qwen_legacy",
        "speaking_rate": settings.voice.speaking_rate,
        "model_id": settings.voice.model_id,
        "model_revision": settings.voice.model_revision,
        "speaker": settings.voice.speaker,
        "language": settings.voice.language,
        "generation_preset": settings.voice.generation_preset,
        "emotion_mode": settings.voice.emotion_mode,
        "target_syllables_per_second": (
            settings.voice.target_syllables_per_second
        ),
        "max_internal_pause_ms": settings.voice.max_internal_pause_ms,
        "temperature": temperature,
        "max_tokens": settings.voice.max_tokens,
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "instructions_file": settings.voice.instructions_file,
        "global_instruction_sha256": hashlib.sha256(instruction_bytes).hexdigest(),
        "narrative_role": generation.narrative_role,
        "sample_rate": generation.sample_rate,
        "sample_count": generation.sample_count,
        "sentence_leading_margin_ms": generation.sentence_leading_margin_ms,
        "sentence_trailing_margin_ms": generation.sentence_trailing_margin_ms,
        "tempo_factor": generation.tempo_factor,
        "sentences": [asdict(sentence) for sentence in generation.sentences],
    }

def _generation_scene_entry(result: AudioResult, settings) -> dict[str, object]:
    if settings.voice.engine == "qwen3":
        return _qwen_generation_scene_entry(result, settings)
    raise ValueError(f"unsupported master voice engine: {settings.voice.engine}")


def _merged_generation_report(
    run_dir: Path,
    results: Sequence[AudioResult],
    settings,
) -> dict[str, object]:
    report_path = run_dir / "voice-generation-report.json"
    existing_by_id: dict[int, dict[str, object]] = {}
    if report_path.is_file():
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"기존 음성 생성 보고서가 유효한 JSON이 아닙니다: {report_path}"
            ) from error
        if payload.get("schema_version") != 1 or not isinstance(
            payload.get("scenes"), list
        ):
            raise RuntimeError(f"지원하지 않는 음성 생성 보고서입니다: {report_path}")
        for item in payload["scenes"]:
            if not isinstance(item, dict) or not isinstance(item.get("scene_id"), int):
                raise RuntimeError(f"음성 생성 보고서 scene 항목이 잘못됐습니다: {report_path}")
            existing_by_id[item["scene_id"]] = item

    for result in results:
        existing_by_id[result.scene_id] = _generation_scene_entry(result, settings)
    typed = getattr(settings.voice, 'pause_mode', 'legacy') == 'typed'
    leading = 0 if typed else settings.voice.sentence_leading_margin_ms
    trailing = settings.voice.sentence_pause_ms if typed else settings.voice.sentence_trailing_margin_ms
    return {
        "schema_version": 1,
        "sentence_leading_margin_ms": leading,
        "sentence_trailing_margin_ms": trailing,
        "sentence_gap_milliseconds": leading + trailing,
        "scenes": [existing_by_id[scene_id] for scene_id in sorted(existing_by_id)],
    }


def generate_audio(
    script_path: Path,
    scene_ids: set[int] | None = None,
    force: bool = False,
    synthesizer: SceneSynthesizer | None = None,
    duration_reader: Callable[[Path], float] = read_mp3_duration,
    settings: ResolvedHarnessSettings | None = None,
) -> DurationReport:
    if settings is None:
        from .settings import HarnessSettings

        settings = HarnessSettings()
    if getattr(settings.voice, "engine", None) == "voxcpm2":
        raise RuntimeError("VoxCPM2 has been removed; explicitly refresh this run with Qwen settings before regenerating voice")
    if settings.schema_version not in (4, 5, 6) and not (settings.schema_version == 3 and settings.voice.engine == "qwen3"):
        raise RuntimeError(
            f"schema-v{settings.schema_version} run settings cannot regenerate local voice; run "
            f"python -m video_harness settings {script_path.parent} --refresh-settings"
        )
    script_path = script_path.resolve()
    script = ScriptArtifact.model_validate_json(script_path.read_text(encoding="utf-8"))
    known_ids = {scene.scene_id for scene in script.scenes}
    requested_ids = scene_ids or known_ids
    unknown_ids = requested_ids - known_ids
    if unknown_ids:
        raise ValueError(f"대본에 없는 씬 번호입니다: {sorted(unknown_ids)}")

    from .creative_gates import require_story_chain
    require_story_chain(script_path.parent)

    selected = [scene for scene in script.scenes if scene.scene_id in requested_ids]
    output_dir = script_path.parent / "audioFiles"
    width = max(2, len(str(max(known_ids))))
    final_destinations = {
        scene.scene_id: output_dir / scene_filename(scene, ".mp3", width)
        for scene in selected
    }
    if not force:
        existing = [path for path in final_destinations.values() if path.exists()]
        if existing:
            raise FileExistsError(
                f"이미 음성이 있습니다: {existing[0]}. 덮어쓰려면 --force를 사용하세요."
            )

    active_synthesizer = synthesizer or create_synthesizer(
        settings.voice,
        duration_reader=duration_reader,
    )
    with tempfile.TemporaryDirectory(
        prefix=".voice-stage-",
        dir=script_path.parent,
    ) as stage_name:
        stage_root = Path(stage_name)
        stage_audio_dir = stage_root / "audioFiles"
        try:
            results = synthesize_scenes(
                selected,
                stage_audio_dir,
                active_synthesizer,
                force=False,
            )
        finally:
            # An injected synthesizer may be shared across scene checkpoints;
            # its caller owns the lifetime. CLI-created models end with this job.
            if synthesizer is None:
                close = getattr(active_synthesizer, "close", None)
                if close is not None:
                    close()
        result_by_id = {result.scene_id: result for result in results}
        updated_script = ScriptArtifact.model_validate(
            script.model_dump(mode="python")
        )
        publications: dict[Path, Path] = {}
        audio_overrides: dict[int, Path] = {}
        for scene in updated_script.scenes:
            result = result_by_id.get(scene.scene_id)
            if result is None:
                continue
            final_path = final_destinations[scene.scene_id]
            scene.audio_file = final_path.relative_to(script_path.parent).as_posix()
            scene.duration_seconds = round(result.duration_seconds, 3)
            audio_overrides[scene.scene_id] = result.path
            publications[result.path] = final_path
            staged_sidecar = result.path.with_suffix(".txt")
            atomic_write(staged_sidecar, scene_narration_text(scene))
            publications[staged_sidecar] = final_path.with_suffix(".txt")

        report = build_duration_report(
            updated_script,
            script_path.parent,
            duration_reader,
            minimum=settings.voice.min_scene_seconds,
            maximum=settings.voice.max_scene_seconds,
            audio_overrides=audio_overrides,
        )
        invalid_selected = [
            entry
            for entry in report.scenes
            if entry.scene_id in requested_ids and entry.status != "valid"
        ]
        if invalid_selected:
            raise SceneDurationError(report)

        staged_script = stage_root / "script.json"
        staged_duration_report = stage_root / "duration-report.json"
        staged_generation_report = stage_root / "voice-generation-report.json"
        atomic_write(
            staged_script,
            updated_script.model_dump_json(indent=2) + "\n",
        )
        atomic_write(
            staged_duration_report,
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
        generation_report = _merged_generation_report(
            script_path.parent,
            results,
            settings,
        )
        atomic_write(
            staged_generation_report,
            json.dumps(generation_report, ensure_ascii=False, indent=2) + "\n",
        )
        publications[staged_script] = script_path
        publications[staged_duration_report] = script_path.parent / "duration-report.json"
        publications[staged_generation_report] = (
            script_path.parent / "voice-generation-report.json"
        )
        publish_files_atomically(publications)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Qwen3-TTS로 씬 음성을 생성하고 실제 길이를 측정합니다."
        )
    )
    parser.add_argument("script", type=Path, help="실행 폴더의 script.json")
    parser.add_argument("--engine", choices=["qwen3", "kokoro"])
    parser.add_argument("--model-id", type=str)
    parser.add_argument("--model-revision", type=str)
    parser.add_argument("--speaker", type=str)
    parser.add_argument("--language", type=str)
    parser.add_argument("--instructions-file", type=str)
    parser.add_argument("--generation-preset", type=str)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--repetition-penalty", type=float)
    parser.add_argument("--emotion-mode", type=str)
    parser.add_argument("--speaking-rate", type=float)
    parser.add_argument("--target-syllables-per-second", type=float)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--refresh-settings", action="store_true")
    parser.add_argument("--scenes", type=parse_scene_ids)
    parser.add_argument("--target-language", type=str, default=None,
        help="번역 언어 음성 생성: en|ja|zh|es 또는 all. 한국어 마스터는 건드리지 않습니다.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="모든 문장에 재사용할 고정 시드 (설정값을 덮어씀)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from .settings import resolve_run_settings

        base_settings = resolve_run_settings(args.script.parent, refresh=args.refresh_settings)
        if getattr(base_settings.voice, "engine", None) == "voxcpm2":
            raise RuntimeError("VoxCPM2 has been removed; use --refresh-settings with Qwen project settings")
        if base_settings.schema_version not in (4, 5, 6) and not (base_settings.schema_version == 3 and (args.engine or base_settings.voice.engine) == "qwen3"):
            raise RuntimeError(
                f"schema-v{base_settings.schema_version} run settings cannot regenerate local voice; run "
                f"python -m video_harness settings {args.script.parent} --refresh-settings"
            )
        settings = resolve_run_settings(
            args.script.parent,
            refresh=args.refresh_settings,
            cli_overrides={
                "voice": {
                    "engine": args.engine,
                    "model_id": args.model_id,
                    "model_revision": args.model_revision,
                    "speaker": args.speaker,
                    "language": args.language,
                    "instructions_file": args.instructions_file,
                    "generation_preset": args.generation_preset,
                    "temperature": args.temperature,
                    "top_k": args.top_k,
                    "top_p": args.top_p,
                    "repetition_penalty": args.repetition_penalty,
                    "emotion_mode": args.emotion_mode,
                    "speaking_rate": args.speaking_rate,
                    "target_syllables_per_second": args.target_syllables_per_second,
                    "max_tokens": args.max_tokens,
                    "seed": args.seed,
                }
            },
            persist=True,
        )
        if args.target_language:
            from .localize_voice import generate_all_languages, generate_language_audio
            if args.target_language == "all":
                reports = generate_all_languages(args.script.parent, settings=settings, force=args.force)
            else:
                reports = [generate_language_audio(args.script.parent, args.target_language, settings=settings,
                                                   scene_ids=args.scenes, force=args.force)]
            for item in reports:
                print(f"{item.language}: {len(item.audio_files)} scenes → {item.report_path.name}")
            return 0
        report = generate_audio(
            args.script,
            scene_ids=args.scenes,
            force=args.force,
            settings=settings,
        )
    except SceneDurationError as error:
        report = error.report
        for scene in report.scenes:
            duration = (
                f"{scene.duration_seconds:.3f}초"
                if scene.duration_seconds is not None
                else "음성 없음"
            )
            print(f"SCENE {scene.scene_id:02d}: {duration} [{scene.status}]")
        print(f"보정 필요 씬: {report.invalid_scene_ids}")
        return 1
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"음성 생성 실패: {error}", file=sys.stderr)
        return 2

    for scene in report.scenes:
        duration = (
            f"{scene.duration_seconds:.3f}초"
            if scene.duration_seconds is not None
            else "음성 없음"
        )
        print(f"SCENE {scene.scene_id:02d}: {duration} [{scene.status}]")
    if report.invalid_scene_ids:
        print(f"보정 필요 씬: {report.invalid_scene_ids}")
        return 1
    print(
        "모든 씬이 "
        f"{report.minimum_seconds:g}~{report.maximum_seconds:g}초 범위입니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
