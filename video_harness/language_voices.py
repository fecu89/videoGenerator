"""Per-language voice engines and subtitle typography, kept outside the scalar settings catalog."""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from .models import StrictModel
from .settings import PROJECT_ROOT

PROJECT_LANGUAGE_VOICES = PROJECT_ROOT / "video_harness" / "agent" / "language-voices.json"
RUN_LANGUAGE_VOICES = "language-voices.json"
MASTER_LANGUAGE = "ko"


class LanguageVoice(StrictModel):
    engine: Literal["kokoro", "qwen3"] | None = None
    model_id: str | None = None
    revision: str | None = None
    voice: str | None = None
    lang_code: str | None = None
    speaker: str | None = None
    language: str | None = None
    font: str = Field(min_length=1)
    chars_per_line: int = Field(ge=8, le=80)
    units_per_second: float = Field(gt=0)

    @model_validator(mode="after")
    def require_engine_fields(self) -> "LanguageVoice":
        if self.engine == "kokoro" and not (self.model_id and self.voice and self.lang_code):
            raise ValueError("kokoro voice requires model_id, voice and lang_code")
        if self.engine == "qwen3" and not (self.model_id and self.speaker and self.language):
            raise ValueError("qwen3 voice requires model_id, speaker and language")
        return self


class LanguageVoices(StrictModel):
    schema_version: Literal[1] = 1
    voices: dict[str, LanguageVoice]


def load_language_voices(run_dir: Path) -> LanguageVoices:
    """Read the run's copy, seeding it from the project defaults on first use."""
    path = Path(run_dir) / RUN_LANGUAGE_VOICES
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_LANGUAGE_VOICES, path)
    return LanguageVoices.model_validate_json(path.read_text(encoding="utf-8"))
