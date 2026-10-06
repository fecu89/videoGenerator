from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from .models import StrictModel


RenderMode = Literal["generated", "simulation", "composite", "still_motion"]
GenerationMode = Literal["t2v", "i2v", "first_last"]
CoordinateSpaceType = Literal["world_3d", "image_normalized", "semantic"]
PrimaryRoute = Literal["local", "online_required"]
RelationshipOwner = Literal[
    "simulation",
    "deterministic_overlay",
    "reference_frame",
    "generated_model",
]
RelationshipType = Literal[
    "attached_line",
    "fixed_distance",
    "path_membership",
    "projection_intersection",
    "occlusion_alignment",
    "screen_anchor",
    "relative_placement",
]
EXACT_RELATIONSHIPS = frozenset(
    {
        "attached_line",
        "fixed_distance",
        "path_membership",
        "projection_intersection",
        "occlusion_alignment",
        "screen_anchor",
    }
)
NEGATIVE_COMMAND = re.compile(r"^(?:no\s|do not\s|don't\s|never\s)", re.IGNORECASE)


class ProductionModel(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _validate_noun_phrases(values: list[str]) -> list[str]:
    for value in values:
        if not value.strip() or NEGATIVE_COMMAND.match(value.strip()):
            raise ValueError("excluded_elements must be descriptive noun phrases")
    return values


class CoordinateSpace(ProductionModel):
    type: CoordinateSpaceType
    frame_id: str = Field(min_length=1)
    origin: str | None = None
    positive_x: str | None = None
    positive_y: str | None = None
    positive_z: str | None = None
    screen_convention: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_world_axes(self) -> "CoordinateSpace":
        if self.type == "world_3d" and not all(
            (self.origin, self.positive_x, self.positive_y, self.positive_z)
        ):
            raise ValueError("world_3d coordinate spaces require an origin and all axes")
        return self


class EntitySpec(ProductionModel):
    entity_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    identity_ref: str | None = None
    path_id: str | None = None


class PathSpec(ProductionModel):
    path_id: str = Field(min_length=1)
    type: Literal["circle", "line", "polyline", "custom"]
    center: str | None = None
    radius: float | None = Field(default=None, gt=0)
    plane: str | None = None
    points: list[tuple[float, float, float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_circle_geometry(self) -> "PathSpec":
        if self.type == "circle" and not all((self.center, self.radius, self.plane)):
            raise ValueError("circle paths require center, radius, and plane")
        if self.type in {"line", "polyline"} and len(self.points) < 2:
            raise ValueError("line and polyline paths require at least two points")
        return self


class EntityState(ProductionModel):
    center: tuple[float, float] | tuple[float, float, float] | None = None
    scale: float | None = Field(default=None, gt=0)
    rotation_degrees: float | None = None
    visible: bool = True


class TimedState(ProductionModel):
    at_seconds: float = Field(ge=0)
    simulation_time: float | None = None
    entities: dict[str, EntityState] = Field(default_factory=dict)


class MotionTrack(ProductionModel):
    entity_id: str = Field(min_length=1)
    path_id: str | None = None
    direction: Literal[
        "clockwise", "counterclockwise", "left", "right", "static", "custom"
    ]
    rate_profile: Literal["uniform", "linear", "keyframed", "physics"]
    rate_source: str | None = None
    start: EntityState | None = None
    end: EntityState | None = None


class MotionContract(ProductionModel):
    primary_event: str = Field(min_length=1)
    tracks: list[MotionTrack] = Field(default_factory=list)


class RelationshipSpec(ProductionModel):
    relationship_id: str = Field(min_length=1)
    type: RelationshipType
    owner: RelationshipOwner
    entity_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_relationship_has_deterministic_owner(self) -> "RelationshipSpec":
        if self.type in EXACT_RELATIONSHIPS and self.owner == "generated_model":
            raise ValueError("exact relationship cannot be owned by generated_model")
        return self


class CameraContract(ProductionModel):
    projection: Literal["perspective", "orthographic"]
    framing: str = Field(min_length=1)
    movement: str = Field(min_length=1)
    position: tuple[float, float, float] | None = None
    target: tuple[float, float, float] | None = None
    orientation_convention: str | None = None
    screen_direction_convention: str | None = None
    start: EntityState | None = None
    end: EntityState | None = None


class AssetRefs(ProductionModel):
    start_image: str | None = None
    end_image: str | None = None
    reference_images: list[str] = Field(default_factory=list)
    background: str | None = None
    mask: str | None = None


class ShotDependency(ProductionModel):
    shot_id: str = Field(pattern=r"^\d{2,}[A-Z]$")
    artifact: Literal["final_frame", "mask", "tracked_anchors"]


class GenerationContract(ProductionModel):
    mode: GenerationMode
    prompt_file: str = Field(min_length=1)
    inbox_file: str = Field(min_length=1)


class SimulationContract(ProductionModel):
    model: str = Field(min_length=1)
    template: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    renderer_options: dict[str, Any] = Field(default_factory=dict)


class MotionKeyframe(ProductionModel):
    at_seconds: float = Field(ge=0)
    center: tuple[float, float] = (0.5, 0.5)
    scale: float = Field(default=1.0, gt=0)
    rotation_degrees: float = 0.0
    opacity: float = Field(default=1.0, ge=0, le=1)


class StillLayer(ProductionModel):
    layer_id: str = Field(min_length=1)
    source_image: str = Field(min_length=1)
    mask: str | None = None
    z_index: int = 0
    keyframes: list[MotionKeyframe] = Field(min_length=2)


class StillMotionContract(ProductionModel):
    source_image: str = Field(min_length=1)
    camera_keyframes: list[MotionKeyframe] = Field(default_factory=list)
    layers: list[StillLayer] = Field(default_factory=list)


class OverlayKeyframe(ProductionModel):
    at_seconds: float = Field(ge=0)
    points: list[tuple[float, float]] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def normalized_points(cls, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if any(not 0 <= coordinate <= 1 for point in points for coordinate in point):
            raise ValueError("overlay points must use normalized coordinates")
        return points


class OverlayContract(ProductionModel):
    overlay_id: str = Field(min_length=1)
    type: Literal["line", "circle", "polyline", "screen_anchor"]
    relationship_id: str = Field(min_length=1)
    style: dict[str, Any] = Field(default_factory=dict)
    keyframes: list[OverlayKeyframe] = Field(min_length=1)


class CompositeBase(ProductionModel):
    mode: Literal["generated", "still_motion"]
    generation: GenerationContract | None = None
    still_motion: StillMotionContract | None = None

    @model_validator(mode="after")
    def require_matching_contract(self) -> "CompositeBase":
        if self.mode == "generated" and (self.generation is None or self.still_motion is not None):
            raise ValueError("generated composite base requires only generation")
        if self.mode == "still_motion" and (
            self.still_motion is None or self.generation is not None
        ):
            raise ValueError("still_motion composite base requires only still_motion")
        return self


class ProductionShotBase(ProductionModel):
    shot_id: str = Field(pattern=r"^\d{2,}[A-Z]$")
    title: str = Field(min_length=1, max_length=60)
    duration_seconds: float = Field(gt=0)
    render_mode: RenderMode
    purpose: str = Field(min_length=1)
    single_event: str = Field(min_length=1)
    coordinate_space: CoordinateSpace
    entities: list[EntitySpec] = Field(default_factory=list)
    paths: list[PathSpec] = Field(default_factory=list)
    start_state: TimedState
    end_state: TimedState
    invariants: list[str] = Field(min_length=1)
    motion_contract: MotionContract
    camera: CameraContract
    assets: AssetRefs = Field(default_factory=AssetRefs)
    relationships: list[RelationshipSpec] = Field(default_factory=list)
    dependencies: list[ShotDependency] = Field(default_factory=list)
    excluded_elements: list[str] = Field(default_factory=list)

    @field_validator("excluded_elements")
    @classmethod
    def descriptive_exclusions(cls, values: list[str]) -> list[str]:
        return _validate_noun_phrases(values)

    @model_validator(mode="after")
    def validate_time_range_and_unique_ids(self) -> "ProductionShotBase":
        if abs(self.start_state.at_seconds) > 1e-9:
            raise ValueError("start_state.at_seconds must be zero")
        if abs(self.end_state.at_seconds - self.duration_seconds) > 1e-6:
            raise ValueError("end_state.at_seconds must equal shot duration")
        for values, label in (
            ([item.entity_id for item in self.entities], "entity"),
            ([item.path_id for item in self.paths], "path"),
            ([item.relationship_id for item in self.relationships], "relationship"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} identifiers")
        return self


class GeneratedShot(ProductionShotBase):
    render_mode: Literal["generated"]
    generation: GenerationContract

    @model_validator(mode="after")
    def validate_generation_budget(self) -> "GeneratedShot":
        generated_relationships = [
            item for item in self.relationships if item.owner == "generated_model"
        ]
        if len(generated_relationships) > 1:
            raise ValueError("generated shots allow at most one independent relationship")
        if self.generation.mode == "i2v" and not self.assets.start_image:
            raise ValueError("i2v requires assets.start_image")
        if self.generation.mode == "first_last" and not (
            self.assets.start_image and self.assets.end_image
        ):
            raise ValueError("first_last requires start_image and end_image")
        return self


class SimulationShot(ProductionShotBase):
    render_mode: Literal["simulation"]
    simulation: SimulationContract

    @model_validator(mode="after")
    def require_numeric_coordinate_space(self) -> "SimulationShot":
        if self.coordinate_space.type not in {"world_3d", "image_normalized"}:
            raise ValueError("simulation requires world_3d or image_normalized coordinates")
        return self


class CompositeShot(ProductionShotBase):
    render_mode: Literal["composite"]
    base: CompositeBase
    overlays: list[OverlayContract] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_overlays(self) -> "CompositeShot":
        relationships = {item.relationship_id: item for item in self.relationships}
        for overlay in self.overlays:
            relationship = relationships.get(overlay.relationship_id)
            if relationship is None:
                raise ValueError(f"overlay relationship is not declared: {overlay.relationship_id}")
            if relationship.owner != "deterministic_overlay":
                raise ValueError("composite overlay relationship must use deterministic_overlay")
        if self.coordinate_space.type != "image_normalized":
            raise ValueError("composite schema version 1 requires image_normalized coordinates")
        if self.base.mode == "generated":
            generation = self.base.generation
            if generation is not None and generation.mode == "i2v" and not self.assets.start_image:
                raise ValueError("i2v composite base requires assets.start_image")
            if generation is not None and generation.mode == "first_last" and not (
                self.assets.start_image and self.assets.end_image
            ):
                raise ValueError("first_last composite base requires start_image and end_image")
        return self


class StillMotionShot(ProductionShotBase):
    render_mode: Literal["still_motion"]
    still_motion: StillMotionContract

    @model_validator(mode="after")
    def validate_keyframe_ranges(self) -> "StillMotionShot":
        sequences = []
        if self.still_motion.camera_keyframes:
            sequences.append(self.still_motion.camera_keyframes)
        sequences.extend(layer.keyframes for layer in self.still_motion.layers)
        if not sequences:
            raise ValueError("still_motion requires camera or layer keyframes")
        for keyframes in sequences:
            times = [item.at_seconds for item in keyframes]
            if times != sorted(times) or len(times) != len(set(times)):
                raise ValueError("still_motion keyframes must be unique and ordered")
            if abs(times[0]) > 1e-9 or abs(times[-1] - self.duration_seconds) > 1e-6:
                raise ValueError("still_motion keyframes must span the full shot duration")
        return self


ProductionShot = Annotated[
    GeneratedShot | SimulationShot | CompositeShot | StillMotionShot,
    Field(discriminator="render_mode"),
]


class ProductionScene(ProductionModel):
    scene_id: int = Field(ge=1)
    duration_seconds: float = Field(gt=0)
    shots: list[ProductionShot] = Field(default_factory=list)


class SceneTransitionSettings(ProductionModel):
    mode: Literal["cut", "dip_to_black"] = "dip_to_black"
    duration_seconds: float = Field(default=0.65, ge=0)
    fade_seconds: float = Field(default=0.15, ge=0)

    @model_validator(mode="after")
    def validate_fade_window(self) -> "SceneTransitionSettings":
        if self.mode == "dip_to_black" and (
            self.duration_seconds <= 0
            or self.fade_seconds <= 0
            or self.fade_seconds * 2 > self.duration_seconds
        ):
            raise ValueError(
                "dip_to_black fade_seconds must be positive and fit twice "
                "inside duration_seconds"
            )
        return self


class ProductionDefaults(ProductionModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    preview_interval_seconds: float = Field(gt=0)
    scene_transition: SceneTransitionSettings = Field(
        default_factory=SceneTransitionSettings
    )


class StyleEntity(ProductionModel):
    entity_id: str = Field(min_length=1)
    appearance_constraints: list[str] = Field(min_length=1)
    reference_assets: list[str] = Field(default_factory=list)


class StyleBible(ProductionModel):
    visual_mode: str = Field(min_length=1)
    entities: list[StyleEntity] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list)
    lighting: str = Field(min_length=1)
    excluded_elements: list[str] = Field(default_factory=list)

    @field_validator("excluded_elements")
    @classmethod
    def descriptive_exclusions(cls, values: list[str]) -> list[str]:
        return _validate_noun_phrases(values)


class VisualBeat(ProductionModel):
    beat_id: str = Field(pattern=r"^B\d{2,}$")
    scene_id: int = Field(ge=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    primary_event: str = Field(min_length=1)
    relationship_owner: RelationshipOwner

    @model_validator(mode="after")
    def require_positive_half_open_range(self) -> "VisualBeat":
        if self.end_frame <= self.start_frame:
            raise ValueError("visual beat end_frame must exceed start_frame")
        return self


class VisualSequence(ProductionModel):
    sequence_id: str = Field(pattern=r"^SEQ\d{2,}$")
    scene_ids: list[int] = Field(min_length=1)
    primary_route: PrimaryRoute
    purpose: str = Field(min_length=1)
    visual_beat_ids: list[str] = Field(min_length=1)


class ProductionPlan(ProductionModel):
    schema_version: Literal[1, 2]
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    defaults: ProductionDefaults
    style_bible: StyleBible
    scenes: list[ProductionScene] = Field(min_length=1)
    visual_sequences: list[VisualSequence] = Field(default_factory=list)
    visual_beats: list[VisualBeat] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_ordered_scenes_and_style_entities(self) -> "ProductionPlan":
        scene_ids = [scene.scene_id for scene in self.scenes]
        if scene_ids != sorted(scene_ids) or len(scene_ids) != len(set(scene_ids)):
            raise ValueError("production scene IDs must be unique and ordered")
        entity_ids = [entity.entity_id for entity in self.style_bible.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("style entity IDs must be unique")
        return self

    @model_validator(mode="after")
    def validate_version_contract(self) -> "ProductionPlan":
        if self.schema_version == 1:
            if self.visual_sequences or self.visual_beats:
                raise ValueError("schema version 1 cannot contain visual sequences")
            if any(not scene.shots for scene in self.scenes):
                raise ValueError("schema version 1 requires shots in every scene")
            return self
        if not self.visual_sequences or not self.visual_beats:
            raise ValueError("schema version 2 requires visual sequences and beats")
        return self
