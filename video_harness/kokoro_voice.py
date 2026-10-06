"""Kokoro (mlx-audio) engine for translated languages: preset voices, natural pace, scene-fit tempo."""
from __future__ import annotations
import gc
import hashlib
import platform
import sys
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
import numpy as np
from .voice_audio import (AudioSynthesizer, RuntimeBindings, SentenceGeneration, cap_internal_silence,
    longest_internal_silence_ms, spoken_unit_count)


def _kokoro_snapshot(model_id: str, revision: str | None) -> Path:
    """Pinned local snapshot; the network is touched only when the revision is not cached."""
    from huggingface_hub import snapshot_download
    try:
        return Path(snapshot_download(model_id, revision=revision, local_files_only=True))
    except Exception:
        return Path(snapshot_download(model_id, revision=revision))


def voice_names_in(snapshot: Path) -> list[str]:
    """Preset names shipped in the snapshot's voices/ folder."""
    return sorted({path.stem for path in (snapshot / "voices").glob("*") if path.suffix in {".pt", ".safetensors"}})


@dataclass(frozen=True)
class KokoroRuntime(RuntimeBindings):
    snapshot: Callable[[str, str | None], Path] = _kokoro_snapshot


def load_kokoro_runtime() -> KokoroRuntime:
    try:
        import mlx.core as mx
        from mlx_audio.audio_io import write
        from mlx_audio.tts.utils import load_model
    except ImportError as error:
        raise RuntimeError("MLX-Audio를 불러올 수 없습니다. mlx-audio와 misaki를 설치하세요.") from error

    def release_unused_memory():
        gc.collect()
        mx.synchronize()
        mx.clear_cache()

    return KokoroRuntime(
        # A pinned snapshot path ends in the revision hash, which mlx-audio would
        # otherwise read as the model type because Kokoro's config names none.
        load_model=lambda model_id, **_: load_model(model_id, model_type="kokoro"),
        release_unused_memory=release_unused_memory,
        write_audio=lambda path, audio, rate, audio_format: write(path, audio, rate, format=audio_format),
        seed=mx.random.seed,
        to_numpy=np.asarray,
        concatenate=np.concatenate,
        zeros=lambda count, dtype: np.zeros(count, dtype=dtype),
        all_finite=lambda audio: bool(np.isfinite(audio).all()),
    )


class KokoroSynthesizer(AudioSynthesizer):
    def __init__(self, settings, *, voice: str, lang_code: str, model_id: str, revision: str | None = None,
                 runtime_loader=load_kokoro_runtime, platform_name=sys.platform, machine_name=platform.machine(), **kwargs):
        super().__init__(settings, runtime_loader=runtime_loader, **kwargs)
        self.model_id = model_id
        self.revision = revision
        self.platform_name = platform_name
        self.machine_name = machine_name
        self._voices: list[str] | None = None
        self.configure(voice=voice, lang_code=lang_code, scene_target_seconds=self.scene_target_seconds)

    def configure(self, *, voice: str, lang_code: str, scene_target_seconds=None) -> None:
        """Switch language/voice on the already loaded model (one load serves en/ja/es)."""
        self.voice = voice
        self.lang_code = lang_code
        self.scene_target_seconds = scene_target_seconds
        self.provenance = {"engine": "kokoro", "model_id": self.model_id, "revision": self.revision, "voice": voice, "lang_code": lang_code}
        if self._voices is not None and voice not in self._voices:
            raise RuntimeError(f"Kokoro 음성 프리셋 없음: {voice} (사용 가능: {', '.join(self._voices[:12])} …)")

    def _load_model_runtime(self):
        if self.platform_name != "darwin" or self.machine_name != "arm64":
            raise RuntimeError("Kokoro 음성 생성에는 arm64 Apple silicon macOS가 필요합니다.")
        if self._runtime is None:
            self._runtime = self.runtime_loader()
        if self._voices is None:
            snapshot = getattr(self._runtime, "snapshot", None)
            if snapshot is not None:
                self._snapshot_path = Path(snapshot(self.model_id, self.revision))
                self._voices = voice_names_in(self._snapshot_path)
            else:
                self._snapshot_path = None
                self._voices = list(self._runtime.list_voices(self.model_id))
        if self.voice not in self._voices:
            raise RuntimeError(f"Kokoro 음성 프리셋 없음: {self.voice} (사용 가능: {', '.join(self._voices[:12])} …)")
        if self._model is None:
            target = str(self._snapshot_path) if self._snapshot_path is not None else self.model_id
            self._model = self._runtime.load_model(target)
        return self._runtime, self._model

    def effective_instruction(self, delivery):
        # Kokoro has no instruction channel; delivery is carried by the preset voice.
        return ""

    def _generate_sentence(self, *, model, runtime, sentence, instruction, scene_id, sentence_index):
        chunks = []
        sample_rate = None
        for result in model.generate(text=sentence, voice=self.voice, lang_code=self.lang_code, speed=1.0):
            chunks.append(runtime.to_numpy(result.audio))
            sample_rate = int(result.sample_rate)
        if not chunks or sample_rate is None or sample_rate <= 0:
            raise RuntimeError(f"Kokoro returned no audio for scene {scene_id} sentence {sentence_index}")
        audio = runtime.concatenate(chunks)
        if getattr(audio, "ndim", 1) != 1 or len(audio) == 0 or not runtime.all_finite(audio):
            raise RuntimeError(f"Kokoro returned invalid audio for scene {scene_id} sentence {sentence_index}")
        original_pause_ms = longest_internal_silence_ms(audio, sample_rate=sample_rate)
        if original_pause_ms > self.settings.max_internal_pause_ms:
            audio = cap_internal_silence(audio, sample_rate=sample_rate, max_pause_ms=self.settings.max_internal_pause_ms)
        report = SentenceGeneration(
            text=sentence,
            seed=self.settings.seed,
            instruction_sha256=hashlib.sha256(b"").hexdigest(),
            sample_count=len(audio),
            token_count=None,
            processing_time_seconds=None,
            peak_memory_usage=None,
            spoken_units=spoken_unit_count(sentence),
            original_longest_internal_pause_ms=original_pause_ms,
            longest_internal_pause_ms=longest_internal_silence_ms(audio, sample_rate=sample_rate),
            tempo_factor=1.0,
            raw_speech_seconds=len(audio) / sample_rate,
            adjusted_speech_seconds=len(audio) / sample_rate,
        )
        return audio, sample_rate, report
