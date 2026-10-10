"""Qwen/Sohee backend restored from 453fba16^, sharing current audio publication."""
from __future__ import annotations
import gc
import hashlib
import math
import platform
import re
import sys
from pathlib import Path
import numpy as np
from .models import SentenceDelivery
from .settings import PROJECT_ROOT, VoiceSettings, ArchivedV4VoiceSettings
from .voice_audio import (spoken_unit_count,
    AudioSynthesizer, SentenceGeneration,
    RuntimeBindings, SentenceTimingBudget, _audible_bounds,
    cap_internal_silence, longest_internal_silence_ms, split_sentences,
)

CONSISTENT_SAMPLING = (0.5, 30, 1.0, 1.05)
DELIVERY_INSTRUCTIONS = {
    ("curious", "subtle"): "이 문장에만 절제된 호기심을 살짝 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("curious", "moderate"): "이 문장에만 분명한 호기심을 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("bright", "subtle"): "이 문장에만 은은한 밝음을 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("bright", "moderate"): "이 문장에만 밝은 생동감을 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("surprised", "subtle"): "이 문장에만 절제된 놀라움을 살짝 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("surprised", "moderate"): "이 문장에만 분명한 놀라움을 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("confident", "subtle"): "이 문장에만 은은한 확신을 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("confident", "moderate"): "이 문장에만 분명한 확신을 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("gentle", "subtle"): "이 문장에만 약간 부드러운 온기를 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
    ("gentle", "moderate"): "이 문장에만 부드러운 온기를 더하되 기본 화자, 말하기 속도와 피치 중심은 유지한다.",
}
EDGE_SILENCE_ABSOLUTE_THRESHOLD = 1e-4
EDGE_SILENCE_RELATIVE_THRESHOLD = 0.01
EDGE_GUARD_MILLISECONDS = 20
TEMPO_HEADROOM_RATIO = 0.975
MAX_TEMPO_FACTOR = 1.25
ACOUSTIC_TOKENS_PER_SECOND = 12.5
SCRIPT_PUNCTUATION_PAUSE_SECONDS = 0.18
TOKEN_HEADROOM_RATIO = 1.3
# Short pause-delimited phrases can consume attempts on both completion and
# tempo checks. Keep one more candidate without relaxing either quality gate.
MAX_SENTENCE_GENERATION_ATTEMPTS = 4
MAX_SENTENCE_COMPLETION_RETRIES = 3


def sentence_timing_budget(
    text: str,
    settings: VoiceSettings,
) -> SentenceTimingBudget:
    # Same articulation units as voice_audio: CJK ideographs and kana count too.
    spoken_units = spoken_unit_count(text)
    # Standalone letter names in an enumeration need a full articulation,
    # unlike a syllable inside a word. Keep the approved text and the existing
    # final duration/tempo gates; only correct the input speaking-time estimate.
    letter = r"(?:오|비|에이|에프|지|케이|엠)"
    enumerations = re.findall(
        rf"(?<![가-힣]){letter}(?:\s*[,，]\s*{letter}){{2,}}(?![가-힣])", text
    )
    enumeration_separators = 0
    for enumeration in enumerations:
        names = re.split(r"\s*[,，]\s*", enumeration)
        spoken_units += sum(max(0, 3 - len(name)) for name in names)
        enumeration_separators += len(names) - 1
    if spoken_units == 0:
        raise ValueError("sentence must contain spoken text")
    punctuation_pauses = len(re.findall(r"[,，;；:：]+", text))
    target_output_seconds = (
        spoken_units / settings.target_syllables_per_second
        + punctuation_pauses * SCRIPT_PUNCTUATION_PAUSE_SECONDS
    )
    raw_target_seconds = target_output_seconds * settings.speaking_rate
    # Qwen inserts long raw gaps when enumerating names. This allowance only
    # permits completion before cap_internal_silence; it does not increase the
    # target output duration, configured pause cap, or allowed tempo factor.
    raw_target_seconds += enumeration_separators * 0.8
    soft_token_budget = math.ceil(raw_target_seconds * ACOUSTIC_TOKENS_PER_SECOND)
    hard_token_limit = min(
        settings.max_tokens,
        math.ceil(soft_token_budget * TOKEN_HEADROOM_RATIO),
    )
    return SentenceTimingBudget(
        spoken_units=spoken_units,
        punctuation_pauses=punctuation_pauses,
        target_output_seconds=target_output_seconds,
        soft_token_budget=soft_token_budget,
        hard_token_limit=hard_token_limit,
    )

