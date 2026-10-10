from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import ConfigDict, Field, HttpUrl, TypeAdapter, field_validator, model_validator

from .models import StrictModel
from .storage import atomic_write
from .runtime_defaults import (PREVIEW_LONG_EDGE, PREVIEW_FPS, PREVIEW_INTERVAL_SECONDS, CONTACT_SHEET_COLUMNS)
from .archived_voice_settings import ArchivedVoiceSettings, ArchivedV4VoiceSettings
OutputMode = Literal["all", "video_only", "prompts_only"]
VariantMode = Literal["four", "balanced_only"]
VoiceGenerationPreset = Literal["consistent", "custom"]
VoiceEmotionMode = Literal["script_only", "off"]
TextPolicy = Literal["legacy", "keywords", "subtitles"]
LocalizedDelivery = Literal["burned_videos", "videos", "audio_tracks", "video_and_audio"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SETTINGS_FILE = PROJECT_ROOT / "settings.json"
RUN_SETTINGS_FILENAME = "run-settings.json"
QWEN_SETTING_FIELDS = ('model_id', 'model_revision', 'speaker', 'language', 'instructions_file', 'generation_preset', 'temperature', 'top_k', 'top_p', 'repetition_penalty')


class VoiceSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine: Literal["qwen3", "kokoro"] = "qwen3"
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
    emotion_mode: VoiceEmotionMode = "off"
    speaking_rate: float = Field(default=1.0, ge=0.8, le=1.25)
    # Upper bound for speeding speech up (atempo). Above ~1.3x articulation starts to smear.
    max_tempo_factor: float = Field(default=1.25, ge=1.0, le=1.6)
    target_syllables_per_second: float = Field(default=5.2, ge=4.0, le=7.0)
    loudness_mode: Literal["off", "leveled"] = "leveled"
    loudness_target_lufs: float = Field(default=-18.0, ge=-30, le=-12)
    loudness_range_lu: float = Field(default=5.0, ge=3, le=20)
    loudness_true_peak_db: float = Field(default=-1.5, ge=-6, le=-0.5)
    max_internal_pause_ms: int = Field(default=350, ge=50, le=800)
    # Missing fields retain old run semantics; project settings/presets enable typed pauses.
    pause_mode: Literal['legacy', 'typed'] = 'legacy'
    comma_pause_ms: int = Field(default=120, ge=80, le=150)
    semantic_pause_ms: int = Field(default=200, ge=150, le=250)
    emphasis_pause_ms: int = Field(default=350, ge=300, le=400)
    sentence_pause_ms: int = Field(default=500, ge=400, le=600)
    sentence_leading_margin_ms: int = Field(default=100, ge=0, le=300)
    sentence_trailing_margin_ms: int = Field(default=950, ge=200, le=1500)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    seed: int = Field(default=20260828, ge=0, le=4294967295)
    min_scene_seconds: float = Field(default=5.0, gt=0)
    max_scene_seconds: float = Field(default=14.0, gt=0)


class AppleVoiceSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    voice_identifier: str = "com.apple.voice.compact.ko-KR.Yuna"
    rate: float = Field(default=0.5, ge=0, le=1)
    pitch_multiplier: float = Field(default=1.0, ge=0.5, le=2)
    volume: float = Field(default=1.0, ge=0, le=1)
    min_scene_seconds: float = Field(default=5.5, gt=0)
    max_scene_seconds: float = Field(default=8.0, gt=0)


class LegacyVoiceSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    voice: str
    instructions: str
    min_scene_seconds: float = Field(default=5.5, gt=0)
    max_scene_seconds: float = Field(default=8.0, gt=0)
    workers: int = Field(default=2, ge=1, le=16)
    retry_attempts: int = Field(default=4, ge=1, le=10)
    retry_min_wait_seconds: float = Field(default=1.0, ge=0)
    retry_max_wait_seconds: float = Field(default=8.0, ge=0)


class ArchivedRenderSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    final_width: int = Field(default=1920, gt=0)
    final_height: int = Field(default=1080, gt=0)
    final_fps: int = Field(default=30, gt=0)
    draft_width: int = Field(default=960, gt=0)
    draft_height: int = Field(default=540, gt=0)
    draft_fps: int = Field(default=15, gt=0)
    x264_preset: str = "medium"
    x264_crf: int = Field(default=18, ge=0, le=51)
    preview_interval_seconds: float = Field(default=0.5, gt=0)
    contact_sheet_columns: int = Field(default=8, ge=1, le=32)


class RenderSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    final_width: int = Field(default=1920, gt=0)
    final_height: int = Field(default=1080, gt=0)
    final_fps: int = Field(default=30, gt=0)
    x264_preset: str = "medium"
    x264_crf: int = Field(default=18, ge=0, le=51)
    # Keep existing consumers readable without exposing these as settings fields.
    @property
    def draft_width(self) -> int:
        return max(2, round(PREVIEW_LONG_EDGE * self.final_width / max(self.final_width, self.final_height) / 2) * 2)

    @property
    def draft_height(self) -> int:
        return max(2, round(PREVIEW_LONG_EDGE * self.final_height / max(self.final_width, self.final_height) / 2) * 2)

    draft_fps: ClassVar[int] = PREVIEW_FPS
    preview_interval_seconds: ClassVar[float] = PREVIEW_INTERVAL_SECONDS
    contact_sheet_columns: ClassVar[int] = CONTACT_SHEET_COLUMNS


CAMERA_TRANSITION_DEFAULT = 0.35


class LocalVideoSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_scene_seconds: float = Field(default=5.0, gt=0)
    max_scene_seconds: float = Field(default=15.0, gt=0)
    scene_gap_seconds: float = Field(default=0.65, ge=0)
    # Camera move duration for new scene paths; custom renderers must consume the job value.
    camera_transition_seconds: float = Field(default=CAMERA_TRANSITION_DEFAULT, ge=0, le=3)
    # Zero/zero preserves existing plans without adding pacing advice.
    target_beat_min_seconds: float = Field(default=0, ge=0, le=30)
    target_beat_max_seconds: float = Field(default=0, ge=0, le=30)
    text_policy: TextPolicy = "legacy"
    subtitle_languages: str = ""
    # video_and_audio: Korean MP4 + translated M4A; retain older delivery modes for run compatibility.
    localized_delivery: LocalizedDelivery = "burned_videos"


class MusicSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str = ""                                   # file name inside bgmusic/; empty = no music
    gain_db: float = Field(default=-12.0, ge=-40, le=0)   # music level relative to narration loudness
    duck_db: float = Field(default=-16.0, ge=-40, le=0)   # extra reduction while narration speaks
    fade_seconds: float = Field(default=1.2, ge=0, le=5)  # duck-down / duck-up ramp
    loop_mode: Literal["loop", "once"] = "loop"


class QaSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_undeclared_freeze_seconds: float = Field(default=2.0, gt=0)
    black_frame_amount_percent: float = Field(default=99.9, gt=0, le=100)
    black_frame_threshold: int = Field(default=17, ge=0, le=255)
    audio_packet_tolerance_seconds: float = Field(default=0.05, ge=0)
    duration_tolerance_seconds: float = Field(default=0.05, ge=0)


class PipelineSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    output_mode: OutputMode = "all"
    variant_mode: VariantMode = "four"


class PacingSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    preset: Literal["custom", "calm", "standard", "shorts"] = "custom"
    version: Literal[1, 2] = 1


class ArchivedV5HarnessSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[5] = 5
    pacing: PacingSettings = Field(default_factory=PacingSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    local_video: LocalVideoSettings = Field(default_factory=LocalVideoSettings)
    render: ArchivedRenderSettings = Field(default_factory=ArchivedRenderSettings)
    qa: QaSettings = Field(default_factory=QaSettings)
    music: MusicSettings = Field(default_factory=MusicSettings)

    @model_validator(mode="after")
    def validate_duration_range(self) -> ArchivedV5HarnessSettings:
        low = self.local_video.target_beat_min_seconds
        high = self.local_video.target_beat_max_seconds
        if not (low == high == 0 or 0 < low <= high):
            raise ValueError("target beat range must be zero/zero or 0 < minimum <= maximum")
        if self.voice.min_scene_seconds > self.voice.max_scene_seconds:
            raise ValueError("voice minimum scene seconds must not exceed maximum scene seconds")
        if self.local_video.min_scene_seconds >= self.local_video.max_scene_seconds:
            raise ValueError(
                "local minimum scene seconds must be less than maximum scene seconds"
            )
        if (
            self.voice.max_scene_seconds + self.local_video.scene_gap_seconds
            >= self.local_video.max_scene_seconds
        ):
            raise ValueError(
                "voice maximum scene seconds plus scene gap must be below local maximum scene seconds"
            )
        return self


class PromotionSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = ""
    locale_mode: Literal["shared", "language_path", "ko_only"] = "shared"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        url = TypeAdapter(HttpUrl).validate_python(value)
        if url.username or url.password or url.query is not None or url.fragment is not None:
            raise ValueError("홍보 주소는 로그인 정보·쿼리·앵커 없는 HTTP(S) 주소를 입력하세요.")
        return str(url).rstrip("/")

    def url_for(self, lang: str) -> str:
        if self.locale_mode == "ko_only":
            return self.base_url if lang == "ko" else ""
        if not self.base_url or self.locale_mode == "shared" or lang == "ko":
            return self.base_url
        url = urlsplit(self.base_url)
        return urlunsplit((url.scheme, url.netloc, f"/{lang}{url.path}", "", ""))


class ArchivedV6HarnessSettings(ArchivedV5HarnessSettings):
    schema_version: Literal[6] = 6
    render: RenderSettings = Field(default_factory=RenderSettings)
    promotion: PromotionSettings = Field(default_factory=PromotionSettings)


class BlenderSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    shadow_pool_mb: Literal[16, 32, 64, 128, 256, 512, 1024, 1536, 2048] = 2048


class HarnessSettings(ArchivedV6HarnessSettings):
    schema_version: Literal[7] = 7
    blender: BlenderSettings = Field(default_factory=BlenderSettings)


class ArchivedV4HarnessSettings(ArchivedV5HarnessSettings):
    schema_version: Literal[4] = 4
    voice: ArchivedV4VoiceSettings = Field(default_factory=ArchivedV4VoiceSettings)


class ArchivedHarnessSettings(ArchivedV5HarnessSettings):
    schema_version: Literal[3] = 3
    voice: ArchivedVoiceSettings = Field(default_factory=ArchivedVoiceSettings)


class AppleHarnessSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    voice: AppleVoiceSettings = Field(default_factory=AppleVoiceSettings)
    render: ArchivedRenderSettings = Field(default_factory=ArchivedRenderSettings)
    qa: QaSettings = Field(default_factory=QaSettings)

    @model_validator(mode="after")
    def validate_duration_range(self) -> AppleHarnessSettings:
        if self.voice.min_scene_seconds > self.voice.max_scene_seconds:
            raise ValueError("voice minimum scene seconds must not exceed maximum scene seconds")
        return self


class LegacyHarnessSettings(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1, 2] = 1
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    voice: LegacyVoiceSettings
    render: ArchivedRenderSettings = Field(default_factory=ArchivedRenderSettings)
    qa: QaSettings = Field(default_factory=QaSettings)

    @model_validator(mode="after")
    def validate_voice_ranges(self) -> LegacyHarnessSettings:
        if self.voice.min_scene_seconds > self.voice.max_scene_seconds:
            raise ValueError("voice minimum scene seconds must not exceed maximum scene seconds")
        if self.voice.retry_min_wait_seconds > self.voice.retry_max_wait_seconds:
            raise ValueError("voice retry minimum wait seconds must not exceed maximum wait seconds")
        return self


ResolvedHarnessSettings = HarnessSettings | ArchivedV6HarnessSettings | ArchivedV5HarnessSettings | ArchivedV4HarnessSettings | ArchivedHarnessSettings | AppleHarnessSettings | LegacyHarnessSettings


def load_project_settings(settings_file: Path | None = None) -> HarnessSettings:
    path = settings_file if settings_file is not None else PROJECT_SETTINGS_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"project settings not found: {path}; run "
            "`python -m video_harness settings-ui` to create or repair it"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"invalid settings JSON in {path}: "
            f"line {error.lineno}, column {error.colno}"
        ) from error
    if payload.get("schema_version") == 5:
        # Only project loading migrates; existing run snapshots stay v5.
        archived = ArchivedV5HarnessSettings.model_validate(payload)
        payload = archived.model_dump(mode="json")
        payload["schema_version"] = 6
        for key in ("draft_width", "draft_height", "draft_fps", "preview_interval_seconds", "contact_sheet_columns"):
            payload["render"].pop(key)
    if payload.get("schema_version") == 6:
        payload = ArchivedV6HarnessSettings.model_validate(payload).model_dump(mode="json")
        payload["schema_version"] = 7
    local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    if local_path.is_file():
        local = json.loads(local_path.read_text(encoding="utf-8"))
        if not isinstance(local, dict) or set(local) != {"promotion"}:
            raise ValueError(f"{local_path.name}에는 promotion 설정만 저장할 수 있습니다.")
        payload["promotion"] = local["promotion"]
    return HarnessSettings.model_validate(payload)


def write_project_settings(
    settings: HarnessSettings,
    settings_file: Path | None = None,
) -> Path:
    path = settings_file if settings_file is not None else PROJECT_SETTINGS_FILE
    # Personal promotion is never written into the shared project configuration.
    values = settings.model_dump(mode="json")
    personal = values["promotion"]
    values["promotion"] = PromotionSettings().model_dump(mode="json")
    local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    atomic_write(local_path, json.dumps({"promotion": personal}, ensure_ascii=False, indent=2) + "\n")
    atomic_write(path, json.dumps(values, ensure_ascii=False, indent=2) + "\n")
    return path


def settings_sha256(settings: ResolvedHarnessSettings) -> str:
    values = settings.model_dump(mode="json")
    if values.get("promotion") == PromotionSettings().model_dump(mode="json"):
        values.pop("promotion")
    if values.get('voice', {}).get('pause_mode') == 'legacy':
        from .voice_pauses import PAUSE_FIELDS
        for key in PAUSE_FIELDS:
            values['voice'].pop(key, None)
    if values.get("pacing") == PacingSettings().model_dump(mode="json"):
        values.pop("pacing")
    for key in ("target_beat_min_seconds", "target_beat_max_seconds"):
        if values.get("local_video", {}).get(key) == 0:
            values["local_video"].pop(key)
    # Legacy text policy is the pre-callout default; dropping it keeps completed run hashes.
    if values.get("local_video", {}).get("text_policy") == "legacy":
        values["local_video"].pop("text_policy")
    if values.get("local_video", {}).get("subtitle_languages") == "":
        values["local_video"].pop("subtitle_languages")
    if values.get("local_video", {}).get("localized_delivery") == "burned_videos":
        values["local_video"].pop("localized_delivery")
    # Music off (the default) is hash-excluded so pre-music runs keep their approvals.
    if values.get("music") == MusicSettings().model_dump(mode="json"):
        values.pop("music")
    # Preserve completed Vox run hashes when adding inactive Qwen defaults.
    if settings.schema_version == 4 and values["voice"]["engine"] == "voxcpm2":
        defaults = ArchivedV4VoiceSettings().model_dump(mode="json")
        for key in QWEN_SETTING_FIELDS:
            if values["voice"].get(key) == defaults[key]:
                values["voice"].pop(key)
    # Inactive additive controls preserve approvals for pre-acting schema-v4 runs.
    if settings.schema_version == 4 and values["voice"].get("acting_style") == "natural":
        values["voice"].pop("acting_style")
    # Advisory pacing value added later; the default keeps old hashes.
    if values.get("local_video", {}).get("camera_transition_seconds") == CAMERA_TRANSITION_DEFAULT:
        values["local_video"].pop("camera_transition_seconds")
    # The tempo cap was a fixed 1.25 before it became a setting; the default keeps old hashes.
    if values.get("voice", {}).get("max_tempo_factor") == 1.25:
        values["voice"].pop("max_tempo_factor")
    # Schema-v3 predates engine selection. Default Qwen choices must keep the
    # exact historical hash so completed runs and their approvals stay valid.
    if settings.schema_version == 3:
        defaults = ArchivedVoiceSettings().model_dump(mode="json")
        additions = [key for key in defaults if key == "engine" or key.startswith("voxcpm_")]
        if all(values["voice"][key] == defaults[key] for key in additions):
            for key in additions:
                values["voice"].pop(key)
        # Preserve hashes of existing VoxCPM2 runs, too, when the new controls
        # are unused. Enabled controls and their parameters remain hash-bound.
        consistency_additions = ["voxcpm_consistency_mode", "voxcpm_reference_text"]
        if all(getattr(settings.voice,key) == defaults[key] for key in consistency_additions):
            for key in consistency_additions:
                values["voice"].pop(key,None)
        loudness_additions = [key for key in defaults if key.startswith("loudness_")]
        if all(values["voice"][key] == defaults[key] for key in loudness_additions):
            for key in loudness_additions:
                values["voice"].pop(key)
    payload = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_settings_snapshot(run_dir: Path, settings: ResolvedHarnessSettings) -> Path:
    snapshot_path = run_dir / RUN_SETTINGS_FILENAME
    atomic_write(snapshot_path, settings.model_dump_json(indent=2) + "\n")
    return snapshot_path


def _settings_with_overrides(
    settings: ResolvedHarnessSettings,
    overrides: Mapping[str, object] | None,
) -> ResolvedHarnessSettings:
    if not overrides:
        return settings

    values = settings.model_dump(mode="python")
    for group, group_overrides in overrides.items():
        if group_overrides is None:
            continue
        if not isinstance(group_overrides, Mapping):
            values[group] = group_overrides
            continue
        current_group = values.get(group)
        if not isinstance(current_group, dict):
            values[group] = {
                field: value
                for field, value in group_overrides.items()
                if value is not None
            }
            continue
        current_group.update(
            {
                field: value
                for field, value in group_overrides.items()
                if value is not None
            }
        )
    return type(settings).model_validate(values)


def resolve_run_settings(
    run_dir: Path | None,
    *,
    settings_file: Path | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    refresh: bool = False,
    persist: bool = False,
) -> ResolvedHarnessSettings:
    if refresh and run_dir is None:
        raise ValueError("--refresh-settings requires a run directory")
    if persist and run_dir is None:
        raise ValueError("persisting settings requires a run directory")

    snapshot_path = None if run_dir is None else run_dir / RUN_SETTINGS_FILENAME
    if snapshot_path is not None and snapshot_path.is_file() and not refresh:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        schema_version = payload.get("schema_version")
        if schema_version == 1:
            settings = LegacyHarnessSettings.model_validate(payload)
        elif schema_version == 2:
            settings = AppleHarnessSettings.model_validate(payload)
        elif schema_version == 3:
            settings = ArchivedHarnessSettings.model_validate(payload)
        elif schema_version == 4:
            settings = ArchivedV4HarnessSettings.model_validate(payload)
        elif schema_version == 5:
            settings = ArchivedV5HarnessSettings.model_validate(payload)
        elif schema_version == 6:
            settings = ArchivedV6HarnessSettings.model_validate(payload)
        elif schema_version == 7:
            settings = HarnessSettings.model_validate(payload)
        else:
            raise ValueError(
                f"unsupported run settings schema_version: {schema_version!r}"
            )
    else:
        settings = load_project_settings(settings_file)

    settings = _settings_with_overrides(settings, cli_overrides)
    if persist:
        assert run_dir is not None
        write_settings_snapshot(run_dir, settings)
    return settings


def write_settings_schema(path: Path) -> None:
    schema = HarnessSettings.model_json_schema(mode="validation")
    atomic_write(path, json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


def subtitle_language_list(settings: ResolvedHarnessSettings) -> list[str]:
    """Target subtitle/voice languages; Korean is always the master and never a target."""
    raw = getattr(getattr(settings, "local_video", None), "subtitle_languages", "") or ""
    seen: list[str] = []
    for item in raw.split(","):
        code = item.strip().lower()
        if code and code != "ko" and code not in seen:
            seen.append(code)
    return seen
