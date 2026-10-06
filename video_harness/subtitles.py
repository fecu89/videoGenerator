"""Sentence-timed subtitles from the voice reports: no ASR, no clipping, two lines at most."""
from __future__ import annotations
import math
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from .creative_gates import _named_gate
from .language_voices import load_language_voices
from .sequence_models import LocalSequencePlan
from .sequence_plans import load_local_sequence_plan
from .sequence_render import _output_boundary
from .storage import atomic_write

MAX_LINES = 2
MIN_CUE_SECONDS = 0.8
CUE_GAP_SECONDS = 0.05
FONT_HEIGHT_RATIO = 0.044
BOTTOM_MARGIN_RATIO = 0.05
SIDE_MARGIN_RATIO = 0.06
SUBTITLE_DIR = "subtitles"
SPACED_LANGUAGES = {"en", "es", "ko"}
_BREAKS = (", ", "，", "、", "; ", ": ")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    lines: list[str]
    window: tuple[float, float] | None = field(default=None, compare=False)
    overflow: float = field(default=0.0, compare=False)   # seconds of speech beyond the scene slot


def gate_name(lang: str) -> str:
    return f"subtitle-gate-{lang}.json"


def report_path_for(run: Path, lang: str) -> Path:
    return run / ("voice-generation-report.json" if lang == "ko" else f"voice-generation-report-{lang}.json")


def sentence_windows(scene_report: dict, *, leading_ms: int, trailing_ms: int) -> list[tuple[float, float]]:
    """Per-sentence (start, end) inside the scene's MP3, mirroring the encode filter graph."""
    rate = int(scene_report["sample_rate"])
    scene_tempo = float(scene_report.get("tempo_factor", 1.0))
    cursor = 0.0
    windows = []
    for sentence in scene_report["sentences"]:
        tempo = float(sentence.get("tempo_factor", scene_tempo))
        reported = float(sentence.get("output_seconds") or 0.0)
        adjusted = float(sentence.get("adjusted_speech_seconds") or 0.0)
        if reported > 0:
            # Reports written after 2026-09-24 carry the encoded sentence length directly.
            length = reported
        elif adjusted > 0:
            # Older master reports: the encoder keeps the audible speech (already
            # tempo-adjusted) and adds both margins; the raw sample count also holds
            # the model's own silence, so it must not be used here.
            length = adjusted + (leading_ms + trailing_ms) / 1000
        else:
            lead = round(rate * leading_ms / 1000 * tempo)
            trail = round(rate * trailing_ms / 1000 * tempo)
            speech = max(0, int(sentence["sample_count"]) - lead - trail) / rate / tempo
            length = speech + (leading_ms + trailing_ms) / 1000
        windows.append((cursor, cursor + length))
        cursor += length
    return windows


def scene_offsets(local: LocalSequencePlan, *, output_fps: int) -> dict[int, tuple[float, float]]:
    """Absolute (audio start, slot end) seconds of every scene in the concatenated final timeline."""
    canonical_fps = local.defaults.fps
    offsets: dict[int, tuple[float, float]] = {}
    cursor = 0
    for sequence in local.sequences:
        for span in sequence.scene_spans:
            start = cursor + _output_boundary(span.audio_start_frame, output_fps=output_fps, canonical_fps=canonical_fps)
            end = cursor + _output_boundary(span.audio_end_frame, output_fps=output_fps, canonical_fps=canonical_fps)
            offsets[span.scene_id] = (start / output_fps, end / output_fps)
        cursor += _output_boundary(sequence.duration_frames, output_fps=output_fps, canonical_fps=canonical_fps)
    return offsets


def wrap_lines(text: str, lang: str, chars_per_line: int) -> list[str]:
    text = text.strip()
    if lang in SPACED_LANGUAGES:
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= chars_per_line or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines
    return [text[i:i + chars_per_line] for i in range(0, len(text), chars_per_line)] or [text]


