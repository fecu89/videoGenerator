"""Schema-v3 voice settings. Historical Qwen generation remains supported."""
from typing import Literal
from pydantic import ConfigDict, Field, model_validator
from .models import StrictModel
VoiceGenerationPreset = Literal["consistent", "custom"]
VoiceEmotionMode = Literal["script_only", "off"]

class ArchivedVoiceSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: Literal["qwen3", "voxcpm2"] = "qwen3"
    voxcpm_source: Literal["modelscope", "huggingface", "local"] = "modelscope"
    voxcpm_model_id: str = Field(default="OpenBMB/VoxCPM2", min_length=1)
    voxcpm_revision: str = Field(default="master", min_length=1)
    voxcpm_device: Literal["auto", "mps", "cpu", "cuda"] = "auto"
    voxcpm_voice: Literal["bright_female", "warm_male", "reference"] = "bright_female"
    voxcpm_reference_audio: str = ""
    voxcpm_consistency_mode: Literal["standard", "locked"] = "standard"
    voxcpm_reference_text: str = ""
    voxcpm_cfg: float = Field(default=2.0, gt=0, le=10)
    voxcpm_steps: int = Field(default=10, ge=1, le=100)
    loudness_mode: Literal["off", "leveled"] = "off"
    loudness_target_lufs: float = Field(default=-18.0, ge=-30, le=-12)
    loudness_range_lu: float = Field(default=5.0, ge=3, le=20)
    loudness_true_peak_db: float = Field(default=-1.5, ge=-6, le=-0.5)

    @model_validator(mode="after")
    def validate_voxcpm_reference(self):
        if self.engine == "voxcpm2" and self.voxcpm_consistency_mode == "locked":
            if self.voxcpm_voice != "reference" or not self.voxcpm_reference_audio.strip():
                raise ValueError("VoxCPM2 locked voice requires a reference voice and audio file")
            if not self.voxcpm_reference_text.strip():
                raise ValueError("VoxCPM2 locked voice requires an exact reference transcript")
        if self.engine == "voxcpm2" and self.voxcpm_voice == "reference" and not self.voxcpm_reference_audio.strip():
            raise ValueError("VoxCPM2 reference voice requires voxcpm_reference_audio")
        return self

    model_id: str = Field(
        default="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        min_length=1,
    )
    model_revision: str = Field(
        default="41d3337e8b7f2843a75841595fc14e4b9a7a4b96",
        pattern=r"^[0-9a-f]{40}$",
    )
    speaker: str = Field(default="Sohee", min_length=1)
    language: str = Field(default="Korean", min_length=1)
    instructions_file: str = Field(
        default="video_harness/agent/prompts/voice-sohee-ko.txt",
        min_length=1,
    )
    generation_preset: VoiceGenerationPreset = "consistent"
    emotion_mode: VoiceEmotionMode = "script_only"
    speaking_rate: float = Field(default=1.08, ge=0.9, le=1.2)
    target_syllables_per_second: float = Field(default=5.2, ge=4.0, le=7.0)
    max_internal_pause_ms: int = Field(default=350, ge=150, le=800)
    sentence_leading_margin_ms: int = Field(default=100, ge=0, le=300)
    sentence_trailing_margin_ms: int = Field(default=950, ge=800, le=1500)
    temperature: float = Field(default=0.5, gt=0)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    top_k: int = Field(default=30, ge=1)
    top_p: float = Field(default=1.0, gt=0, le=1)
    repetition_penalty: float = Field(default=1.05, gt=0)
    seed: int = Field(default=20260828, ge=0, le=4294967295)
    min_scene_seconds: float = Field(default=5.0, gt=0)
    max_scene_seconds: float = Field(default=14.0, gt=0)



