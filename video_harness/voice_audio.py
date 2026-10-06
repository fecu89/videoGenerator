from __future__ import annotations
import dataclasses

import math
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from mutagen.mp3 import MP3

from .models import Scene
from .narration import split_narration_sentences
from .settings import VoiceSettings


EDGE_SILENCE_ABSOLUTE_THRESHOLD = 1e-4
EDGE_SILENCE_RELATIVE_THRESHOLD = 0.01
EDGE_GUARD_MILLISECONDS = 20
TEMPO_HEADROOM_RATIO = 0.975
MAX_TEMPO_FACTOR = 1.25
SCRIPT_PUNCTUATION_PAUSE_SECONDS = 0.18
MAX_SENTENCE_GENERATION_ATTEMPTS = 3
FileReplacer = Callable[[Path, Path], None]


def _replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


@dataclass(frozen=True)
class RuntimeBindings:
    load_model: Callable[..., object]
    write_audio: Callable[[Path, object, int, str | None], None]
    seed: Callable[[int], None]
    to_numpy: Callable[[object], object]
    concatenate: Callable[[Sequence[object]], object]
    zeros: Callable[[int, object], object]
    all_finite: Callable[[object], bool]
    release_unused_memory: Callable[[], None] = lambda: None


@dataclass(frozen=True)
class SentenceTimingBudget:
    spoken_units: int
    punctuation_pauses: int
    target_output_seconds: float
    soft_token_budget: int
    hard_token_limit: int


_SPOKEN_UNIT = re.compile(r"[가-힣A-Za-z0-9\u00C0-\u024F\u3040-\u30ff\u4e00-\u9fff\uf900-\ufaff]")


def spoken_unit_count(text: str) -> int:
    """Articulation units: Hangul/Latin/digit characters plus kana and CJK ideographs."""
    return len(_SPOKEN_UNIT.findall(text))


def sentence_timing_budget(
    text: str,
    settings: VoiceSettings,
) -> SentenceTimingBudget:
    spoken_units = spoken_unit_count(text)
    # Standalone letter names in an enumeration need a full articulation,
    # unlike a syllable inside a word. Keep the approved text and the existing
    # final duration/tempo gates; only correct the input speaking-time estimate.
    letter = r"(?:오|비|에이|에프|지|케이|엠)"
    enumerations = re.findall(
        rf"(?<![가-힣]){letter}(?:\s*[,，]\s*{letter}){{2,}}(?![가-힣])", text
    )
    for enumeration in enumerations:
        names = re.split(r"\s*[,，]\s*", enumeration)
        spoken_units += sum(max(0, 3 - len(name)) for name in names)
    # A sentence consisting only of short Korean labels has the same
    # articulation cost (e.g. "순행, 유, 역행, 유, 다시 순행.").
    # Restrict this to complete lists, not ordinary comma-separated clauses;
    # avoid counting the alphabet-name case above a second time.
    labels = re.split(r"\s*[,，]\s*", text.strip().rstrip(".!?。！？"))
    if not enumerations and len(labels) >= 3 and all(
        re.fullmatch(r"[가-힣]{1,3}(?:\s+[가-힣]{1,3})?", label)
        for label in labels
    ):
        spoken_units += sum(
            max(0, 3 - len(label)) for label in labels if " " not in label
        )
    if spoken_units == 0:
        raise ValueError("sentence must contain spoken text")
    punctuation_pauses = len(re.findall(r"[,，;；:：]+", text))
    target_output_seconds = (
        spoken_units / settings.target_syllables_per_second
        + punctuation_pauses * SCRIPT_PUNCTUATION_PAUSE_SECONDS
    )
    return SentenceTimingBudget(spoken_units, punctuation_pauses, target_output_seconds, 0, settings.max_tokens)


class SceneFitError(RuntimeError):
    """A translated scene cannot be sped up enough to fit the Korean master slot."""

    def __init__(self, scene_id: int, ratio: float, *, output_seconds: float | None = None, slot_seconds: float | None = None,
                 limit: float = MAX_TEMPO_FACTOR):
        detail = f" (output {output_seconds:.3f}s > slot {slot_seconds:.3f}s)" if output_seconds is not None and slot_seconds is not None else ""
        super().__init__(f"scene {scene_id} needs ×{ratio:.3f} to fit its slot, above {limit:.2f}{detail}; shorten the translation")
        self.limit = limit
        self.scene_id = scene_id
        self.ratio = ratio
        self.output_seconds = output_seconds
        self.slot_seconds = slot_seconds


