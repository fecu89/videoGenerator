"""Per-language narration on top of the Korean master: translated text, own engine, scene-fit tempo."""
from __future__ import annotations
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from .creative_gates import _named_gate, require_translations
from .language_voices import LanguageVoice, LanguageVoices, RUN_LANGUAGE_VOICES, load_language_voices
from .models import Scene, ScriptArtifact
from .settings import ResolvedHarnessSettings, subtitle_language_list
from .storage import atomic_write, scene_filename
from .translations import load_translations
from .narration import split_narration_sentences
from .voice import create_synthesizer, synthesize_scenes
from .voice_audio import AudioResult, SceneFitError

ENGINE_ORDER = ("qwen3", "kokoro")
MIN_RMS_DB = -60.0


@dataclass(frozen=True)
class LanguageVoiceReport:
    language: str
    report_path: Path
    audio_files: dict[int, str]


def report_name(lang: str) -> str:
    return f"voice-generation-report-{lang}.json"


def fit_gate_name(lang: str) -> str:
    return f"translation-fit-gate-{lang}.json"


def engine_order(languages: Sequence[str], voices: LanguageVoices) -> list[str]:
    """Group languages by engine so each model is loaded once; Qwen (already resident for ko) first."""
    ordered: list[str] = []
    for engine in ENGINE_ORDER:
        ordered.extend(lang for lang in languages if voices.voices[lang].engine == engine)
    ordered.extend(lang for lang in languages if lang not in ordered)
    return ordered


def audio_health_issues(path: Path) -> list[str]:
    """Not silent and not clipped; quality itself is only reviewed for the Korean master."""
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    text = completed.stderr
    issues: list[str] = []
    mean = _volume(text, "mean_volume")
    peak = _volume(text, "max_volume")
    if mean is None or peak is None:
        return [f"audio_unreadable: {path.name}"]
    if mean < MIN_RMS_DB:
        issues.append(f"audio_silent: {path.name} mean {mean:.1f} dB")
    if peak >= 0.0:
        issues.append(f"audio_clipped: {path.name} peak {peak:.1f} dB")
    return issues


def _volume(text: str, key: str) -> float | None:
    for line in text.splitlines():
        if key in line:
            try:
                return float(line.split(key + ":")[1].split("dB")[0])
            except (IndexError, ValueError):
                return None
    return None


def _default_factory(lang: str, voice: LanguageVoice, settings: ResolvedHarnessSettings, scene_targets: Mapping[int, float]):
    if voice.engine == "kokoro":
        engine_settings = settings.voice.model_copy(update={"engine": "kokoro"})
        return create_synthesizer(engine_settings, language_voice=voice, scene_target_seconds=scene_targets)
    if voice.engine == "qwen3":
        engine_settings = settings.voice.model_copy(update={
            "engine": "qwen3", "model_id": voice.model_id, "speaker": voice.speaker, "language": voice.language,
            "instructions_file": "video_harness/agent/prompts/voice-neutral.txt", "emotion_mode": "off",
        })
        return create_synthesizer(engine_settings, scene_target_seconds=scene_targets)
    raise ValueError(f"language {lang} has no synthesis engine in {RUN_LANGUAGE_VOICES}")


def _translated_scenes(script: ScriptArtifact, run: Path, lang: str) -> list[Scene]:
    translations = load_translations(run)
    text_by_id = {scene.scene_id: scene.text.get(lang, "") for scene in translations.scenes}
    scenes = []
    for scene in script.scenes:
        payload = scene.model_dump(mode="python")
        payload.update(narration=text_by_id[scene.scene_id], audio_file=None, sentence_delivery=[], sentence_pauses=[])
        scenes.append(Scene.model_validate(payload))
    return scenes


def _scene_entry(result: AudioResult, target: float, relative_audio: str) -> dict[str, object]:
    generation = result.generation
    return {
        "scene_id": result.scene_id,
        "audio_file": relative_audio,
        "duration_seconds": round(result.duration_seconds, 3),
        "target_seconds": target,
        "tempo_factor": generation.tempo_factor,
        "sample_rate": generation.sample_rate,
        "sample_count": generation.sample_count,
        "sentence_leading_margin_ms": generation.sentence_leading_margin_ms,
        "sentence_trailing_margin_ms": generation.sentence_trailing_margin_ms,
        "sentences": [
            # Subtitle timing needs the encoded sentence length; the raw sample count
            # also holds the model's own silence and drifts cues away from speech.
            {"text": sentence.text, "sample_count": sentence.sample_count, "tempo_factor": sentence.tempo_factor,
             "output_seconds": sentence.output_seconds, "adjusted_speech_seconds": sentence.adjusted_speech_seconds,
             "pause_events": list(sentence.pause_events)}
            for sentence in generation.sentences
        ],
    }


