"""Copy-ready upload text: per language, the title and description for the film and its short.

Every description ends with the credits the run actually owes: the 3D models in the run's
`assets/` folder (title, creator, source and licence read from each GLB file), the
and the background music. The titles and description are the ones written
with the script and their translations in `translations.json`.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .localize import MASTER, language_outputs
from .models import ScriptArtifact
from .settings import PromotionSettings, resolve_run_settings
from .shorts import OVERRIDES_FILENAME, SHORTS_DIR, load_upload_overrides, shorts_name, shorts_titles
from .storage import atomic_write
from .translations import TRANSLATIONS_FILENAME, Translations, load_translations

UPLOAD_FILENAME = "upload.md"
LABELS = {
    "ko": ("한국어", "3D 모델 (수정하여 사용)", "배경음악"),
    "en": ("English", "3D models (modified)", "Music"),
    "ja": ("日本語", "3Dモデル（改変して使用）", "BGM"),
    "zh": ("中文", "3D模型（经修改后使用）", "背景音乐"),
    "es": ("Español", "Modelos 3D (modificados)", "Música"),
}


@dataclass(frozen=True)
class ModelCredit:
    file: str
    title: str | None = None
    author: str | None = None
    source: str | None = None
    license: str | None = None
    license_url: str | None = None

    @property
    def line(self) -> str:
        if not self.title:
            return f"- {Path(self.file).stem}"
        credit = f'- "{self.title}"' + (f" by {self.author}" if self.author else "")
        if self.source:
            credit += f" — {self.source}"
        return credit + (f" ({self.license})" if self.license else "")


def _name_and_url(value: object) -> tuple[str | None, str | None]:
    """'CC-BY-4.0 (http://…)' -> ('CC-BY-4.0', 'http://…')."""
    text = str(value or "").strip()
    match = re.match(r"^(.*?)\s*\((https?://[^)]+)\)\s*$", text)
    return (match.group(1).strip() or None, match.group(2)) if match else (text or None, None)


def read_model_credit(path: Path, relative: str) -> ModelCredit:
    """Attribution a marketplace wrote into the GLB's asset.extras; only the file name when there is none."""
    try:
        with path.open("rb") as handle:
            magic, _, _ = struct.unpack("<4sII", handle.read(12))
            length, kind = struct.unpack("<I4s", handle.read(8))
            if magic != b"glTF" or kind != b"JSON":
                return ModelCredit(relative)
            extras = json.loads(handle.read(length)).get("asset", {}).get("extras") or {}
    except (OSError, ValueError, struct.error):
        return ModelCredit(relative)
    author, _ = _name_and_url(extras.get("author"))
    license_name, license_url = _name_and_url(extras.get("license"))
    if license_name:
        license_name = re.sub(r"^CC-", "CC ", license_name).replace("-", " ") if license_name.startswith("CC-") else license_name
    return ModelCredit(relative, title=str(extras.get("title") or "").strip() or None, author=author,
                       source=str(extras.get("source") or "").strip() or None, license=license_name, license_url=license_url)


def model_credits(run_dir: Path) -> list[ModelCredit]:
    root = Path(run_dir) / "assets"
    if not root.is_dir():
        return []
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".glb", ".gltf", ".usdz", ".obj", ".fbx"})
    credits = [read_model_credit(path, path.relative_to(root).as_posix()) for path in files]
    seen: set[tuple] = set()
    unique = []
    for credit in credits:
        key = (credit.title, credit.author, credit.source) if credit.title else (credit.file,)
        if key not in seen:
            seen.add(key)
            unique.append(credit)
    return unique


def credit_warnings(credits: Sequence[ModelCredit]) -> list[str]:
    warnings = []
    for credit in credits:
        name = (credit.license or "").upper()
        if not credit.title:
            warnings.append(f"`{credit.file}`: 파일 안에 출처·저작자·라이선스가 없습니다. `assets/CREDITS.md`에서 확인해 표기를 채우세요.")
        elif not credit.license:
            warnings.append(f"`{credit.file}`: 라이선스가 적혀 있지 않습니다. 출처에서 확인하세요.")
        elif re.search(r"\bNC\b", name):
            warnings.append(f"`{credit.file}`: 비영리 전용({credit.license})입니다. 수익 창출 영상에는 쓸 수 없습니다.")
        elif re.search(r"\bND\b", name):
            warnings.append(f"`{credit.file}`: 변경 금지({credit.license})입니다. 수정해서 쓴 장면이 있는지 확인하세요.")
    return warnings


def credits_block(lang: str, credits: Sequence[ModelCredit], music: str | None, *, include_urls: bool = True) -> str:
    _, models_label, music_label = LABELS.get(lang, LABELS["en"])
    lines: list[str] = []
    if credits:
        lines.append(models_label)
        lines.extend((credit if include_urls else replace(credit, source=None)).line for credit in credits)
        licenses = {credit.license: credit.license_url for credit in credits if credit.license and credit.license_url}
        if include_urls:
            lines.extend(f"{name}: {url}" for name, url in sorted(licenses.items()))
    if music:
        lines.extend(([""] if lines else []) + [f"{music_label}: {music}"])
    return "\n".join(lines)