def tempo_limit(settings) -> float:
    """The configured speed-up cap; archived run settings predate it and keep 1.25."""
    return float(getattr(settings, "max_tempo_factor", MAX_TEMPO_FACTOR))


def fit_scene_tempo(natural_seconds: float, target_seconds: float, *, scene_id: int = 0,
                    limit: float = MAX_TEMPO_FACTOR) -> float:
    """Uniform per-scene tempo so translated audio ends inside the master's slot.

    Never slows below natural pace: slack is filled with timeline silence instead.
    """
    if natural_seconds <= 0 or target_seconds <= 0:
        raise ValueError("natural and target durations must be positive")
    ratio = natural_seconds / target_seconds
    if ratio > limit + 1e-9:
        raise SceneFitError(scene_id, ratio, limit=limit)
    return max(1.0, ratio)


@dataclass(frozen=True)
class SentenceGeneration:
    text: str
    seed: int
    instruction_sha256: str
    sample_count: int
    token_count: int | None
    processing_time_seconds: float | None
    peak_memory_usage: float | None
    instruction: str = ""
    attempt_count: int = 1
    spoken_units: int = 0
    target_output_seconds: float = 0.0
    soft_token_budget: int = 0
    hard_token_limit: int = 0
    original_longest_internal_pause_ms: float = 0.0
    longest_internal_pause_ms: float = 0.0
    tempo_factor: float = 1.0
    raw_speech_seconds: float = 0.0
    adjusted_speech_seconds: float = 0.0
    target_reached: bool = True
    output_seconds: float = 0.0
    pause_events: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class SceneGeneration:
    narrative_role: str
    sample_rate: int
    sample_count: int
    sentence_leading_margin_ms: int
    sentence_trailing_margin_ms: int
    sentences: tuple[SentenceGeneration, ...]
    tempo_factor: float = 1.0

    @property
    def sentence_gap_milliseconds(self) -> int:
        return self.sentence_leading_margin_ms + self.sentence_trailing_margin_ms


@dataclass(frozen=True)
class AudioResult:
    scene_id: int
    path: Path
    duration_seconds: float
    generation: SceneGeneration
    provenance: dict | None = None


def read_mp3_duration(path: Path) -> float:
    return float(MP3(path).info.length)


split_sentences = split_narration_sentences


def _audible_bounds(audio: np.ndarray) -> tuple[int, int]:
    absolute = np.abs(audio)
    peak = float(absolute.max())
    if peak <= EDGE_SILENCE_ABSOLUTE_THRESHOLD:
        raise ValueError("sentence audio has no audible samples")
    threshold = max(
        EDGE_SILENCE_ABSOLUTE_THRESHOLD,
        peak * EDGE_SILENCE_RELATIVE_THRESHOLD,
    )
    active = np.flatnonzero(absolute >= threshold)
    if len(active) == 0:
        raise ValueError("sentence audio has no audible samples")
    return int(active[0]), int(active[-1]) + 1


def longest_internal_silence_ms(audio: np.ndarray, *, sample_rate: int) -> float:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    first, end = _audible_bounds(audio)
    core = np.abs(audio[first:end])
    peak = float(core.max())
    threshold = max(
        EDGE_SILENCE_ABSOLUTE_THRESHOLD,
        peak * EDGE_SILENCE_RELATIVE_THRESHOLD,
    )
    silent = core < threshold
    padded = np.concatenate(
        [
            np.array([False]),
            silent,
            np.array([False]),
        ]
    )
    transitions = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    if len(starts) == 0:
        return 0.0
    longest_samples = int(np.max(ends - starts))
    return longest_samples / sample_rate * 1000