def generate_language_audio(
    run_dir: Path,
    lang: str,
    *,
    settings: ResolvedHarnessSettings,
    synthesizer_factory: Callable[..., object] | None = None,
    scene_ids: set[int] | None = None,
    force: bool = False,
    synthesizer=None,
) -> LanguageVoiceReport:
    run = Path(run_dir).resolve()
    if lang not in subtitle_language_list(settings):
        raise ValueError(f"{lang}는 local_video.subtitle_languages에 없는 언어입니다.")
    require_translations(run)
    voices = load_language_voices(run)
    voice = voices.voices[lang]
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    targets: dict[int, float] = {}
    for scene in script.scenes:
        if scene.duration_seconds is None or not scene.audio_file:
            raise ValueError(f"scene {scene.scene_id}: 한국어 마스터 음성이 먼저 있어야 합니다.")
        targets[scene.scene_id] = scene.duration_seconds
    scenes = _translated_scenes(script, run, lang)
    if scene_ids:
        scenes = [scene for scene in scenes if scene.scene_id in scene_ids]
    output_dir = run / "audioFiles" / lang
    owned = synthesizer is None
    if synthesizer is None:
        factory = synthesizer_factory or _default_factory
        synthesizer = factory(lang, voice, settings, targets)
    elif hasattr(synthesizer, "configure"):
        synthesizer.configure(voice=voice.voice, lang_code=voice.lang_code, scene_target_seconds=targets)
    errors: list[str] = []
    results: list[AudioResult] = []
    try:
        # One scene at a time so a single over-long translation keeps every other scene's audio.
        for scene in scenes:
            try:
                results.extend(synthesize_scenes([scene], output_dir, synthesizer, force=force))
            except SceneFitError as error:
                detail = (f" (output {error.output_seconds:.2f}s > slot {error.slot_seconds:.2f}s)"
                          if getattr(error, "output_seconds", None) is not None else "")
                errors.append(f"scene_too_long: {error.scene_id} ×{error.ratio:.3f} > {getattr(error, 'limit', 1.25):.2f}{detail} — shorten the {lang} translation")
    except Exception as error:
        # A model/ffmpeg failure must not leave an older "passed" gate on disk.
        atomic_write(run / fit_gate_name(lang), json.dumps({"schema_version": 1, "status": "failed", "language": lang,
            "issues": [f"synthesis_error: {lang} {type(error).__name__}: {error}"]}, ensure_ascii=False, indent=2) + "\n")
        raise
    finally:
        close = getattr(synthesizer, "close", None)
        if owned and close is not None:
            close()
    for result in results:
        tolerance = 0.05
        if result.duration_seconds > targets[result.scene_id] + tolerance:
            errors.append(f"duration_over_target: {result.scene_id} {result.duration_seconds:.3f}s > {targets[result.scene_id]:.3f}s")
        errors.extend(audio_health_issues(result.path))
    if results:
        width = max(2, len(str(max(scene.scene_id for scene in script.scenes))))
        existing = _existing_report(run / report_name(lang))
        for result in results:
            scene = next(s for s in scenes if s.scene_id == result.scene_id)
            relative = (output_dir / scene_filename(scene, ".mp3", width)).relative_to(run).as_posix()
            # Per-scene text hash: editing one language or scene stales only that audio.
            existing[result.scene_id] = {**_scene_entry(result, targets[result.scene_id], relative),
                                         "text_sha256": _text_sha(scene.narration)}
        payload = {
            "schema_version": 1,
            "language": lang,
            "engine": voice.engine,
            "model_id": voice.model_id,
            "voice": voice.voice,
            "speaker": voice.speaker,
            "language_voices_sha256": _sha(run / RUN_LANGUAGE_VOICES),
            "translations_sha256": _sha(run / "translations.json"),
            "script_sha256": _sha(run / "script.json"),
            "targets": {str(k): v for k, v in sorted(targets.items())},
            "sentence_leading_margin_ms": 0 if getattr(settings.voice, 'pause_mode', 'legacy') == 'typed' else settings.voice.sentence_leading_margin_ms,
            "sentence_trailing_margin_ms": settings.voice.sentence_pause_ms if getattr(settings.voice, 'pause_mode', 'legacy') == 'typed' else settings.voice.sentence_trailing_margin_ms,
            "scenes": [existing[scene_id] for scene_id in sorted(existing)],
        }
        atomic_write(run / report_name(lang), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _named_gate(run, fit_gate_name(lang), errors, language=lang)
    return LanguageVoiceReport(lang, run / report_name(lang), {r.scene_id: r.path.relative_to(run).as_posix() for r in results})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def language_audio_issues(run_dir: Path, lang: str) -> list[str]:
    """Is the language's audio current for this run? Used before any localized assembly."""
    run = Path(run_dir).resolve()
    issues: list[str] = []
    gate = run / fit_gate_name(lang)
    status = json.loads(gate.read_text(encoding="utf-8")).get("status") if gate.is_file() else None
    if status != "passed":
        issues.append(f"language_audio_unverified: {lang} {fit_gate_name(lang)} is {status}")
    report_path = run / report_name(lang)
    if not report_path.is_file():
        return issues + [f"language_audio_missing: {lang} {report_name(lang)}"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checked = (("script_sha256", "script.json"), ("language_voices_sha256", RUN_LANGUAGE_VOICES))
    scenes = report.get("scenes", [])
    if scenes and all("text_sha256" in scene or scene.get("sentences") for scene in scenes):
        # Compare each scene with its own current translation, not the whole file:
        # by stored text hash, or for older reports by the sentences actually spoken.
        texts = {scene.scene_id: scene.text.get(lang, "") for scene in load_translations(run).scenes}
        def current(scene):
            text = texts.get(int(scene["scene_id"]), "")
            if "text_sha256" in scene:
                return _text_sha(text) == scene["text_sha256"]
            return split_narration_sentences(text) == [s.get("text") for s in scene["sentences"]]
        changed = [int(scene["scene_id"]) for scene in scenes if not current(scene)]
        if changed:
            issues.append(f"language_audio_stale: {lang} translations changed for scenes {changed} since the audio was made")
    else:
        checked = (("translations_sha256", "translations.json"),) + checked
    for key, filename in checked:
        current = _sha(run / filename) if (run / filename).is_file() else None
        if report.get(key) != current:
            issues.append(f"language_audio_stale: {lang} {filename} changed since the audio was made")
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    targets = {str(scene.scene_id): scene.duration_seconds for scene in script.scenes}
    if report.get("targets") != targets:
        issues.append(f"language_audio_stale: {lang} Korean scene durations changed since the audio was made")
    return issues


def _existing_report(path: Path) -> dict[int, dict[str, object]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(item["scene_id"]): item for item in payload.get("scenes", [])}


def generate_all_languages(run_dir: Path, *, settings: ResolvedHarnessSettings,
                           synthesizer_factory: Callable[..., object] | None = None, force: bool = False) -> list[LanguageVoiceReport]:
    run = Path(run_dir).resolve()
    voices = load_language_voices(run)
    reports: list[LanguageVoiceReport] = []
    failures: list[str] = []
    factory = synthesizer_factory or _default_factory
    languages = engine_order(subtitle_language_list(settings), voices)
    index = 0
    while index < len(languages):
        # One model load per (engine, model) group; languages in the group switch voice/lang_code in place.
        lead = voices.voices[languages[index]]
        group = [l for l in languages[index:] if (voices.voices[l].engine, voices.voices[l].model_id) == (lead.engine, lead.model_id)]
        index += len(group)
        shared = None
        for position, lang in enumerate(group):
            targets = _scene_targets(run)
            if position == 0:
                shared = factory(lang, voices.voices[lang], settings, targets)
            elif not hasattr(shared, "configure"):
                _close(shared)
                shared = factory(lang, voices.voices[lang], settings, targets)
            try:
                reports.append(generate_language_audio(run, lang, settings=settings, force=force, synthesizer=shared))
            except ValueError as error:
                failures.append(f"{lang}: {error}")
        _close(shared)
    if failures:
        raise ValueError("\n".join(failures))
    return reports


def _close(synthesizer) -> None:
    close = getattr(synthesizer, "close", None)
    if close is not None:
        close()


def _scene_targets(run: Path) -> dict[int, float]:
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    return {scene.scene_id: scene.duration_seconds for scene in script.scenes if scene.duration_seconds}