def without_web_urls(text: str) -> str:
    """Keep readable link labels and credit names in copy for channels without URLs."""
    text = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", text, flags=re.I)
    text = re.sub(r'''(?:https?://|www\.)[^\s<>()\[\]"'，。！？、]+''', "", text, flags=re.I)
    text = re.sub(r'''(?<![\w@])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::[0-9]+)?(?:[/#?][^\s<>()\[\]"'，。！？、]*)?''', "", text, flags=re.I)
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip(" \t—:;") for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _box(text: str) -> list[str]:
    return ["```text", text.strip(), "```", ""]


def _texts(script: ScriptArtifact, translations: Translations | None, lang: str,
           overrides: dict[str, dict[str, str]] | None = None) -> tuple[str, str]:
    """(title, description); a missing description falls back to the film's opening narration.
    The run's upload-overrides.json wins over both."""
    title, description = _declared_texts(script, translations, lang)
    overrides = overrides or {}
    return overrides.get("title", {}).get(lang, title), overrides.get("description", {}).get(lang, description)


def _declared_texts(script: ScriptArtifact, translations: Translations | None, lang: str) -> tuple[str, str]:
    if lang == MASTER:
        return script.selected_topic.title, script.upload_description or script.scenes[0].narration
    if translations is None:
        return "", ""
    opening = next((scene.text.get(lang, "") for scene in translations.scenes if scene.scene_id == 1), "")
    return translations.title.get(lang, "").strip(), translations.description.get(lang, "").strip() or opening.strip()


def upload_sheet(run_dir: Path) -> dict:
    """Everything the upload page shows: per language the film's and the short's title and description."""
    run = Path(run_dir).resolve()
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    settings = resolve_run_settings(run, persist=False)
    languages = language_outputs(settings) or [MASTER]
    translations = load_translations(run) if (run / TRANSLATIONS_FILENAME).is_file() else None
    credits = model_credits(run)
    music_file = getattr(getattr(settings, "music", None), "file", "") or ""
    music = Path(music_file).stem if music_file.strip() else None
    short_titles = shorts_titles(run, languages)
    overrides = load_upload_overrides(run)
    promotion = getattr(settings, "promotion", None)
    override_path = run / OVERRIDES_FILENAME
    if override_path.is_file():
        metadata = json.loads(override_path.read_text(encoding="utf-8"))
        if "promotion" in metadata:
            promotion = PromotionSettings.model_validate(metadata["promotion"])
    entries = []
    for lang in languages:
        title, description = _texts(script, translations, lang, overrides)
        omit_urls = promotion is not None and promotion.locale_mode == "ko_only" and lang != MASTER
        block = credits_block(lang, credits, music, include_urls=not omit_urls)
        url = promotion.url_for(lang) if promotion else ""
        website_label = {"ko": "웹사이트", "en": "Website", "ja": "ウェブサイト", "zh": "网站", "es": "Sitio web"}.get(lang, "Website")
        promotion_block = f"{website_label}: {url}" if url else ""
        entry = {"lang": lang, "name": LABELS.get(lang, (lang,))[0], "title": title,
                 "description": "\n\n".join(part for part in (description, promotion_block, block) if part),
                 "shorts_title": None, "shorts_description": None}
        if (run / SHORTS_DIR / shorts_name(lang, "final")).is_file():
            entry["shorts_title"] = short_titles.get(lang) or title
            entry["shorts_description"] = "\n\n".join(part for part in (description, "#Shorts", promotion_block, block) if part)
        if omit_urls:
            for key in ("title", "description", "shorts_title", "shorts_description"):
                if entry[key] is not None:
                    entry[key] = without_web_urls(entry[key])
        entries.append(entry)
    return {"title": script.selected_topic.title, "warnings": credit_warnings(credits), "languages": entries}


def upload_markdown(run_dir: Path) -> str:
    sheet = upload_sheet(run_dir)
    lines = [f"# 업로드 문구 — {sheet['title']}", "",
             "언어별로 제목과 설명을 코드 상자에서 그대로 복사해 붙입니다. 설명 끝의 출처 표기는 지우지 않습니다.", ""]
    if sheet["warnings"]:
        lines += ["## 올리기 전에 확인", "", *(f"- {warning}" for warning in sheet["warnings"]), ""]
    for entry in sheet["languages"]:
        lines += [f"## {entry['name']} ({entry['lang']})", ""]
        if not entry["title"]:
            lines += [f"> 영상 제목 번역이 없습니다. `translations.json`의 `title.{entry['lang']}`을 채운 뒤 `upload-text`를 다시 실행하세요.", ""]
        lines += ["**영상 제목**", "", *_box(entry["title"] or "—"), "**영상 설명**", "", *_box(entry["description"] or "—")]
        if entry["shorts_description"] is not None:
            lines += ["**쇼츠 제목**", "", *_box(entry["shorts_title"] or "—"), "**쇼츠 설명**", "", *_box(entry["shorts_description"])]
    return "\n".join(lines).rstrip() + "\n"


def write_upload_text(run_dir: Path) -> Path:
    path = Path(run_dir).resolve() / UPLOAD_FILENAME
    atomic_write(path, upload_markdown(run_dir))
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="언어별 유튜브 제목·설명과 출처 표기를 upload.md로 만듭니다.")
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args(argv)
    try:
        path = write_upload_text(args.run_directory)
    except (OSError, ValueError) as error:
        print(f"업로드 문구 생성 실패: {error}", file=sys.stderr)
        return 1
    print(f"업로드 문구 완료: {path}")
    return 0
