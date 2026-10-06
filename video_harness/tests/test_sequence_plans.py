from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.production import script_sha256
from video_harness.production_models import ProductionPlan
from video_harness.sequence_models import (
    LocalSequencePlan,
    OnlinePlan,
    OnlineShot,
    SceneSpan,
    SequenceTimelineBeat,
)
from video_harness.sequence_plans import (
    load_local_sequence_plan,
    load_online_plan,
    validate_sequence_plans,
)


def _script() -> ScriptArtifact:
    return ScriptArtifact(
        selected_topic=SelectedTopic(title="연속 시퀀스", reason="계약 테스트"),
        story_engine=StoryEngine(
            common_belief="장면은 독립적이다",
            contradiction="시각 상태는 이어진다",
            obvious_answer="장면마다 초기화한다",
            constraint="관계가 끊기면 안 된다",
            actual_answer="공유 시퀀스를 렌더한다",
            mechanism="프레임 계약을 사용한다",
            payoff="경계가 자연스럽다",
        ),
        scenes=[
            Scene(
                scene_id=1,
                title="궤도",
                narration="첫 장면은 궤도 관계를 보여줍니다.",
                narrative_role="MECHANISM",
                visual_subject="궤도",
                duration_seconds=4.0,
                audio_file="audioFiles/01_궤도.mp3",
            ),
            Scene(
                scene_id=2,
                title="시선",
                narration="둘째 장면은 시선 변화를 이어갑니다.",
                narrative_role="PAYOFF",
                visual_subject="시선",
                duration_seconds=4.0,
                audio_file="audioFiles/02_시선.mp3",
            ),
        ],
    )


def _production(script_hash: str) -> ProductionPlan:
    return ProductionPlan.model_validate(
        {
            "schema_version": 2,
            "script_sha256": script_hash,
            "defaults": {
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "preview_interval_seconds": 0.5,
            },
            "style_bible": {
                "visual_mode": "scientific visualization",
                "entities": [],
                "palette": ["navy", "white"],
                "lighting": "stable",
                "excluded_elements": ["logos"],
            },
            "scenes": [
                {"scene_id": 1, "duration_seconds": 4.0, "shots": []},
                {"scene_id": 2, "duration_seconds": 4.0, "shots": []},
            ],
            "visual_sequences": [
                {
                    "sequence_id": "SEQ01",
                    "scene_ids": [1, 2],
                    "primary_route": "local",
                    "purpose": "두 장면의 연속 관계를 보인다",
                    "visual_beat_ids": ["B01", "B02"],
                }
            ],
            "visual_beats": [
                {
                    "beat_id": "B01",
                    "scene_id": 1,
                    "start_frame": 0,
                    "end_frame": 120,
                    "primary_event": "궤도 관계를 만든다",
                    "relationship_owner": "simulation",
                },
                {
                    "beat_id": "B02",
                    "scene_id": 2,
                    "start_frame": 120,
                    "end_frame": 240,
                    "primary_event": "시선 관계를 이어간다",
                    "relationship_owner": "simulation",
                },
            ],
        }
    )


def _local(script_hash: str, production_hash: str) -> LocalSequencePlan:
    return LocalSequencePlan.model_validate(
        {
            "schema_version": 1,
            "script_sha256": script_hash,
            "production_plan_sha256": production_hash,
            "defaults": {"width": 1920, "height": 1080, "fps": 30},
            "simulation_config_file": "simulation.json",
            "sequences": [
                {
                    "sequence_id": "SEQ01",
                    "scene_ids": [1, 2],
                    "duration_frames": 240,
                    "render_mode": "simulation",
                    "scene_graph": "continuous-orbit",
                    "scene_spans": [
                        {
                            "scene_id": 1,
                            "start_frame": 0,
                            "end_frame": 120,
                            "audio_start_frame": 0,
                            "audio_end_frame": 120,
                            "tail_silence_frames": 0,
                        },
                        {
                            "scene_id": 2,
                            "start_frame": 120,
                            "end_frame": 240,
                            "audio_start_frame": 120,
                            "audio_end_frame": 240,
                            "tail_silence_frames": 0,
                        },
                    ],
                    "timeline": [
                        {
                            "beat_id": "B01",
                            "start_frame": 0,
                            "end_frame": 120,
                            "simulation_time_start": 0.0,
                            "simulation_time_end": 4.0,
                            "controller": "grow-orbit",
                            "patch_targets": ["geometry", "camera"],
                            "priority": 0,
                        },
                        {
                            "beat_id": "B02",
                            "start_frame": 120,
                            "end_frame": 240,
                            "simulation_time_start": 4.0,
                            "simulation_time_end": 8.0,
                            "controller": "move-sightline",
                            "patch_targets": ["geometry", "camera"],
                            "priority": 0,
                        },
                    ],
                }
            ],
        }
    )