# Read-only schema-v4 compatibility; this does not provide an engine.
class ArchivedV4VoiceSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine: Literal["qwen3", "voxcpm2", "kokoro"] = "voxcpm2"
    model_id: str = Field(
        default="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        min_length=1,
    )
    model_revision: str = Field(
        default="41d3337e8b7f2843a75841595fc14e4b9a7a4b96",
        pattern=r"^[0-9a-f]{40}$",
    )
    speaker: str = Field(default="Sohee", min_length=1)
    language: str = Field(default="Korean", min_length=1)
    instructions_file: str = Field(
        default="video_harness/agent/prompts/voice-sohee-ko.txt",
        min_length=1,
    )
    generation_preset: VoiceGenerationPreset = "consistent"
    temperature: float = Field(default=0.5, gt=0)
    top_k: int = Field(default=30, ge=1)
    top_p: float = Field(default=1.0, gt=0, le=1)
    repetition_penalty: float = Field(default=1.05, gt=0)
    voxcpm_source: Literal["modelscope", "huggingface", "local"] = "modelscope"
    voxcpm_model_id: str = Field(default="OpenBMB/VoxCPM2", min_length=1)
    voxcpm_revision: str = Field(default="master", min_length=1)
    voxcpm_device: Literal["auto", "mps", "cpu", "cuda"] = "auto"
    voxcpm_voice: Literal["bright_female", "warm_male", "reference"] = "bright_female"
    voxcpm_reference_audio: str = ""
    voxcpm_consistency_mode: Literal["standard", "locked", "directed"] = "standard"
    acting_style: Literal["natural", "youtube", "youtube_exuberant"] = "natural"
    voxcpm_reference_text: str = ""
    voxcpm_cfg: float = Field(default=2.0, gt=0, le=10)
    voxcpm_steps: int = Field(default=10, ge=1, le=100)
    emotion_mode: VoiceEmotionMode = "off"
    speed_mode: Literal["target", "manual"] = "manual"
    speaking_rate: float = Field(default=1.0, ge=0.8, le=1.25)
    # Upper bound for speeding speech up (atempo). Above ~1.3x articulation starts to smear.
    max_tempo_factor: float = Field(default=1.25, ge=1.0, le=1.6)
    target_syllables_per_second: float = Field(default=5.2, ge=4.0, le=7.0)
    loudness_mode: Literal["off", "leveled"] = "leveled"
    loudness_target_lufs: float = Field(default=-18.0, ge=-30, le=-12)
    loudness_range_lu: float = Field(default=5.0, ge=3, le=20)
    loudness_true_peak_db: float = Field(default=-1.5, ge=-6, le=-0.5)
    max_internal_pause_ms: int = Field(default=350, ge=150, le=800)
    sentence_leading_margin_ms: int = Field(default=100, ge=0, le=300)
    sentence_trailing_margin_ms: int = Field(default=950, ge=200, le=1500)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    seed: int = Field(default=20260828, ge=0, le=4294967295)
    min_scene_seconds: float = Field(default=5.0, gt=0)
    max_scene_seconds: float = Field(default=14.0, gt=0)

    @model_validator(mode="after")
    def validate_reference(self):
        if self.engine != "voxcpm2":
            return self
        if self.voxcpm_consistency_mode == "directed":
            if self.voxcpm_voice != "reference" or not self.voxcpm_reference_audio.strip():
                raise ValueError("VoxCPM2 directed voice requires a reference audio file")
        if self.voxcpm_consistency_mode == "locked":
            if self.acting_style != "natural":
                raise ValueError("acting_style requires standard or directed voice mode")
            if self.voxcpm_voice != "reference" or not self.voxcpm_reference_audio.strip():
                raise ValueError("VoxCPM2 locked voice requires a reference voice and audio file")
            if not self.voxcpm_reference_text.strip():
                raise ValueError("VoxCPM2 locked voice requires an exact reference transcript")
        if self.voxcpm_voice == "reference" and not self.voxcpm_reference_audio.strip():
            raise ValueError("VoxCPM2 reference voice requires voxcpm_reference_audio")
        return self

