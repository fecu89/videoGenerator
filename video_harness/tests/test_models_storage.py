from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.storage import RunStore, sanitize_filename, scene_filename


PROJECT_DIR = Path(__file__).resolve().parents[2]


def minimal_script_payload():
    return {
        "candidates": [],
        "selected_topic": {"title": "테스트", "reason": "검증"},
        "story_engine": {
            "common_belief": "상식",
            "contradiction": "충돌",
            "obvious_answer": "예상",
            "constraint": "제약",
            "actual_answer": "실제 답",
            "mechanism": "원리",
            "payoff": "결말",
        },
        "scenes": [
            {
                "scene_id": 1,
                "title": "첫 장면",
                "narration": "첫 장면입니다.",
                "narrative_role": "HOOK",
                "visual_subject": "구조물",
                "source_ids": [],
                "duration_seconds": None,
                "audio_file": None,
                "video_prompt_file": None,
            }
        ],
        "fact_checks": [],
        "sources": [],
    }


def test_script_rejects_non_contiguous_scene_ids():
    with pytest.raises(ValidationError, match="contiguous"):
        ScriptArtifact(
            selected_topic=SelectedTopic(title="테스트", reason="검증"),
            story_engine=StoryEngine(
                common_belief="상식",
                contradiction="충돌",
                obvious_answer="예상",
                constraint="제약",
                actual_answer="실제 답",
                mechanism="원리",
                payoff="결말",
            ),
            scenes=[
                Scene(
                    scene_id=1,
                    title="첫 장면",
                    narration="첫 장면입니다.",
                    narrative_role="HOOK",
                    visual_subject="구조물",
                ),
                Scene(
                    scene_id=3,
                    title="셋째 장면",
                    narration="세 번째 장면입니다.",
                    narrative_role="CONTEXT",
                    visual_subject="구조물 내부",
                ),
            ],
        )


def test_run_store_writes_json_atomically(tmp_path):
    store = RunStore.create(tmp_path, "피사의 사탑은 왜?", input_kind="topic")

    store.write_json("input.json", {"topic": "피사의 사탑"})

    assert store.read_json("input.json") == {"topic": "피사의 사탑"}
    assert not list(store.root.glob("*.tmp"))
    assert store.audio_dir.is_dir()


def test_run_store_creates_prompt_directories_only_when_a_prompt_is_written(tmp_path):
    store = RunStore.create(tmp_path, "시뮬레이션 전용", input_kind="topic")

    store.ensure_production_directories()

    assert not store.video_prompt_dir.exists()
    assert not (store.video_dir / "prompts").exists()

    store.write_text("videoPrompt/01A_생성.txt", "prompt\n")
    store.write_text("videoFiles/prompts/01_장면/01A_생성.txt", "prompt\n")

    assert store.video_prompt_dir.is_dir()
    assert (store.video_dir / "prompts/01_장면").is_dir()


def test_sanitize_filename_removes_path_characters():
    assert sanitize_filename("왜/무너지지 않을까?:*") == "왜_무너지지_않을까"


def test_schema_and_pydantic_accept_same_minimal_script():
    payload = minimal_script_payload()
    script = ScriptArtifact.model_validate(payload)
    schema = json.loads(
        (PROJECT_DIR / "video_harness/schemas/script.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert script.scenes[0].scene_id == 1
    assert set(schema["required"]) <= set(payload)


def test_scene_accepts_sparse_script_authored_sentence_delivery():
    scene = Scene(
        scene_id=1,
        title="감정 지시",
        narration="첫 문장입니다. 정말일까요? 네, 맞습니다!",
        narrative_role="REVEAL",
        visual_subject="질문과 답",
        sentence_delivery=[
            {"sentence_index": 2, "emotion": "curious", "intensity": "subtle"},
            {"sentence_index": 3, "emotion": "confident", "intensity": "moderate"},
        ],
    )

    assert [cue.sentence_index for cue in scene.sentence_delivery] == [2, 3]
    assert scene.sentence_delivery[0].emotion == "curious"
    assert scene.sentence_delivery[1].intensity == "moderate"


def test_scene_rejects_duplicate_sentence_delivery_indices():
    with pytest.raises(ValidationError, match="unique"):
        Scene(
            scene_id=1,
            title="중복 지시",
            narration="첫 문장입니다. 둘째 문장입니다.",
            narrative_role="HOOK",
            visual_subject="두 문장",
            sentence_delivery=[
                {"sentence_index": 1, "emotion": "bright", "intensity": "subtle"},
                {"sentence_index": 1, "emotion": "gentle", "intensity": "moderate"},
            ],
        )


def test_scene_rejects_sentence_delivery_beyond_narration_sentence_count():
    with pytest.raises(ValidationError, match="sentence_index.*2"):
        Scene(
            scene_id=1,
            title="범위 밖 지시",
            narration="첫 문장입니다. 둘째 문장입니다.",
            narrative_role="HOOK",
            visual_subject="두 문장",
            sentence_delivery=[
                {"sentence_index": 3, "emotion": "surprised", "intensity": "subtle"}
            ],
        )


def test_script_schema_accepts_delivery_and_rejects_unknown_emotion():
    payload = minimal_script_payload()
    payload["scenes"][0]["sentence_delivery"] = [
        {"sentence_index": 1, "emotion": "bright", "intensity": "subtle"}
    ]
    schema = json.loads(
        (PROJECT_DIR / "video_harness/schemas/script.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)

    assert list(validator.iter_errors(payload)) == []

    payload["scenes"][0]["sentence_delivery"][0]["emotion"] = "automatic"
    errors = list(validator.iter_errors(payload))
    assert len(errors) == 1
    assert list(errors[0].absolute_path)[-1] == "emotion"


def test_scene_filename_is_numbered_and_sanitized():
    scene = Scene.model_validate(minimal_script_payload()["scenes"][0])
    scene.title = "왜/무너지지 않을까?"

    assert scene_filename(scene, ".mp3") == "01_왜_무너지지_않을까.mp3"


def test_run_store_reads_and_writes_script(tmp_path):
    store = RunStore.create(tmp_path, "테스트", input_kind="pdf")
    script = ScriptArtifact.model_validate(minimal_script_payload())

    store.write_script(script)

    assert store.read_script() == script


def test_agent_bootstrap_resolves_to_the_internal_workflow():
    bootstrap = (PROJECT_DIR / "AGENTS.md").read_text(encoding="utf-8")
    workflow_path = PROJECT_DIR / "video_harness/agent/WORKFLOW.md"

    assert "video_harness/agent/WORKFLOW.md" in bootstrap
    assert workflow_path.is_file()