def _online(script_hash: str, production_hash: str) -> OnlinePlan:
    return OnlinePlan.model_validate(
        {
            "schema_version": 1,
            "script_sha256": script_hash,
            "production_plan_sha256": production_hash,
            "shots": [
                {
                    "online_shot_id": "ON-B01",
                    "beat_ids": ["B01"],
                    "scene_ids": [1],
                    "source_sequence_id": "SEQ01",
                    "source_start_frame": 0,
                    "source_end_frame": 120,
                    "duration_seconds": 4.0,
                    "preferred_mode": "v2v",
                    "science_authority": "local_reference",
                    "primary_event": "궤도 관계를 만든다",
                    "invariants": ["궤도 관계가 정확하다"],
                    "reference_video_file": "videoFiles/onlineReferences/ON-B01.mp4",
                    "prompt_file": "videoFiles/prompts/online/SEQ01/ON-B01.txt",
                    "metadata_file": "videoFiles/prompts/online/SEQ01/ON-B01.json",
                },
                {
                    "online_shot_id": "ON-B02",
                    "beat_ids": ["B02"],
                    "scene_ids": [2],
                    "source_sequence_id": "SEQ01",
                    "source_start_frame": 120,
                    "source_end_frame": 240,
                    "duration_seconds": 4.0,
                    "preferred_mode": "v2v",
                    "science_authority": "local_reference",
                    "primary_event": "시선 관계를 이어간다",
                    "invariants": ["시선 관계가 정확하다"],
                    "reference_video_file": "videoFiles/onlineReferences/ON-B02.mp4",
                    "prompt_file": "videoFiles/prompts/online/SEQ01/ON-B02.txt",
                    "metadata_file": "videoFiles/prompts/online/SEQ01/ON-B02.json",
                },
            ],
        }
    )


