from __future__ import annotations

from pydantic import Field, model_validator

from .models import StrictModel
from .production_models import GenerationMode, RenderMode


class ShotRequirements(StrictModel):
    exact_cross_frame_relationships: list[str] = Field(default_factory=list)
    deterministic_overlays: list[str] = Field(default_factory=list)
    fixed_source_image: bool = False
    keyframed_camera: bool = False
    organic_base: bool = False
    historical_action: bool = False
    start_image: str | None = None
    end_image: str | None = None
    identity_references: list[str] = Field(default_factory=list)
    allow_generated_owner: bool = False

    @model_validator(mode="after")
    def reject_generated_owner_for_calculated_relationships(self) -> "ShotRequirements":
        if self.exact_cross_frame_relationships and self.allow_generated_owner:
            raise ValueError(
                "generated owner cannot own calculated cross-frame relationships"
            )
        return self


class RouteDecision(StrictModel):
    render_mode: RenderMode
    generation_mode: GenerationMode | None = None
    reason_code: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


def choose_render_mode(requirements: ShotRequirements) -> RenderMode:
    if requirements.exact_cross_frame_relationships:
        return "simulation"
    if requirements.deterministic_overlays:
        return "composite"
    if requirements.fixed_source_image and requirements.keyframed_camera:
        return "still_motion"
    return "generated"


def choose_generation_mode(requirements: ShotRequirements) -> GenerationMode:
    if requirements.start_image and requirements.end_image:
        return "first_last"
    if requirements.start_image or requirements.identity_references:
        return "i2v"
    return "t2v"


def explain_route(requirements: ShotRequirements) -> RouteDecision:
    render_mode = choose_render_mode(requirements)
    if render_mode == "simulation":
        return RouteDecision(
            render_mode=render_mode,
            reason_code="calculated_relationship_required",
            explanation="프레임마다 계산해야 하는 관계가 있어 결정론적 시뮬레이션을 사용합니다.",
        )
    if render_mode == "composite":
        return RouteDecision(
            render_mode=render_mode,
            generation_mode=(
                choose_generation_mode(requirements)
                if requirements.organic_base
                else None
            ),
            reason_code="exact_overlay_required",
            explanation="기본 화면과 분리된 정확한 오버레이가 필요해 합성 모드를 사용합니다.",
        )
    if render_mode == "still_motion":
        return RouteDecision(
            render_mode=render_mode,
            reason_code="fixed_image_keyframes_sufficient",
            explanation="고정 이미지와 명시된 키프레임만으로 장면을 정확히 만들 수 있습니다.",
        )
    return RouteDecision(
        render_mode=render_mode,
        generation_mode=choose_generation_mode(requirements),
        reason_code="single_generatable_event",
        explanation="정확한 다중 객체 계산 없이 하나의 시각 사건만 생성하면 됩니다.",
    )