def load_runtime() -> RuntimeBindings:
    try:
        import mlx.core as mx
        import numpy as np
        from mlx_audio.audio_io import write
        from mlx_audio.tts.utils import load_model
    except ImportError as error:
        raise RuntimeError(
            "MLX-Audio를 불러올 수 없습니다. mlx-audio==0.5.0을 설치하세요."
        ) from error
    def release_unused_memory():
        gc.collect()
        mx.synchronize()
        mx.clear_cache()

    return RuntimeBindings(
        load_model=load_model,
        release_unused_memory=release_unused_memory,
        write_audio=lambda path, audio, rate, audio_format: write(
            path, audio, rate, format=audio_format
        ),
        seed=mx.random.seed,
        to_numpy=np.asarray,
        concatenate=np.concatenate,
        zeros=lambda count, dtype: np.zeros(count, dtype=dtype),
        all_finite=lambda audio: bool(np.isfinite(audio).all()),
    )

class MLXAudioSynthesizer(AudioSynthesizer):
    def __init__(self, settings, *, runtime_loader=load_runtime,
                 platform_name=sys.platform, machine_name=platform.machine(), **kwargs):
        super().__init__(settings, runtime_loader=runtime_loader, **kwargs)
        self.platform_name = platform_name
        self.machine_name = machine_name
        configured_path = Path(settings.instructions_file).expanduser()
        self.instructions_path = configured_path if configured_path.is_absolute() else PROJECT_ROOT / configured_path

    def synthesize(self, scenes, destinations):
        # Preserve schema-v3 behavior; current runs use the common acting gate.
        if isinstance(self.settings, (VoiceSettings, ArchivedV4VoiceSettings)) and self.settings.emotion_mode == "script_only":
            for scene in scenes:
                expected = set(range(1, len(split_sentences(scene.narration)) + 1))
                missing = expected - {cue.sentence_index for cue in scene.sentence_delivery}
                if missing:
                    raise ValueError(f"scene {scene.scene_id}: sentence_delivery missing for sentences {sorted(missing)}")
        return super().synthesize(scenes, destinations)

    def _load_model_runtime(self):
        if self.platform_name != "darwin" or self.machine_name != "arm64":
            raise RuntimeError("MLX-Audio 음성 생성에는 arm64 Apple silicon macOS가 필요합니다.")
        if self._runtime is None:
            self._runtime = self.runtime_loader()
        if self._model is None:
            self._model = self._runtime.load_model(self.settings.model_id, revision=self.settings.model_revision)
        for kind, selected, supported in (
            ("화자", self.settings.speaker, self._model.get_supported_speakers()),
            ("언어", self.settings.language, self._model.get_supported_languages()),
        ):
            if selected.casefold() not in {name.casefold() for name in supported}:
                raise RuntimeError(f"모델이 요청한 {kind} {selected}를 지원하지 않습니다.")
        return self._runtime, self._model

    def effective_instruction(self, delivery: SentenceDelivery | None) -> str:
        global_instruction = self.instructions_path.read_text(encoding="utf-8").strip()
        if not global_instruction:
            raise ValueError(f"voice instruction file is empty: {self.instructions_path}")
        if (
            self.settings.emotion_mode == "off"
            or delivery is None
            or delivery.emotion == "neutral"
        ):
            return global_instruction
        return " ".join(
            [
                global_instruction,
                DELIVERY_INSTRUCTIONS[(delivery.emotion, delivery.intensity)],
            ]
        )

    def effective_sampling(self) -> tuple[float, int, float, float]:
        if self.settings.generation_preset == "consistent":
            return CONSISTENT_SAMPLING
        return (
            self.settings.temperature,
            self.settings.top_k,
            self.settings.top_p,
            self.settings.repetition_penalty,
        )

    def _generate_sentence(
        self,
        *,
        model: object,
        runtime: RuntimeBindings,
        sentence: str,
        instruction: str,
        scene_id: int,
        sentence_index: int,
    ) -> tuple[np.ndarray, int, SentenceGeneration]:
        temperature, top_k, top_p, repetition_penalty = self.effective_sampling()
        budget = sentence_timing_budget(sentence, self.settings)
        last_rejection = "unknown candidate rejection"
        hard_token_limit = budget.hard_token_limit
        quality_attempts = 0
        completion_retries = 0
        attempts = 0
        while quality_attempts < MAX_SENTENCE_GENERATION_ATTEMPTS:
            seed = self.settings.seed + attempts
            attempts += 1
            runtime.seed(seed)
            generated = list(
                model.generate_custom_voice(
                    text=sentence,
                    speaker=self.settings.speaker,
                    language=self.settings.language,
                    instruct=instruction,
                    temperature=temperature,
                    max_tokens=hard_token_limit,
                    top_k=top_k,
                    top_p=top_p,
                    repetition_penalty=repetition_penalty,
                    verbose=False,
                    stream=False,
                )
            )
            if len(generated) != 1:
                raise RuntimeError(
                    "non-streaming MLX generation must return exactly one result"
                )
            result = generated[0]
            audio = runtime.to_numpy(result.audio)
            sample_rate = int(result.sample_rate)
            if (
                sample_rate <= 0
                or getattr(audio, "ndim", None) != 1
                or len(audio) == 0
                or not runtime.all_finite(audio)
            ):
                raise RuntimeError(f"MLX returned invalid audio for scene {scene_id}")
            token_count = getattr(result, "token_count", None)
            if token_count is None:
                last_rejection = "missing acoustic token count"
                quality_attempts += 1
                continue
            token_count = int(token_count)
            if token_count >= hard_token_limit:
                last_rejection = (
                    f"reached hard token limit {hard_token_limit}"
                )
                # Allow completion of model-inserted pauses before trimming them.
                # Final silence, tempo and scene-duration gates remain unchanged.
                expanded = min(self.settings.max_tokens, math.ceil(hard_token_limit * 1.5))
                if completion_retries >= MAX_SENTENCE_COMPLETION_RETRIES or expanded == hard_token_limit:
                    break
                completion_retries += 1
                hard_token_limit = expanded
                continue
            quality_attempts += 1
            original_pause_ms = longest_internal_silence_ms(
                audio,
                sample_rate=sample_rate,
            )
            if original_pause_ms > self.settings.max_internal_pause_ms:
                audio = cap_internal_silence(
                    audio,
                    sample_rate=sample_rate,
                    max_pause_ms=self.settings.max_internal_pause_ms,
                )
            pause_ms = longest_internal_silence_ms(
                audio,
                sample_rate=sample_rate,
            )
            start, end = _audible_bounds(audio)
            speech_duration = (end - start) / sample_rate
            tempo_factor = max(
                self.settings.speaking_rate,
                speech_duration / budget.target_output_seconds,
            )
            limit = float(getattr(self.settings, "max_tempo_factor", MAX_TEMPO_FACTOR))
            if tempo_factor > limit and not self.scene_target_seconds:
                last_rejection = (
                    f"requires atempo {tempo_factor:.3f}, above "
                    f"{limit:.2f}"
                )
                continue
            return (
                audio,
                sample_rate,
                SentenceGeneration(
                    text=sentence,
                    instruction=instruction,
                    raw_speech_seconds=speech_duration,
                    adjusted_speech_seconds=speech_duration / tempo_factor,
                    seed=seed,
                    instruction_sha256=hashlib.sha256(
                        instruction.encode("utf-8")
                    ).hexdigest(),
                    sample_count=len(audio),
                    token_count=token_count,
                    processing_time_seconds=getattr(
                        result, "processing_time_seconds", None
                    ),
                    peak_memory_usage=getattr(result, "peak_memory_usage", None),
                    attempt_count=attempts,
                    spoken_units=budget.spoken_units,
                    target_output_seconds=budget.target_output_seconds,
                    soft_token_budget=budget.soft_token_budget,
                    hard_token_limit=hard_token_limit,
                    original_longest_internal_pause_ms=original_pause_ms,
                    longest_internal_pause_ms=pause_ms,
                    tempo_factor=tempo_factor,
                ),
            )
        raise RuntimeError(
            f"scene {scene_id} sentence {sentence_index} failed delivery quality "
            f"budget after {attempts} attempts: "
            f"{last_rejection}"
        )