@pytest.fixture
def sequence_fixture(tmp_path: Path):
    script = _script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production = _production(script_sha256(script_path))
    production_path = tmp_path / "production-plan.json"
    production_path.write_text(
        production.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    local = _local(script_sha256(script_path), script_sha256(production_path))
    online = _online(script_sha256(script_path), script_sha256(production_path))
    paths = SimpleNamespace(script=script_path, production=production_path)
    return script, production, local, online, paths


def _codes(sequence_fixture) -> set[str]:
    script, production, local, online, paths = sequence_fixture
    return {
        issue.code
        for issue in validate_sequence_plans(
            production,
            local,
            online,
            script,
            script_path=paths.script,
            production_path=paths.production,
        )
    }


def test_valid_sequence_plans_cover_local_and_online_contracts(sequence_fixture):
    assert _codes(sequence_fixture) == set()


def test_loaders_parse_local_and_online_plan_files(sequence_fixture, tmp_path: Path):
    _, _, local, online, _ = sequence_fixture
    local_path = tmp_path / "local-sequence-plan.json"
    online_path = tmp_path / "online-plan.json"
    local_path.write_text(local.model_dump_json(indent=2), encoding="utf-8")
    online_path.write_text(online.model_dump_json(indent=2), encoding="utf-8")

    assert load_local_sequence_plan(local_path) == local
    assert load_online_plan(online_path) == online


@pytest.mark.parametrize("loader", [load_local_sequence_plan, load_online_plan])
def test_loaders_leave_parse_failures_as_exceptions(loader, tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValidationError):
        loader(path)


def test_stale_production_hash_is_rejected(sequence_fixture):
    _, _, local, online, _ = sequence_fixture
    local.production_plan_sha256 = "f" * 64
    online.production_plan_sha256 = "e" * 64

    assert "stale_production_plan" in _codes(sequence_fixture)


def test_duplicate_local_scene_is_rejected(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    local.sequences[0].scene_ids.append(1)

    assert "duplicate_local_scene" in _codes(sequence_fixture)


def test_local_timeline_rejects_frame_gap(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    local.sequences[0].timeline[1].start_frame += 1

    assert "local_timeline_gap" in _codes(sequence_fixture)


def test_local_timeline_uses_interval_union_for_overlaps(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    local.sequences[0].timeline[0].end_frame = 130
    local.sequences[0].timeline[1].start_frame = 110
    local.sequences[0].timeline[1].priority = 1

    assert "local_timeline_gap" not in _codes(sequence_fixture)


def _configure_eclipse_explanation(
    sequence_fixture,
    *,
    controller: str,
    close_view_mode: str,
) -> None:
    _, production, local, _, _ = sequence_fixture
    production.visual_beats[1].scene_id = 1
    wide, close = local.sequences[0].timeline
    wide.controller = controller
    wide.controller_options = {"view_mode": "wide_alignment"}
    close.controller = controller
    close.controller_options = {"view_mode": close_view_mode}


def _append_eclipse_beat(
    sequence_fixture,
    *,
    beat_id: str,
    scene_id: int,
    start_frame: int,
    end_frame: int,
    view_mode: str,
) -> None:
    _, production, local, _, _ = sequence_fixture
    common = production.visual_beats[0].model_copy(deep=True)
    common.beat_id = beat_id
    common.scene_id = scene_id
    common.start_frame = start_frame
    common.end_frame = end_frame
    production.visual_beats.append(common)
    production.visual_sequences[0].visual_beat_ids.append(beat_id)

    timeline = local.sequences[0].timeline[0].model_copy(deep=True)
    timeline.beat_id = beat_id
    timeline.start_frame = start_frame
    timeline.end_frame = end_frame
    timeline.simulation_time_start = start_frame / local.defaults.fps
    timeline.simulation_time_end = end_frame / local.defaults.fps
    timeline.controller_options = {"view_mode": view_mode}
    local.sequences[0].timeline.append(timeline)


@pytest.mark.parametrize(
    ("controller", "close_view_mode"),
    [
        ("solar-eclipse-alignment", "earth_close_shadow_track"),
        ("lunar-eclipse-alignment", "moon_close_shadow_entry"),
    ],
)
def test_eclipse_explanation_accepts_contiguous_wide_then_close_views(
    sequence_fixture,
    controller: str,
    close_view_mode: str,
):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller=controller,
        close_view_mode=close_view_mode,
    )

    codes = _codes(sequence_fixture)

    assert not any(code.startswith("eclipse_explanation_") for code in codes)


def test_eclipse_explanation_requires_wide_alignment(sequence_fixture):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="solar-eclipse-alignment",
        close_view_mode="earth_close_shadow_track",
    )
    local = sequence_fixture[2]
    local.sequences[0].timeline[0].controller_options["view_mode"] = (
        "observer_annular_close"
    )

    assert "eclipse_explanation_missing_wide" in _codes(sequence_fixture)


def test_eclipse_explanation_requires_mechanism_closeup(sequence_fixture):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="lunar-eclipse-alignment",
        close_view_mode="blood_moon_close_to_night_side",
    )

    assert "eclipse_explanation_missing_close" in _codes(sequence_fixture)


def test_eclipse_explanation_views_must_share_a_scene(sequence_fixture):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="solar-eclipse-alignment",
        close_view_mode="earth_close_shadow_track",
    )
    production = sequence_fixture[1]
    production.visual_beats[1].scene_id = 2

    assert "eclipse_explanation_scene_mismatch" in _codes(sequence_fixture)


def test_eclipse_explanation_wide_view_must_precede_closeup(sequence_fixture):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="lunar-eclipse-alignment",
        close_view_mode="moon_close_shadow_entry",
    )
    local = sequence_fixture[2]
    wide, close = local.sequences[0].timeline
    wide.controller_options, close.controller_options = (
        close.controller_options,
        wide.controller_options,
    )

    assert "eclipse_explanation_order_mismatch" in _codes(sequence_fixture)