def cap_internal_silence(
    audio: np.ndarray,
    *,
    sample_rate: int,
    max_pause_ms: int,
) -> np.ndarray:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if max_pause_ms < 0:
        raise ValueError("max_pause_ms must not be negative")
    first, end = _audible_bounds(audio)
    core = audio[first:end]
    absolute = np.abs(core)
    peak = float(absolute.max())
    threshold = max(
        EDGE_SILENCE_ABSOLUTE_THRESHOLD,
        peak * EDGE_SILENCE_RELATIVE_THRESHOLD,
    )
    silent = absolute < threshold
    padded = np.concatenate(
        [np.array([False]), silent, np.array([False])]
    )
    transitions = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    maximum_samples = round(sample_rate * max_pause_ms / 1000)
    parts: list[np.ndarray] = [audio[:first]]
    cursor = 0
    for start, silence_end in zip(starts, ends, strict=True):
        silence_length = int(silence_end - start)
        if silence_length <= maximum_samples:
            continue
        keep_before = maximum_samples // 2
        keep_after = maximum_samples - keep_before
        parts.append(core[cursor : int(start) + keep_before])
        cursor = int(silence_end) - keep_after
    parts.append(core[cursor:])
    parts.append(audio[end:])
    return np.concatenate(parts)


def normalize_sentence_edges(
    audio: np.ndarray,
    *,
    sample_rate: int,
    leading_ms: int,
    trailing_ms: int,
    tempo_factor: float,
) -> np.ndarray:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if leading_ms < 0 or trailing_ms < 0:
        raise ValueError("sentence margins must not be negative")
    if tempo_factor <= 0:
        raise ValueError("tempo_factor must be positive")

    first, end = _audible_bounds(audio)
    leading_target = round(sample_rate * leading_ms / 1000 * tempo_factor)
    trailing_target = round(sample_rate * trailing_ms / 1000 * tempo_factor)
    guard_target = round(sample_rate * EDGE_GUARD_MILLISECONDS / 1000)
    leading_guard = min(first, leading_target, guard_target)
    trailing_available = len(audio) - end
    trailing_guard = min(trailing_available, trailing_target, guard_target)
    core = audio[first - leading_guard : end + trailing_guard]
    return np.concatenate(
        [
            np.zeros(leading_target - leading_guard, dtype=audio.dtype),
            core,
            np.zeros(trailing_target - trailing_guard, dtype=audio.dtype),
        ]
    )