def _break_index(text: str, lang: str) -> int | None:
    centre = len(text) / 2
    candidates = []
    for mark in _BREAKS:
        start = 0
        while (i := text.find(mark, start)) != -1:
            candidates.append((abs(i + len(mark) - centre), i + len(mark)))
            start = i + 1
    # A mark far from the middle (e.g. "In the end,") would leave a cue too short
    # to read; use marks only in the middle third, else the space nearest centre.
    balanced = [c for c in candidates if c[0] <= len(text) / 6]
    if balanced:
        return min(balanced)[1]
    if lang in SPACED_LANGUAGES:
        spaces = [(abs(i - centre), i + 1) for i, ch in enumerate(text) if ch == " "]
        if spaces:
            return min(spaces)[1]
    if not candidates:
        return None if lang in SPACED_LANGUAGES or len(text) < 2 else len(text) // 2
    return min(candidates)[1]


def split_for_two_lines(text: str, lang: str, chars_per_line: int) -> list[str]:
    text = text.strip()
    if len(wrap_lines(text, lang, chars_per_line)) <= MAX_LINES:
        return [text]
    index = _break_index(text, lang)
    if index is None or index <= 0 or index >= len(text):
        return [text]
    head, tail = text[:index].rstrip(), text[index:].lstrip()
    if not head or not tail:
        return [text]
    return split_for_two_lines(head, lang, chars_per_line) + split_for_two_lines(tail, lang, chars_per_line)


def build_cues(report: dict, offsets: dict[int, tuple[float, float]], *, lang: str, chars_per_line: int) -> list[Cue]:
    leading_ms = int(report["sentence_leading_margin_ms"])
    trailing_ms = int(report["sentence_trailing_margin_ms"])
    cues: list[Cue] = []
    for scene in sorted(report["scenes"], key=lambda s: s["scene_id"]):
        scene_leading = int(scene.get('sentence_leading_margin_ms', leading_ms))
        scene_trailing = int(scene.get('sentence_trailing_margin_ms', trailing_ms))
        lead = scene_leading / 1000
        base, slot_end = offsets[int(scene["scene_id"])]
        windows = sentence_windows(scene, leading_ms=scene_leading, trailing_ms=scene_trailing)
        starts = [base + w[0] + lead for w in windows]
        for index, (sentence, (w_start, w_end)) in enumerate(zip(scene["sentences"], windows)):
            start = starts[index]
            # The next sentence speaks only after its leading margin, so the gap before
            # it can extend past this sentence's own window; never leave the window.
            limit = min(starts[index + 1] - CUE_GAP_SECONDS, base + w_end, slot_end) if index + 1 < len(starts) else min(base + w_end, slot_end)
            end = limit
            window = (base + w_start, min(base + w_end, slot_end))
            overflow = max(0.0, base + w_end - slot_end)
            pieces = split_for_two_lines(sentence["text"], lang, chars_per_line)
            total = sum(len(p) for p in pieces) or 1
            cursor = start
            for piece in pieces:
                share = (end - start) * len(piece) / total
                piece_end = cursor + share if piece is not pieces[-1] else end
                # Millisecond cue times round inward so a cue stays inside its window.
                cues.append(Cue(math.ceil(cursor * 1000 - 1e-6) / 1000, math.floor(piece_end * 1000 + 1e-6) / 1000,
                                wrap_lines(piece, lang, chars_per_line), window, overflow))
                cursor = piece_end
    return cues


