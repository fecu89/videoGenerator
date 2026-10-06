"""Vertical shorts cut from the finished film: one 1080x1920 video per language.

Each language gets its own audio and its own burned subtitles, re-timed for the faster
playback and laid out for a portrait screen: the middle of the landscape picture sits in
the upper middle over a blurred copy of itself, the shorts title stays above it and the
subtitles sit below it. The title is the one decided with the script (`shorts_title`) and
its translations in `translations.json`.

A short carries only the core of the film: scenes the script marks `in_shorts: false` are
cut out, and the result must fit the platform's length limit.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .language_voices import load_language_voices
from .localize import MASTER, ass_filter_argument, delivery_mode, final_name, language_outputs
from .media import probe_media
from .models import ScriptArtifact
from .sequence_plans import load_local_sequence_plan
from .settings import resolve_run_settings
from .storage import atomic_write
from .translations import TRANSLATIONS_FILENAME, load_translations

SHORTS_DIR = "shorts"
OVERRIDES_FILENAME = "upload-overrides.json"   # titles and descriptions decided after the script was approved
SPEED = 1.15
MAX_SECONDS = 180.0        # longest video YouTube accepts as a Short
WIDTH, HEIGHT = 1080, 1920
KEEP = 0.84                # share of the landscape width that is kept
PICTURE_TOP = 500          # top of the picture; the title sits above it, subtitles below it
TITLE_GAP = 70             # space between the title and the top of the picture
TITLE_MAX_SIZE = 92
TITLE_WIDTH = 980          # widest a one-line title may be
SUBTITLE_SIZE = {"ko": 70, "ja": 66, "zh": 70}
DEFAULT_SUBTITLE_SIZE = 64
CJK_LINE = {"ja": 13, "zh": 13}   # characters per subtitle line where there are no spaces to wrap at
FALLBACK_FONT = "Apple SD Gothic Neo"
_BREAK_AFTER = "、。，,；：？！"
_NEVER_FIRST = _BREAK_AFTER + "）」』"


def shorts_name(lang: str, quality: str) -> str:
    return f"shorts-{lang}.mp4" if quality == "final" else f"shorts-{lang}-draft.mp4"


def load_upload_overrides(run_dir: Path) -> dict[str, dict[str, str]]:
    """Per-language `title`, `shorts_title` and `description` for a run whose approved script and
    voiced translations cannot be edited any more (both are hash-bound to approvals and audio)."""
    path = Path(run_dir) / OVERRIDES_FILENAME
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: {lang: str(text).strip() for lang, text in (data.get(key) or {}).items() if str(text).strip()}
            for key in ("title", "shorts_title", "description")}


def save_shorts_title_overrides(run_dir: Path, titles: Mapping[str, str]) -> None:
    """Keep titles given on the command line, so upload.md shows the title burned into each short."""
    if not titles:
        return
    path = Path(run_dir) / OVERRIDES_FILENAME
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["shorts_title"] = {**(data.get("shorts_title") or {}), **titles}
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def shorts_titles(run_dir: Path, languages: Sequence[str], overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Korean from the script, the rest from translations.json, then the run's saved overrides,
    then `overrides`; a language without a title gets none."""
    run = Path(run_dir)
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    titles = {MASTER: script.shorts_title or script.selected_topic.title}
    if (run / TRANSLATIONS_FILENAME).is_file():
        titles.update({lang: text.strip() for lang, text in load_translations(run).shorts_title.items() if text.strip()})
    titles.update(load_upload_overrides(run).get("shorts_title", {}))
    titles.update({lang: text.strip() for lang, text in (overrides or {}).items() if text.strip()})
    return {lang: titles[lang] for lang in languages if lang in titles}


def estimated_seconds(scenes: Sequence[Mapping[str, object]], syllables_per_second: float) -> float:
    """Length of the short from the script.json scenes it keeps: measured voice when it exists, else a reading estimate."""
    from .voice_audio import spoken_unit_count

    kept = [scene for scene in scenes if scene.get("in_shorts", True)]
    return sum(float(scene.get("duration_seconds") or 0) or spoken_unit_count(str(scene.get("narration", ""))) / syllables_per_second
               for scene in kept) / SPEED


def require_shorts_length(run_dir: Path) -> float:
    """Refuse a script whose short would run past the platform limit; returns the estimated seconds."""
    run = Path(run_dir)
    scenes = json.loads((run / "script.json").read_text(encoding="utf-8")).get("scenes", [])
    if not any(scene.get("in_shorts", True) for scene in scenes):
        raise ValueError("쇼츠에 넣을 장면이 없습니다. 핵심 장면의 in_shorts를 true로 두세요.")
    settings = resolve_run_settings(run if (run / "run-settings.json").is_file() else None, persist=False)
    seconds = estimated_seconds(scenes, settings.voice.target_syllables_per_second)
    if seconds > MAX_SECONDS:
        raise ValueError(f"쇼츠 예상 길이가 {seconds:.0f}초로 {MAX_SECONDS:.0f}초 한도를 넘습니다. "
                         "생략해도 흐름이 이어지는 장면에 in_shorts: false를 지정해 핵심만 남기세요.")
    return seconds