def test_eclipse_explanation_views_must_be_contiguous(sequence_fixture):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="solar-eclipse-alignment",
        close_view_mode="earth_close_shadow_track",
    )
    local = sequence_fixture[2]
    local.sequences[0].timeline[1].start_frame += 1

    assert "eclipse_explanation_gap" in _codes(sequence_fixture)


def test_second_eclipse_explanation_cannot_hide_a_frame_gap(sequence_fixture):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="solar-eclipse-alignment",
        close_view_mode="earth_close_shadow_track",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B03",
        scene_id=2,
        start_frame=240,
        end_frame=300,
        view_mode="wide_alignment",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B04",
        scene_id=2,
        start_frame=301,
        end_frame=360,
        view_mode="earth_close_shadow_track",
    )

    assert "eclipse_explanation_gap" in _codes(sequence_fixture)


def test_second_eclipse_explanation_cannot_leave_a_wide_view_unmatched(
    sequence_fixture,
):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="lunar-eclipse-alignment",
        close_view_mode="moon_close_shadow_entry",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B03",
        scene_id=2,
        start_frame=240,
        end_frame=300,
        view_mode="wide_alignment",
    )

    assert "eclipse_explanation_missing_close" in _codes(sequence_fixture)


def test_second_eclipse_explanation_cannot_reverse_the_view_order(
    sequence_fixture,
):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="solar-eclipse-alignment",
        close_view_mode="earth_close_shadow_track",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B03",
        scene_id=2,
        start_frame=240,
        end_frame=300,
        view_mode="earth_close_shadow_track",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B04",
        scene_id=2,
        start_frame=300,
        end_frame=360,
        view_mode="wide_alignment",
    )

    assert "eclipse_explanation_order_mismatch" in _codes(sequence_fixture)


def test_second_eclipse_explanation_cannot_cross_scene_boundaries(
    sequence_fixture,
):
    _configure_eclipse_explanation(
        sequence_fixture,
        controller="lunar-eclipse-alignment",
        close_view_mode="moon_close_shadow_entry",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B03",
        scene_id=2,
        start_frame=240,
        end_frame=300,
        view_mode="wide_alignment",
    )
    _append_eclipse_beat(
        sequence_fixture,
        beat_id="B04",
        scene_id=1,
        start_frame=300,
        end_frame=360,
        view_mode="moon_close_shadow_entry",
    )

    assert "eclipse_explanation_scene_mismatch" in _codes(sequence_fixture)