class AudioSynthesizer:
    def __init__(
        self,
        settings: VoiceSettings,
        *,
        runtime_loader: Callable[[], object],
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        command_locator: Callable[[str], str | None] = shutil.which,
        duration_reader: Callable[[Path], float] = read_mp3_duration,
        file_replacer: FileReplacer = _replace_file,
        scene_target_seconds: Mapping[int, float] | None = None,
    ):
        self.settings = settings
        # Translated languages fit each scene into the Korean master's slot.
        self.scene_target_seconds = scene_target_seconds
        self.runtime_loader = runtime_loader
        self.runner = runner
        self.command_locator = command_locator
        self.duration_reader = duration_reader
        self.file_replacer = file_replacer
        self._model: object | None = None
        self._runtime: RuntimeBindings | None = None

    def _release_runtime_memory(self, runtime: RuntimeBindings | None) -> None:
        if runtime is not None:
            try:
                runtime.release_unused_memory()
            except Exception:
                logging.getLogger(__name__).warning("모델 메모리 정리 실패", exc_info=True)

    def close(self) -> None:
        """Drop owned model references before releasing device allocations."""
        self._model = None
        runtime, self._runtime = self._runtime, None
        self._release_runtime_memory(runtime)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _run(self, command: Sequence[str]) -> None:
        try:
            completed = self.runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=60.0,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"명령 실행 시간이 초과됐습니다: {command[0]}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                f"명령을 실행할 수 없습니다: {command[0]}: {error}"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise RuntimeError(f"명령 실행 실패 ({command[0]}): {detail}")

    @staticmethod
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

    def _publish_atomically(
        self,
        staged: Mapping[int, Path],
        destinations: Mapping[int, Path],
        temp_root: Path,
    ) -> None:
        backup_root = temp_root / "backup"
        backup_root.mkdir()
        local_staged: dict[int, Path] = {}
        backups: dict[int, Path] = {}
        published: list[int] = []
        try:
            for scene_id in sorted(staged):
                destination = destinations[scene_id]
                if destination.exists():
                    if not destination.is_file() or destination.is_symlink():
                        raise RuntimeError(
                            f"최종 MP3 경로가 일반 파일이 아닙니다: {destination}"
                        )
                    backup = backup_root / f"{scene_id:04d}.mp3"
                    shutil.copy2(destination, backup)
                    backups[scene_id] = backup
                local_staged[scene_id] = self._stage_next_to_destination(
                    staged[scene_id], destination
                )

            try:
                for scene_id in sorted(staged):
                    published.append(scene_id)
                    self.file_replacer(
                        local_staged[scene_id],
                        destinations[scene_id],
                    )
            except BaseException as publication_error:
                rollback_errors: list[BaseException] = []
                for scene_id in reversed(published):
                    destination = destinations[scene_id]
                    try:
                        backup = backups.get(scene_id)
                        if backup is None:
                            destination.unlink(missing_ok=True)
                            continue
                        restoration = self._stage_next_to_destination(
                            backup,
                            destination,
                        )
                        try:
                            self.file_replacer(restoration, destination)
                        finally:
                            restoration.unlink(missing_ok=True)
                    except BaseException as rollback_error:
                        rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise RuntimeError(
                        "MP3 publication failed and rollback was incomplete"
                    ) from publication_error
                raise
        finally:
            for path in local_staged.values():
                path.unlink(missing_ok=True)

    def synthesize(
        self,
        scenes: Sequence[Scene],
        destinations: Mapping[int, Path],
    ) -> list[AudioResult]:
        ordered = sorted(scenes, key=lambda scene: scene.scene_id)
        if not ordered:
            return []
        expected_ids = [scene.scene_id for scene in ordered]
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError("scene IDs must be unique")
        if set(destinations) != set(expected_ids):
            raise ValueError("destinations must exactly match the requested scene IDs")
        ffmpeg = self.command_locator("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg가 없습니다. Homebrew 등으로 FFmpeg를 설치하세요.")

        if getattr(self.settings, 'pause_mode', 'legacy') != 'typed' and any(scene.sentence_pauses for scene in ordered):
            raise ValueError('sentence_pauses requires voice.pause_mode=typed')
        runtime, model = self._load_model_runtime()

        with tempfile.TemporaryDirectory(prefix="video-generator-voice-") as name:
            temp_root = Path(name)
            wav_dir = temp_root / "wav"
            mp3_dir = temp_root / "mp3"
            wav_dir.mkdir()
            mp3_dir.mkdir()
            staged: dict[int, tuple[Path, float, SceneGeneration]] = {}
            for scene in ordered:
                sentences = split_sentences(scene.narration)
                typed_pauses = getattr(self.settings, 'pause_mode', 'legacy') == 'typed'
                from .voice_pauses import sentence_phrases, aggregate_sentence_reports
                requests = []
                for owner, text in enumerate(sentences):
                    if typed_pauses:
                        cues = [cue for cue in scene.sentence_pauses if cue.sentence_index == owner + 1]
                        requests.extend((owner, p.text, 0, p.pause_ms, p.kind)
                                        for p in sentence_phrases(text, cues, self.settings))
                    else:
                        requests.append((owner, text, self.settings.sentence_leading_margin_ms,
                                         self.settings.sentence_trailing_margin_ms, 'sentence'))
                sentence_ids = [r[0] for r in requests]
                leading_margins = [r[2] for r in requests]
                trailing_margins = [r[3] for r in requests]
                kinds = [r[4] for r in requests]
                fixed_margins_seconds = (sum(leading_margins) + sum(trailing_margins)) / 1000
                delivery_by_sentence = {
                    cue.sentence_index: cue for cue in scene.sentence_delivery
                }
                chunks: list[object] = []
                sentence_reports: list[SentenceGeneration] = []
                sample_rate: int | None = None
                for sentence_index, sentence, _leading, _trailing, _kind in requests:
                    instruction = self.effective_instruction(
                        delivery_by_sentence.get(sentence_index + 1)
                    )
                    try:
                        audio, rate, sentence_report = self._generate_sentence(
                            model=model,
                            runtime=runtime,
                            sentence=sentence,
                            instruction=instruction,
                            scene_id=scene.scene_id,
                            sentence_index=sentence_index + 1,
                        )
                    finally:
                        self._release_runtime_memory(runtime)
                    if sample_rate is None:
                        sample_rate = rate
                    elif rate != sample_rate:
                        raise RuntimeError("sentence sample rates do not match")
                    chunks.append(audio)
                    sentence_reports.append(sentence_report)
                assert sample_rate is not None
                target = (self.scene_target_seconds or {}).get(scene.scene_id)
                if target is not None:
                    # Margins are fixed milliseconds (adelay/apad) and never sped up, so only the
                    # audible speech can absorb the tempo. Fit speech into what the slot leaves.
                    speech = sum((end - start) / sample_rate for start, end in (_audible_bounds(chunk) for chunk in chunks))
                    available = target - fixed_margins_seconds
                    if available <= 0 or speech <= 0:
                        raise SceneFitError(scene.scene_id, float("inf"))
                    scene_tempo = fit_scene_tempo(speech, available, scene_id=scene.scene_id,
                                                  limit=tempo_limit(self.settings))
                    sentence_reports = [
                        dataclasses.replace(report, tempo_factor=scene_tempo) for report in sentence_reports
                    ]
                def encode(reports):
                    chunks_out = [
                        normalize_sentence_edges(
                            chunk,
                            sample_rate=sample_rate,
                            leading_ms=leading,
                            trailing_ms=trailing,
                            tempo_factor=report.tempo_factor,
                        )
                        for chunk, report, leading, trailing in zip(chunks, reports, leading_margins, trailing_margins, strict=True)
                    ]
                    total = sum(len(chunk) / sample_rate / report.tempo_factor for chunk, report in zip(chunks_out, reports, strict=True))
                    return chunks_out, total

                normalized_chunks, predicted_duration = encode(sentence_reports)
                if target is not None:
                    # The first tempo fits audible speech only; edge guards kept around it
                    # can still overflow the slot. Re-solve against the encoded length a
                    # few times, failing only when the needed tempo exceeds the limit.
                    fixed = fixed_margins_seconds
                    for _ in range(3):
                        if predicted_duration <= target + 1e-6:
                            break
                        tempo = sentence_reports[0].tempo_factor
                        needed = tempo * (predicted_duration - fixed) / max(1e-9, target - fixed)
                        if needed > tempo_limit(self.settings) + 1e-9:
                            raise SceneFitError(scene.scene_id, needed, output_seconds=predicted_duration, slot_seconds=target,
                                                limit=tempo_limit(self.settings))
                        sentence_reports = [dataclasses.replace(report, tempo_factor=needed) for report in sentence_reports]
                        normalized_chunks, predicted_duration = encode(sentence_reports)
                    if predicted_duration > target + 1e-6:
                        raise SceneFitError(scene.scene_id, sentence_reports[0].tempo_factor,
                                            output_seconds=predicted_duration, slot_seconds=target,
                                            limit=tempo_limit(self.settings))
                sentence_reports = [
                    dataclasses.replace(report, output_seconds=len(chunk) / sample_rate / report.tempo_factor)
                    for chunk, report in zip(normalized_chunks, sentence_reports, strict=True)
                ]
                if predicted_duration > (
                    self.settings.max_scene_seconds * TEMPO_HEADROOM_RATIO
                ):
                    raise RuntimeError(
                        f"scene {scene.scene_id} content-aware duration "
                        f"{predicted_duration:.3f}s exceeds scene headroom"
                    )
                audio = runtime.concatenate(normalized_chunks)
                wav_path = wav_dir / f"{scene.scene_id:04d}.wav"
                runtime.write_audio(wav_path, audio, sample_rate, "WAV")
                staged_mp3 = mp3_dir / destinations[scene.scene_id].name
                boundaries: list[tuple[int, int]] = []
                cursor = 0
                for chunk in normalized_chunks:
                    boundaries.append((cursor, cursor + len(chunk)))
                    cursor += len(chunk)
                filter_parts: list[str] = []
                if len(boundaries) == 1:
                    sources = ["0:a"]
                else:
                    split_outputs = "".join(
                        f"[s{index}]" for index in range(len(boundaries))
                    )
                    filter_parts.append(
                        f"[0:a]asplit={len(boundaries)}{split_outputs}"
                    )
                    sources = [f"s{index}" for index in range(len(boundaries))]
                for index, ((start, end), report, source) in enumerate(
                    zip(boundaries, sentence_reports, sources, strict=True)
                ):
                    leading_milliseconds = leading_margins[index]
                    trailing_seconds = trailing_margins[index] / 1000
                    leveling = ''
                    if self.settings.loudness_mode == 'leveled':
                        # Compress unusually loud syllables, then match perceived
                        # loudness per utterance. Add silence only afterwards so
                        # margins do not drive gain or change sentence placement.
                        leveling = (
                            'acompressor=threshold=0.0630957:ratio=2.5:attack=15:release=180:makeup=1,'
                            f'loudnorm=I={self.settings.loudness_target_lufs}:'
                            f'LRA={self.settings.loudness_range_lu}:'
                            f'TP={self.settings.loudness_true_peak_db},'
                            f'aresample={sample_rate},'
                        )
                    leading_samples = round(
                        sample_rate
                        * leading_margins[index]
                        / 1000
                        * report.tempo_factor
                    )
                    trailing_samples = round(
                        sample_rate
                        * trailing_margins[index]
                        / 1000
                        * report.tempo_factor
                    )
                    filter_parts.append(
                        f"[{source}]atrim=start_sample={start + leading_samples}:"
                        f"end_sample={end - trailing_samples},"
                        "asetpts=PTS-STARTPTS,"
                        f"atempo={report.tempo_factor:.9f},"
                        f"{leveling}"
                        f"adelay={leading_milliseconds}:all=1,"
                        f"apad=pad_dur={trailing_seconds:.3f}[a{index}]"
                    )
                if len(boundaries) == 1:
                    final_source = "a0"
                else:
                    concatenated = "".join(
                        f"[a{index}]" for index in range(len(boundaries))
                    )
                    filter_parts.append(
                        f"{concatenated}concat=n={len(boundaries)}:v=0:a=1[joined]"
                    )
                    final_source = "joined"
                filter_graph = ";".join(filter_parts)
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-filter_complex",
                    filter_graph,
                    "-map",
                    f"[{final_source}]",
                ]
                command.extend(
                    [
                        "-map_metadata",
                        "-1",
                        "-codec:a",
                        "libmp3lame",
                        "-q:a",
                        "2",
                        str(staged_mp3),
                    ]
                )
                self._run(command)
                if not staged_mp3.is_file() or staged_mp3.stat().st_size == 0:
                    raise RuntimeError(
                        f"FFmpeg가 MP3를 만들지 못했습니다: scene {scene.scene_id}"
                    )
                duration = float(self.duration_reader(staged_mp3))
                if not math.isfinite(duration) or duration <= 0:
                    raise RuntimeError(f"변환된 MP3 길이가 0입니다: scene {scene.scene_id}")
                if typed_pauses:
                    sentence_reports = aggregate_sentence_reports(sentences, sentence_reports,
                        sentence_ids, kinds, trailing_margins)
                staged[scene.scene_id] = (
                    staged_mp3,
                    duration,
                    SceneGeneration(
                        narrative_role=scene.narrative_role,
                        sample_rate=sample_rate,
                        sample_count=len(audio),
                        sentence_leading_margin_ms=(
                            0 if typed_pauses else self.settings.sentence_leading_margin_ms
                        ),
                        sentence_trailing_margin_ms=(
                            self.settings.sentence_pause_ms if typed_pauses else self.settings.sentence_trailing_margin_ms
                        ),
                        sentences=tuple(sentence_reports),
                        tempo_factor=max(
                            report.tempo_factor for report in sentence_reports
                        ),
                    ),
                )

            self._publish_atomically(
                {scene_id: values[0] for scene_id, values in staged.items()},
                destinations,
                temp_root,
            )
            return [
                AudioResult(
                    scene.scene_id,
                    destinations[scene.scene_id],
                    staged[scene.scene_id][1],
                    staged[scene.scene_id][2],
                    getattr(self, "provenance", None),
                )
                for scene in ordered
            ]