def kept_segments(run_dir: Path) -> list[tuple[float, float]] | None:
    """Timeline ranges (seconds) of the scenes kept in the short; None when every scene is kept."""
    run = Path(run_dir)
    script = ScriptArtifact.model_validate_json((run / "script.json").read_text(encoding="utf-8"))
    kept = {scene.scene_id for scene in script.scenes if scene.in_shorts}
    if len(kept) == len(script.scenes):
        return None
    local = load_local_sequence_plan(run / "local-sequence-plan.json")
    fps = local.defaults.fps
    segments: list[tuple[float, float]] = []
    cursor = 0
    for sequence in local.sequences:
        for span in sorted(sequence.scene_spans, key=lambda item: item.start_frame):
            if span.scene_id not in kept:
                continue
            start, end = (cursor + span.start_frame) / fps, (cursor + span.end_frame) / fps
            if segments and abs(segments[-1][1] - start) < 1e-6:
                segments[-1] = (segments[-1][0], end)
            else:
                segments.append((start, end))
        cursor += sequence.duration_frames
    if not segments:
        raise ValueError("쇼츠에 넣을 장면이 없습니다. 핵심 장면의 in_shorts를 true로 두세요.")
    return segments


def cut_cues(cues: Sequence[tuple[float, float, str]], segments: Sequence[tuple[float, float]] | None) -> list[tuple[float, float, str]]:
    """Drop subtitles of the cut scenes and move the rest onto the shortened timeline."""
    if segments is None:
        return list(cues)
    moved = []
    for start, end, text in cues:
        offset = 0.0
        for seg_start, seg_end in segments:
            if seg_start - 1e-3 <= start < seg_end:
                moved.append((offset + max(start, seg_start) - seg_start, offset + min(end, seg_end) - seg_start, text))
                break
            offset += seg_end - seg_start
    return moved


def title_size(text: str) -> int:
    """Largest size up to TITLE_MAX_SIZE that keeps the title on one line (measured bold glyph widths)."""
    units = sum(1.0 if unicodedata.east_asian_width(ch) in "WF" else 0.35 if ch.isspace() else 0.70 for ch in text)
    return max(40, min(TITLE_MAX_SIZE, int(TITLE_WIDTH / (max(units, 1.0) * 0.72))))


