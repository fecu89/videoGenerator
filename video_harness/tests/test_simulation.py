from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.simulation import load_simulation


TEMPLATES = [
    ("sky-orbit-reveal", "sky-to-orbit"),
    ("retrograde-track", "fixed-sky"),
    ("moving-observer", "earth-pullback"),
    ("sightline-angle", "orbit-three-quarter"),
    ("speed-comparison", "orbit-top"),
    ("earth-overtake", "earth-tracking"),
    ("projection-proof", "projection-three-quarter"),
    ("return-to-direct", "orbit-to-sky"),
]


def make_script(scene_count: int = 8) -> ScriptArtifact:
    return ScriptArtifact(
        selected_topic=SelectedTopic(title="화성 역행", reason="테스트"),
        story_engine=StoryEngine(
            common_belief="상식",
            contradiction="충돌",
            obvious_answer="질문",
            constraint="조건",
            actual_answer="답",
            mechanism="원리",
            payoff="결과",
        ),
        scenes=[
            Scene(
                scene_id=scene_id,
                title=f"장면_{scene_id}",
                narration=f"{scene_id}번 장면입니다.",
                narrative_role="MECHANISM",
                visual_subject="지구와 화성",
                duration_seconds=6.0,
                audio_file=f"audioFiles/{scene_id:02d}_장면_{scene_id}.mp3",
            )
            for scene_id in range(1, scene_count + 1)
        ],
    )


def simulation_payload(scene_count: int = 8) -> dict:
    return {
        "schema_version": 1,
        "preset": "mars-retrograde",
        "output": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "physics": {
            "model": "circular-teaching-model",
            "earth_period_days": 365.0,
            "mars_period_days": 687.0,
            "earth_orbit_radius": 1.0,
            "mars_orbit_radius": 1.52,
            "opposition_day": 0.0,
        },
        "style": {
            "preset": "hybrid-space-explainer",
            "seed": 220826,
            "earth_scale": 0.075,
            "mars_scale": 0.055,
            "show_labels": False,
        },
        "scenes": [
            {
                "scene_id": scene_id,
                "template": TEMPLATES[scene_id - 1][0],
                "simulation_day_start": -70.0,
                "simulation_day_end": 70.0,
                "camera": TEMPLATES[scene_id - 1][1],
            }
            for scene_id in range(1, scene_count + 1)
        ],
    }


def write_simulation(run_dir: Path, payload: dict) -> None:
    (run_dir / "simulation.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_simulation_matches_all_script_scenes(tmp_path):
    write_simulation(tmp_path, simulation_payload())

    config = load_simulation(tmp_path, make_script())

    assert [scene.scene_id for scene in config.scenes] == list(range(1, 9))
    assert config.physics.earth_period_days == 365.0
    assert config.physics.mars_period_days == 687.0


def test_load_simulation_accepts_scene_transition_settings(tmp_path):
    payload = simulation_payload()
    payload["output"]["scene_transition"] = {
        "mode": "dip_to_black",
        "duration_seconds": 0.24,
        "fade_seconds": 0.1,
    }
    write_simulation(tmp_path, payload)

    config = load_simulation(tmp_path, make_script())

    assert config.output.scene_transition.mode == "dip_to_black"


def test_load_simulation_rejects_scene_mismatch(tmp_path):
    write_simulation(tmp_path, simulation_payload(scene_count=7))

    with pytest.raises(ValueError, match="script.json"):
        load_simulation(tmp_path, make_script(scene_count=8))


def test_load_simulation_rejects_unknown_template_at_schema_boundary(tmp_path):
    payload = simulation_payload()
    payload["scenes"][0]["template"] = "invented-motion"
    write_simulation(tmp_path, payload)

    with pytest.raises(ValueError, match="simulation.json scenes.0.template"):
        load_simulation(tmp_path, make_script())


def test_load_simulation_rejects_non_contiguous_scene_ids(tmp_path):
    payload = simulation_payload()
    payload["scenes"][3]["scene_id"] = 9
    write_simulation(tmp_path, payload)

    with pytest.raises(ValueError, match="contiguous"):
        load_simulation(tmp_path, make_script())
