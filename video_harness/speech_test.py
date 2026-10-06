"""Speak a short sample with unsaved settings, for the settings screen's test button.

The loaded model is kept between presses: pacing values change on every press,
but reloading a TTS model takes 10-30 s. A synthesizer is reused only while the
values that shape the model and voice (engine, model, speaker) stay
the same; otherwise the old one is closed before a new one is created.
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from .models import Scene
from .settings import VoiceSettings

DEFAULT_SAMPLE = "앞차가 아주 조금 느려집니다. 뒤차는 한 박자 늦게, 더 세게 브레이크를 밟습니다."
MAX_SAMPLE_CHARS = 200
# Fields that do not change which model or voice is loaded; a new press may change them freely.
REUSABLE_FIELDS = {
    "target_syllables_per_second", "max_tempo_factor", "speaking_rate", "max_internal_pause_ms",
    "sentence_leading_margin_ms", "sentence_trailing_margin_ms", "min_scene_seconds",
    "max_scene_seconds", "loudness_mode", "loudness_target_lufs", "loudness_range_lu",
    "loudness_true_peak_db", "seed", "max_tokens",
}


def _identity(voice: VoiceSettings) -> dict[str, Any]:
    values = voice.model_dump(mode="json")
    return {key: value for key, value in values.items() if key not in REUSABLE_FIELDS}


class SpeechTester:
    def __init__(self, factory: Callable[[VoiceSettings], Any] | None = None):
        if factory is None:
            from .voice import create_synthesizer
            factory = create_synthesizer
        self.factory = factory
        self.lock = threading.Lock()
        self._synth: Any = None
        self._identity: dict[str, Any] | None = None

    def speak(self, voice: VoiceSettings, text: str) -> tuple[bytes, float]:
        """Return (mp3 bytes, seconds). Scene length limits are lifted for a sample."""
        sample = " ".join(text.split())[:MAX_SAMPLE_CHARS] or DEFAULT_SAMPLE
        voice = voice.model_copy(update={"min_scene_seconds": 0.1, "max_scene_seconds": 120.0})
        with self.lock:
            if self._synth is not None and self._identity != _identity(voice):
                self.close_locked()
            if self._synth is None:
                self._synth = self.factory(voice)
                self._identity = _identity(voice)
            self._synth.settings = voice
            scene = Scene(scene_id=1, title="말하기 속도 테스트", narration=sample,
                          narrative_role="TEST", visual_subject="없음")
            with tempfile.TemporaryDirectory(prefix="speech-test-") as folder:
                destination = Path(folder) / "sample.mp3"
                results = self._synth.synthesize([scene], {1: destination})
                return destination.read_bytes(), float(results[0].duration_seconds)

    def close_locked(self) -> None:
        synth, self._synth, self._identity = self._synth, None, None
        close = getattr(synth, "close", None)
        if close is not None:
            close()

    def close(self) -> None:
        with self.lock:
            self.close_locked()