def wrap_cjk(text: str, limit: int) -> list[str]:
    """Japanese and Chinese have no spaces for the renderer to wrap at: cut lines here,
    after punctuation when one falls in the last third of a line, and never leave a
    closing mark at the start of the next line."""
    count = -(-len(text) // limit)
    limit = min(limit, -(-len(text) // count) + 1)       # even out the lines instead of leaving a stub
    lines = []
    while len(text) > limit:
        cut = limit
        for k in range(limit, limit - limit // 3, -1):
            if text[k - 1] in _BREAK_AFTER:
                cut = k
                break
        while cut < len(text) and text[cut] in _NEVER_FIRST:
            cut += 1
        lines.append(text[:cut])
        text = text[cut:]
    if text:
        lines.append(text)
    return lines


def subtitle_cues(path: Path, lang: str) -> list[tuple[float, float, str]]:
    """(start, end, text) from an .srt, with its landscape line breaks replaced by portrait ones."""
    rows = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        lines = block.strip().split("\n")
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (sum(float(x) * m for x, m in zip(re.split("[:,]", stamp.strip()), (3600, 60, 1, .001)))
                      for stamp in lines[1].split("-->"))
        parts = [line.strip() for line in lines[2:]]
        text = "\\N".join(wrap_cjk("".join(parts), CJK_LINE[lang])) if lang in CJK_LINE else " ".join(parts)
        rows.append((start, end, text))
    return rows


def _stamp(seconds: float) -> str:
    cs = round(seconds * 100)
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def shorts_ass(*, lang: str, font: str, title: str | None, cues: Sequence[tuple[float, float, str]]) -> str:
    picture_bottom = PICTURE_TOP + round(WIDTH * 9 / 16 / KEEP)
    rest = "&H00FFFFFF,&H00201A0F,&H80000000,1,0,0,0,100,100,0,0,1,4,2"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {WIDTH}", f"PlayResY: {HEIGHT}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Sub,{font},{SUBTITLE_SIZE.get(lang, DEFAULT_SUBTITLE_SIZE)},&H00FFFFFF,{rest},8,70,70,{picture_bottom + 56},1",
    ]
    if title:
        lines.append(f"Style: Title,{font},{title_size(title)},&H0078D7FF,{rest},2,30,30,{HEIGHT - PICTURE_TOP + TITLE_GAP},1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    if title:
        lines.append(f"Dialogue: 0,{_stamp(0)},{_stamp(36000)},Title,,0,0,0,,{title}")
    lines += [f"Dialogue: 0,{_stamp(a / SPEED)},{_stamp(b / SPEED)},Sub,,0,0,0,,{text}" for a, b, text in cues]
    return "\n".join(lines) + "\n"


def _filter_graph(ass: Path, audio_input: int, segments: Sequence[tuple[float, float]] | None = None) -> str:
    keep = "+".join(f"gte(t,{start:.4f})*lt(t,{end:.4f})" for start, end in segments or [])
    cut_video = f"select='{keep}',setpts=N/FRAME_RATE/TB," if keep else ""
    cut_audio = f"aselect='{keep}',asetpts=N/SR/TB," if keep else ""
    return (
        f"[0:v]{cut_video}setpts=PTS/{SPEED},split=2[a][b];"
        f"[a]scale=-2:{HEIGHT},crop={WIDTH}:{HEIGHT},boxblur=28:4,eq=brightness=-0.22:saturation=0.8[bg];"
        f"[b]crop=iw*{KEEP}:ih,scale={WIDTH}:-2:flags=lanczos[fg];"
        f"[bg][fg]overlay=0:{PICTURE_TOP}[v0];"
        f"[v0]{ass_filter_argument(ass)}[v];"
        f"[{audio_input}:a]{cut_audio}atempo={SPEED}[au]")


def build_shorts(
    run_dir: Path,
    *,
    quality: str = "final",
    titles: Mapping[str, str] | None = None,
    out_dir: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[Path]:
    """Write shorts/shorts-<lang>.mp4 for every delivered language; [] when the film is already vertical."""
    run = Path(run_dir).resolve()
    out = Path(out_dir).resolve() if out_dir else run / SHORTS_DIR
    video = run / ("final.mp4" if quality == "final" else "final-draft.mp4")
    if not video.is_file():
        raise FileNotFoundError(f"쇼츠를 만들 영상이 없습니다: {video.name}")
    info = probe_media(video)
    if info.width <= info.height:
        return []
    settings = resolve_run_settings(run, persist=False)
    languages = language_outputs(settings) or [MASTER]
    delivery = delivery_mode(settings)
    voices = load_language_voices(run).voices
    resolved_titles = shorts_titles(run, languages, titles)
    segments = kept_segments(run)
    length = (sum(end - start for start, end in segments) if segments else info.duration_seconds) / SPEED
    if length > MAX_SECONDS:
        raise ValueError(f"쇼츠가 {length:.0f}초로 {MAX_SECONDS:.0f}초 한도를 넘습니다. script.json에서 생략할 장면에 in_shorts: false를 지정하세요.")
    out.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for lang in languages:
        audio = run / final_name(lang, quality, delivery)
        if not audio.is_file():
            if lang != MASTER:
                raise FileNotFoundError(f"{lang} 완성 음성이 없습니다: {audio.name}")
            audio = video
        srt = run / "subtitles" / f"{lang}.srt"
        ass = out / f"shorts-{lang}.ass"
        font = voices[lang].font if lang in voices else FALLBACK_FONT
        atomic_write(ass, shorts_ass(lang=lang, font=font, title=resolved_titles.get(lang),
                                     cues=cut_cues(subtitle_cues(srt, lang), segments) if srt.is_file() else []))
        target = out / shorts_name(lang, quality)
        partial = target.with_name(target.stem + ".partial.mp4")
        inputs = ["-i", str(video)] + ([] if audio == video else ["-i", str(audio)])
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
                   "-filter_complex", _filter_graph(ass, 0 if audio == video else 1, segments), "-map", "[v]", "-map", "[au]",
                   "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(partial)]
        try:
            completed = runner(command, capture_output=True, text=True)
            if getattr(completed, "returncode", 0):
                raise RuntimeError(f"쇼츠 제작 실패 {target.name}: {getattr(completed, 'stderr', '')[-800:]}")
            if not partial.is_file() or partial.stat().st_size == 0:
                raise RuntimeError(f"쇼츠 결과가 없습니다: {target.name}")
            partial.replace(target)
        finally:
            if partial.exists():
                partial.unlink()
        outputs.append(target)
    return outputs


def _title_override(value: str) -> tuple[str, str]:
    lang, separator, text = value.partition("=")
    if not separator or not lang.strip() or not text.strip():
        raise argparse.ArgumentTypeError("--title은 LANG=제목 형식입니다 (예: en=Why Typhoons Head Northwest)")
    return lang.strip().lower(), text.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="완성 영상에서 언어별 세로 쇼츠(1080x1920)를 만듭니다.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--quality", choices=("draft", "final"), default="final")
    parser.add_argument("--title", type=_title_override, action="append", default=[], metavar="LANG=제목",
                        help="translations.json에 쇼츠 제목이 없는 기존 실행에서 언어별 제목을 직접 줍니다. "
                             "upload-overrides.json에 저장되어 upload-text에도 쓰입니다.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        save_shorts_title_overrides(args.run_directory, dict(args.title))
        outputs = build_shorts(args.run_directory, quality=args.quality)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"쇼츠 제작 실패: {error}", file=sys.stderr)
        return 1
    if not outputs:
        print("이미 세로 영상이라 쇼츠를 따로 만들지 않습니다.")
    for path in outputs:
        print(f"쇼츠 완료: {path}")
    return 0