def _ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def render_ass(cues: Sequence[Cue], *, width: int, height: int, font: str) -> str:
    size = round(FONT_HEIGHT_RATIO * height)
    margin_v = round(BOTTOM_MARGIN_RATIO * height)
    margin_side = round(SIDE_MARGIN_RATIO * width)
    outline = max(1, round(size / 24))
    shadow = max(1, round(size / 48))
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Sub,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00201A0F,&H80000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,{margin_side},{margin_side},{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Sub,,0,0,0,,{'\\N'.join(c.lines)}" for c in cues]
    return "\n".join(header + events) + "\n"


def render_srt(cues: Sequence[Cue]) -> str:
    blocks = [f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n" + "\n".join(c.lines) + "\n" for i, c in enumerate(cues, start=1)]
    return "\n".join(blocks)


def subtitle_issues(cues: Sequence[Cue], *, chars_per_line: int, windows: Sequence[tuple[float, float]] | None = None) -> list[str]:
    issues: list[str] = []
    for index, cue in enumerate(cues):
        window = windows[index] if windows is not None and index < len(windows) else cue.window
        where = f"cue {index + 1} [{cue.start:.2f}-{cue.end:.2f}]"
        if window is not None and (cue.start < window[0] - 1e-6 or cue.end > window[1] + 1e-6):
            issues.append(f"cue_outside_window: {where} not inside {window[0]:.2f}-{window[1]:.2f}")
        if index + 1 < len(cues) and cue.end > cues[index + 1].start + 1e-6:
            issues.append(f"cue_overlap: {where} overlaps next cue starting {cues[index + 1].start:.2f}")
        if len(cue.lines) > MAX_LINES:
            issues.append(f"cue_too_many_lines: {where} has {len(cue.lines)} lines")
        for line in cue.lines:
            if len(line) > chars_per_line:
                issues.append(f"cue_line_too_long: {where} {len(line)} > {chars_per_line}: {line!r}")
        if cue.end - cue.start < MIN_CUE_SECONDS - 1e-6:
            issues.append(f"cue_too_short: {where} shorter than {MIN_CUE_SECONDS}s")
        if cue.overflow > CUE_GAP_SECONDS:
            issues.append(f"cue_overflows_slot: {where} speech runs {cue.overflow:.2f}s past its scene slot")
    return issues


def subtitle_cue_spans(run_dir: Path, lang: str, *, output_fps: int) -> list[tuple[float, float]]:
    """(start, end) of every subtitle cue in the final timeline — the ducking schedule for background music."""
    run = Path(run_dir).resolve()
    local = load_local_sequence_plan(run / "local-sequence-plan.json")
    report = json.loads(report_path_for(run, lang).read_text(encoding="utf-8"))
    voice = load_language_voices(run).voices[lang]
    cues = build_cues(report, scene_offsets(local, output_fps=output_fps), lang=lang, chars_per_line=voice.chars_per_line)
    return [(cue.start, cue.end) for cue in cues]


def speech_spans_from_cues(cues: list[Cue], *, trailing_seconds: float) -> list[tuple[float, float]]:
    """Cue spans with each sentence's silent trailing margin removed (a cue window ends after it)."""
    spans = []
    for cue in cues:
        end = cue.end if cue.window is None else min(cue.end, cue.window[1] - trailing_seconds)
        spans.append((cue.start, max(cue.start, round(end, 6))))
    return spans


def speech_spans(run_dir: Path, lang: str, *, output_fps: int) -> list[tuple[float, float]]:
    """When the narrator is actually speaking — the ducking schedule for background music."""
    run = Path(run_dir).resolve()
    local = load_local_sequence_plan(run / "local-sequence-plan.json")
    report = json.loads(report_path_for(run, lang).read_text(encoding="utf-8"))
    voice = load_language_voices(run).voices[lang]
    cues = build_cues(report, scene_offsets(local, output_fps=output_fps), lang=lang, chars_per_line=voice.chars_per_line)
    return speech_spans_from_cues(cues, trailing_seconds=int(report["sentence_trailing_margin_ms"]) / 1000)


def write_subtitles(run_dir: Path, lang: str, *, quality: str, width: int, height: int, output_fps: int, out_root: Path | None = None) -> Path:
    """Build the language's ASS/SRT under out_root (the stage being assembled), never elsewhere."""
    run = Path(run_dir).resolve()
    local = load_local_sequence_plan(run / "local-sequence-plan.json")
    report = json.loads(report_path_for(run, lang).read_text(encoding="utf-8"))
    voice = load_language_voices(run).voices[lang]
    cues = build_cues(report, scene_offsets(local, output_fps=output_fps), lang=lang, chars_per_line=voice.chars_per_line)
    out_dir = Path(out_root or run).resolve() / SUBTITLE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_path = out_dir / f"{lang}.ass"
    atomic_write(ass_path, render_ass(cues, width=width, height=height, font=voice.font))
    atomic_write(out_dir / f"{lang}.srt", render_srt(cues))
    errors = subtitle_issues(cues, chars_per_line=voice.chars_per_line)
    if len(cues) < sum(len(s["sentences"]) for s in report["scenes"]):
        errors.append("cue_count_short: fewer cues than sentences")
    _named_gate(run, gate_name(lang), errors, language=lang, quality=quality, cues=len(cues))
    return ass_path