def test_audio_span_must_hold_every_measured_frame(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    local.sequences[0].scene_spans[0].audio_end_frame -= 1

    assert "audio_span_too_short" in _codes(sequence_fixture)


def test_simulation_time_cannot_reverse(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    local.sequences[0].timeline[1].simulation_time_end = 3.0

    assert "simulation_time_reversal" in _codes(sequence_fixture)


def test_nested_overlap_cannot_hide_later_simulation_time_reversal(
    sequence_fixture,
):
    _, production, local, online, _ = sequence_fixture
    production.visual_sequences[0].visual_beat_ids = ["B01", "B02", "B03"]
    production.visual_beats[1].scene_id = 1
    production.visual_beats[1].start_frame = 60
    production.visual_beats[1].end_frame = 90
    third_common = production.visual_beats[1].model_copy(deep=True)
    third_common.beat_id = "B03"
    third_common.scene_id = 2
    third_common.start_frame = 120
    third_common.end_frame = 240
    production.visual_beats.append(third_common)

    first_local, nested_local = local.sequences[0].timeline
    first_local.simulation_time_end = 10.0
    nested_local.start_frame = 60
    nested_local.end_frame = 90
    nested_local.simulation_time_start = 5.0
    nested_local.simulation_time_end = 6.0
    nested_local.priority = 1
    third_local = nested_local.model_copy(deep=True)
    third_local.beat_id = "B03"
    third_local.start_frame = 120
    third_local.end_frame = 240
    third_local.simulation_time_start = 7.0
    third_local.simulation_time_end = 8.0
    third_local.priority = 0
    local.sequences[0].timeline.append(third_local)

    online.shots[1].online_shot_id = "ON-B03"
    online.shots[1].beat_ids = ["B03"]
    nested_online = online.shots[0].model_copy(deep=True)
    nested_online.online_shot_id = "ON-B02-NESTED"
    nested_online.beat_ids = ["B02"]
    nested_online.source_start_frame = 60
    nested_online.source_end_frame = 90
    nested_online.duration_seconds = 1.0
    nested_online.short_shot_reason = "nested visual layer"
    nested_online.prompt_file = "videoFiles/prompts/online/SEQ01/ON-B02-NESTED.txt"
    nested_online.metadata_file = "videoFiles/prompts/online/SEQ01/ON-B02-NESTED.json"
    online.shots.append(nested_online)

    assert "simulation_time_reversal" in _codes(sequence_fixture)


def test_priority_selected_simulation_clock_cannot_drop_at_overlap_start(
    sequence_fixture,
):
    _, production, local, online, _ = sequence_fixture
    production.visual_beats[1].scene_id = 1
    production.visual_beats[1].start_frame = 60

    first_local, overlapping_local = local.sequences[0].timeline
    first_local.patch_targets = ["simulation_clock"]
    overlapping_local.start_frame = 60
    overlapping_local.simulation_time_start = 2.0
    overlapping_local.patch_targets = ["simulation_clock"]
    overlapping_local.priority = 1

    online.shots[1].scene_ids = [1]
    online.shots[1].source_start_frame = 60
    online.shots[1].duration_seconds = 6.0

    assert "simulation_time_reversal" not in _codes(sequence_fixture)

    overlapping_local.simulation_time_start = 1.0
    assert "simulation_time_reversal" in _codes(sequence_fixture)


def test_overlapping_shared_patch_targets_require_distinct_priorities(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    local.sequences[0].timeline[1].start_frame = 100

    assert "ambiguous_patch_priority" in _codes(sequence_fixture)


def test_hold_requires_intent_and_cannot_exceed_two_seconds(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    beat = local.sequences[0].timeline[0]
    beat.simulation_time_end = beat.simulation_time_start

    codes = _codes(sequence_fixture)

    assert "missing_hold_intent" in codes
    assert "hold_too_long" in codes


def test_missing_online_beat_coverage_is_rejected(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    online.shots.pop()

    assert "missing_online_beat" in _codes(sequence_fixture)


def test_partial_online_source_interval_does_not_cover_a_whole_beat(
    sequence_fixture,
):
    _, _, _, online, _ = sequence_fixture
    shot = online.shots[0]
    shot.source_end_frame = 60
    shot.duration_seconds = 2.0
    shot.short_shot_reason = "split beat segment"

    assert "incomplete_online_beat" in _codes(sequence_fixture)


def test_split_online_shots_require_gapless_interval_union(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    first = online.shots[0]
    first.source_end_frame = 70
    first.duration_seconds = 70 / 30
    first.short_shot_reason = "split beat segment"
    second = first.model_copy(deep=True)
    second.online_shot_id = "ON-B01-SPLIT"
    second.source_start_frame = 80
    second.source_end_frame = 120
    second.duration_seconds = 40 / 30
    online.shots.append(second)

    assert "incomplete_online_beat" in _codes(sequence_fixture)

    second.source_start_frame = 60
    second.duration_seconds = 2.0
    assert "incomplete_online_beat" not in _codes(sequence_fixture)


def test_online_shot_over_eight_seconds_is_rejected():
    with pytest.raises(ValidationError):
        OnlineShot.model_validate(
            {
                "online_shot_id": "ON-LONG",
                "beat_ids": ["B01"],
                "scene_ids": [1],
                "source_sequence_id": "SEQ01",
                "source_start_frame": 0,
                "source_end_frame": 241,
                "duration_seconds": 8.01,
                "preferred_mode": "t2v",
                "science_authority": "advisory_only",
                "primary_event": "긴 사건",
                "invariants": ["하나의 사건"],
                "prompt_file": "videoFiles/prompts/online/SEQ01/ON-LONG.txt",
                "metadata_file": "videoFiles/prompts/online/SEQ01/ON-LONG.json",
            }
        )


def test_short_online_shot_requires_reason(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    shot = online.shots[0]
    shot.source_end_frame = 90
    shot.duration_seconds = 3.0

    assert "missing_short_shot_reason" in _codes(sequence_fixture)


def test_online_duration_must_match_source_frames(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    online.shots[0].duration_seconds = 4.1

    assert "online_duration_mismatch" in _codes(sequence_fixture)


def test_online_duration_uses_local_plan_fps(sequence_fixture):
    _, production, _, online, _ = sequence_fixture
    production.defaults.fps = 24
    for shot in online.shots:
        shot.duration_seconds = 5.0

    codes = _codes(sequence_fixture)

    assert "local_defaults_mismatch" in codes
    assert "online_duration_mismatch" in codes


def test_precise_beat_requires_a_local_v2v_reference(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    shot = online.shots[0]
    shot.preferred_mode = "t2v"
    shot.science_authority = "advisory_only"
    shot.reference_video_file = None

    assert "missing_local_v2v_reference" in _codes(sequence_fixture)


def test_non_v2v_precise_science_fallback_must_be_advisory(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    fallback = online.shots[0].model_copy(deep=True)
    fallback.online_shot_id = "ON-B01-FALLBACK"
    fallback.preferred_mode = "t2v"
    fallback.science_authority = "local_reference"
    fallback.reference_video_file = None
    fallback.prompt_file = "videoFiles/prompts/online/SEQ01/ON-B01-FALLBACK.txt"
    fallback.metadata_file = "videoFiles/prompts/online/SEQ01/ON-B01-FALLBACK.json"
    online.shots.append(fallback)

    assert "invalid_science_authority" in _codes(sequence_fixture)


def test_local_beat_must_stay_within_its_owning_scene_span(sequence_fixture):
    _, production, _, online, _ = sequence_fixture
    production.visual_beats[0].scene_id = 2
    online.shots[0].scene_ids = [2]

    assert "local_beat_scene_span_mismatch" in _codes(sequence_fixture)


def test_local_beat_cannot_cross_its_owning_scene_boundary(sequence_fixture):
    _, production, local, online, _ = sequence_fixture
    production.visual_beats[0].end_frame = 121
    local.sequences[0].timeline[0].end_frame = 121
    online.shots[0].source_end_frame = 121
    online.shots[0].duration_seconds = 121 / 30

    assert "local_beat_scene_span_mismatch" in _codes(sequence_fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_file", "../online/ON-B01.txt"),
        ("prompt_file", "/videoFiles/prompts/online/ON-B01.txt"),
        ("metadata_file", "videoFiles/prompts/elsewhere/ON-B01.json"),
        ("reference_video_file", "videoFiles/other/ON-B01.mp4"),
    ],
)
def test_online_declared_paths_stay_in_their_contract_roots(
    sequence_fixture, field: str, value: str
):
    _, _, _, online, _ = sequence_fixture
    setattr(online.shots[0], field, value)

    assert "invalid_online_path" in _codes(sequence_fixture)


def test_online_prompt_and_metadata_paths_must_be_distinct(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    online.shots[0].metadata_file = online.shots[0].prompt_file

    assert "duplicate_online_artifact_path" in _codes(sequence_fixture)


def test_online_artifact_paths_must_be_unique_across_shots(sequence_fixture):
    _, _, _, online, _ = sequence_fixture
    online.shots[1].prompt_file = online.shots[0].metadata_file

    assert "duplicate_online_artifact_path" in _codes(sequence_fixture)


def test_model_rejects_non_positive_half_open_ranges():
    with pytest.raises(ValidationError):
        SceneSpan(
            scene_id=1,
            start_frame=10,
            end_frame=10,
            audio_start_frame=10,
            audio_end_frame=11,
            tail_silence_frames=0,
        )
    with pytest.raises(ValidationError):
        SequenceTimelineBeat(
            beat_id="B01",
            start_frame=10,
            end_frame=10,
            simulation_time_start=0,
            simulation_time_end=1,
            controller="orbit",
            patch_targets=["geometry"],
        )


def test_model_rejects_overlapping_scene_spans(sequence_fixture):
    _, _, local, _, _ = sequence_fixture
    payload = local.model_dump(mode="json")
    payload["sequences"][0]["scene_spans"][1]["start_frame"] = 119

    with pytest.raises(ValidationError, match="scene_spans"):
        LocalSequencePlan.model_validate(payload)
