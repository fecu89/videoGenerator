"""Agent-written translations, budgeted by the Korean master's scene durations."""
from __future__ import annotations
import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from pydantic import Field
from .language_voices import LanguageVoices, load_language_voices
from .models import ScriptArtifact, StrictModel
from .storage import atomic_write
from .voice_audio import spoken_unit_count

TRANSLATIONS_FILENAME = "translations.json"
BUDGET_HEADROOM = 1.25
_TERMINATORS = ".?!。！？…"
_CLOSERS = "\"'”’)]」』»"


class TranslatedScene(StrictModel):
    scene_id: int = Field(ge=1)
    budget_seconds: float = Field(gt=0)
    text: dict[str, str]


class Translations(StrictModel):
    schema_version: Literal[1] = 1
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    languages: list[str]
    title: dict[str, str] = Field(default_factory=dict)
    shorts_title: dict[str, str] = Field(default_factory=dict)
    description: dict[str, str] = Field(default_factory=dict)
    scenes: list[TranslatedScene]


def _script_sha(run_dir: Path) -> str:
    return hashlib.sha256((Path(run_dir) / "script.json").read_bytes()).hexdigest()


def scaffold_translations(run_dir: Path, languages: Sequence[str]) -> Translations:
    run = Path(run_dir)
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    scenes = []
    for scene in script.scenes:
        if scene.duration_seconds is None:
            raise ValueError(f"scene {scene.scene_id} has no Korean duration; generate the master voice first")
        scenes.append(TranslatedScene(scene_id=scene.scene_id, budget_seconds=scene.duration_seconds,
                                      text={lang: "" for lang in languages}))
    empty = {lang: "" for lang in languages}
    return Translations(script_sha256=_script_sha(run), languages=list(languages),
                        title=dict(empty), shorts_title=dict(empty), description=dict(empty), scenes=scenes)


def write_translations(run_dir: Path, translations: Translations, *, force: bool = False) -> Path:
    path = Path(run_dir) / TRANSLATIONS_FILENAME
    if path.exists() and not force:
        raise FileExistsError(f"이미 번역 파일이 있습니다: {path}. 덮어쓰려면 --force를 사용하세요.")
    atomic_write(path, translations.model_dump_json(indent=2) + "\n")
    return path


def load_translations(run_dir: Path) -> Translations:
    return Translations.model_validate_json((Path(run_dir) / TRANSLATIONS_FILENAME).read_text(encoding="utf-8"))


def speech_estimate_seconds(text: str, lang: str, voices: LanguageVoices) -> float:
    return spoken_unit_count(text) / voices.voices[lang].units_per_second


def translation_issues(translations: Translations, script: ScriptArtifact, script_sha: str,
                       voices: LanguageVoices, languages: Sequence[str]) -> list[str]:
    issues: list[str] = []
    if translations.script_sha256 != script_sha:
        issues.append("translation_stale: script.json changed after translations were written")
    # Upload texts are translated only when the script declares the Korean original.
    for code, declared, texts in (("shorts_title", script.shorts_title, translations.shorts_title),
                                  ("title", script.upload_description, translations.title),
                                  ("description", script.upload_description, translations.description)):
        if declared:
            issues.extend(f"{code}_missing: {lang}" for lang in languages if not texts.get(lang, "").strip())
    by_id = {scene.scene_id: scene for scene in translations.scenes}
    for scene in script.scenes:
        entry = by_id.get(scene.scene_id)
        if entry is None:
            issues.extend(f"translation_missing: {scene.scene_id}/{lang}" for lang in languages)
            continue
        for lang in languages:
            text = entry.text.get(lang, "").strip()
            if not text:
                issues.append(f"translation_missing: {scene.scene_id}/{lang}")
                continue
            if text.rstrip(_CLOSERS)[-1:] not in tuple(_TERMINATORS):
                issues.append(f"translation_unterminated: {scene.scene_id}/{lang} must end with a sentence mark")
            if lang not in voices.voices:
                issues.append(f"translation_language_unknown: {lang} missing in language-voices.json")
                continue
            estimate = speech_estimate_seconds(text, lang, voices)
            limit = entry.budget_seconds * BUDGET_HEADROOM
            if estimate > limit:
                issues.append(f"translation_too_long: {scene.scene_id}/{lang} est {estimate:.1f}s > {entry.budget_seconds:.3f}×{BUDGET_HEADROOM}")
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="한국어 장면 길이를 예산으로 한 빈 번역 틀(translations.json)을 만듭니다. 에이전트가 장면 text와 title·shorts_title·description을 채웁니다.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from .settings import resolve_run_settings, subtitle_language_list
        settings = resolve_run_settings(args.run_directory)
        languages = subtitle_language_list(settings)
        if not languages:
            raise ValueError("local_video.subtitle_languages가 비어 있습니다.")
        load_language_voices(args.run_directory)
        path = write_translations(args.run_directory, scaffold_translations(args.run_directory, languages), force=args.force)
    except (OSError, ValueError) as error:
        print(f"번역 틀 생성 실패: {error}", file=sys.stderr)
        return 1
    print(f"번역 틀 생성 완료: {path} ({', '.join(languages)})")
    return 0
