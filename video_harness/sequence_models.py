from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel


PatchTarget = Literal[
    "simulation_clock",
    "geometry",
    "layers",
    "entities",
    "camera",
    "hide_events",
]
OnlineMode = Literal["t2v", "i2v", "first_last", "v2v"]
ScienceAuthority = Literal["local_reference", "reference_frame", "advisory_only"]
MAX_ONLINE_SHOT_SECONDS = 8.0


class SceneSpan(StrictModel):
    scene_id: int = Field(ge=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    audio_start_frame: int = Field(ge=0)
    audio_end_frame: int = Field(gt=0)
    tail_silence_frames: int = Field(ge=0)

    @model_validator(mode="after")
    def require_positive_half_open_ranges(self) -> "SceneSpan":
        if self.end_frame <= self.start_frame:
            raise ValueError("scene span end_frame must exceed start_frame")
        if self.audio_end_frame <= self.audio_start_frame:
            raise ValueError("audio span end_frame must exceed start_frame")
        return self


class SequenceTimelineBeat(StrictModel):
    beat_id: str = Field(pattern=r"^B\d{2,}$")
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    simulation_time_start: float
    simulation_time_end: float
    controller: str = Field(min_length=1)
    patch_targets: list[PatchTarget] = Field(min_length=1)
    priority: int = Field(default=0, ge=0)
    controller_options: dict[str, object] = Field(default_factory=dict)
    hold_intent: str | None = None

    @model_validator(mode="after")
    def require_positive_half_open_range(self) -> "SequenceTimelineBeat":
        if self.end_frame <= self.start_frame:
            raise ValueError("timeline beat end_frame must exceed start_frame")
        return self


class LocalSequence(StrictModel):
    sequence_id: str = Field(pattern=r"^SEQ\d{2,}$")
    renderer: Literal["threejs", "blender"] | None = None
    scene_ids: list[int] = Field(min_length=1)
    duration_frames: int = Field(gt=0)
    render_mode: Literal["simulation"]
    scene_graph: str = Field(min_length=1)
    scene_spans: list[SceneSpan] = Field(min_length=1)
    timeline: list[SequenceTimelineBeat] = Field(min_length=1)

    @model_validator(mode="after")
    def require_ordered_non_overlapping_scene_spans(self) -> "LocalSequence":
        previous_end = -1
        for span in self.scene_spans:
            if span.start_frame < previous_end:
                raise ValueError("scene_spans must be ordered and non-overlapping")
            previous_end = span.end_frame
        return self


class SequenceDefaults(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    min_scene_seconds: float | None = Field(default=None, gt=0)
    max_scene_seconds: float | None = Field(default=None, gt=0)
    scene_gap_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_complete_local_timing_contract(self) -> "SequenceDefaults":
        values = (
            self.min_scene_seconds,
            self.max_scene_seconds,
            self.scene_gap_seconds,
        )
        if all(value is None for value in values):
            return self
        if any(value is None for value in values):
            raise ValueError(
                "local timing defaults must declare minimum, maximum, and scene gap together"
            )
        assert self.min_scene_seconds is not None
        assert self.max_scene_seconds is not None
        if self.min_scene_seconds >= self.max_scene_seconds:
            raise ValueError("local minimum scene seconds must be below maximum")
        return self


class LocalSequencePlan(StrictModel):
    schema_version: Literal[1]
    renderer: Literal["threejs", "blender"] = "threejs"
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    defaults: SequenceDefaults
    simulation_config_file: str = "simulation.json"
    sequences: list[LocalSequence]


class OnlineShot(StrictModel):
    online_shot_id: str = Field(pattern=r"^ON-[A-Z0-9-]+$")
    beat_ids: list[str] = Field(min_length=1)
    scene_ids: list[int] = Field(min_length=1)
    source_sequence_id: str = Field(pattern=r"^SEQ\d{2,}$")
    source_start_frame: int = Field(ge=0)
    source_end_frame: int = Field(gt=0)
    duration_seconds: float = Field(gt=0, le=MAX_ONLINE_SHOT_SECONDS)
    short_shot_reason: str | None = None
    preferred_mode: OnlineMode
    science_authority: ScienceAuthority
    primary_event: str = Field(min_length=1)
    invariants: list[str] = Field(min_length=1)
    allowed_changes: list[str] = Field(default_factory=list)
    excluded_elements: list[str] = Field(default_factory=list)
    reference_image_files: list[str] = Field(default_factory=list)
    reference_video_file: str | None = None
    prompt_file: str = Field(min_length=1)
    metadata_file: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_positive_half_open_source_range(self) -> "OnlineShot":
        if self.source_end_frame <= self.source_start_frame:
            raise ValueError("online source_end_frame must exceed source_start_frame")
        return self


class OnlinePlan(StrictModel):
    schema_version: Literal[1]
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shots: list[OnlineShot] = Field(min_length=1)
