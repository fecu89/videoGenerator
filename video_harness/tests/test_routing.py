from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_harness.routing import (
    ShotRequirements,
    choose_generation_mode,
    choose_render_mode,
    explain_route,
)


@pytest.mark.parametrize(
    ("requirements", "expected"),
    [
        ({"exact_cross_frame_relationships": ["path_membership"]}, "simulation"),
        (
            {"deterministic_overlays": ["attached_line"], "organic_base": True},
            "composite",
        ),
        ({"fixed_source_image": True, "keyframed_camera": True}, "still_motion"),
        ({"organic_base": True, "historical_action": True}, "generated"),
    ],
)
def test_choose_render_mode(requirements, expected):
    assert choose_render_mode(ShotRequirements(**requirements)) == expected


def test_first_last_wins_when_both_boundary_frames_exist():
    requirements = ShotRequirements(
        start_image="shotAssets/starts/01A.png",
        end_image="shotAssets/ends/01A.png",
    )
    assert choose_generation_mode(requirements) == "first_last"


def test_i2v_wins_for_one_start_reference():
    requirements = ShotRequirements(start_image="shotAssets/starts/01A.png")
    assert choose_generation_mode(requirements) == "i2v"


def test_identity_reference_uses_i2v():
    requirements = ShotRequirements(identity_references=["earth-v1"])
    assert choose_generation_mode(requirements) == "i2v"


def test_plain_generated_shot_uses_t2v():
    assert choose_generation_mode(ShotRequirements(organic_base=True)) == "t2v"


def test_route_decision_records_a_stable_reason():
    decision = explain_route(
        ShotRequirements(deterministic_overlays=["projection_intersection"])
    )
    assert decision.render_mode == "composite"
    assert decision.reason_code == "exact_overlay_required"
    assert "오버레이" in decision.explanation


def test_generated_owner_cannot_be_allowed_for_calculated_relationship():
    with pytest.raises(ValidationError, match="generated owner"):
        ShotRequirements(
            exact_cross_frame_relationships=["path_membership"],
            allow_generated_owner=True,
        )


def test_still_motion_requires_both_fixed_image_and_keyframes():
    assert choose_render_mode(ShotRequirements(fixed_source_image=True)) == "generated"
    assert choose_render_mode(ShotRequirements(keyframed_camera=True)) == "generated"
