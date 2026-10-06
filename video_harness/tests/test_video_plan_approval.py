from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import video_harness.video_plan_approval as approval
from video_harness.production import script_sha256
from video_harness.prompt_compiler import write_compiled_artifacts
from video_harness.tests.test_sequence_plans import _local, _online, _production, _script
from video_harness.variants import SequenceVariantPlan


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_reviewable_run(run_dir: Path) -> None:
    for filename in ("story-chain.json", "continuity-plan.json"):
        (run_dir / filename).write_text("{}\n")
    script = _script()
    script_path = run_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production = _production(script_sha256(script_path))
    production_path = run_dir / "production-plan.json"
    production_path.write_text(
        production.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    production_hash = script_sha256(production_path)
    local = _local(production.script_sha256, production_hash)
    online = _online(production.script_sha256, production_hash)
    (run_dir / "local-sequence-plan.json").write_text(
        local.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "online-plan.json").write_text(
        online.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    variant = SequenceVariantPlan.model_validate(
        {
            "schema_version": 2,
            "production_plan_sha256": production_hash,
            "local_sequence_plan_sha256": script_sha256(
                run_dir / "local-sequence-plan.json"
            ),
            "script_sha256": production.script_sha256,
            "variants": [
                {
                    "variant_id": "balanced",
                    "label": "Balanced",
                    "sequence_ids": ["SEQ01"],
                },
                {
                    "variant_id": "explain",
                    "label": "Explain",
                    "sequence_ids": ["SEQ01"],
                    "overrides": [
                        {"sequence_id": "SEQ01", "layer_timing_profile": "explain"}
                    ],
                },
                {
                    "variant_id": "dynamic",
                    "label": "Dynamic",
                    "sequence_ids": ["SEQ01"],
                    "overrides": [
                        {"sequence_id": "SEQ01", "camera_profile": "close"}
                    ],
                },
                {
                    "variant_id": "cinematic",
                    "label": "Cinematic",
                    "sequence_ids": ["SEQ01"],
                    "overrides": [
                        {"sequence_id": "SEQ01", "lighting_profile": "cinematic"}
                    ],
                },
            ],
        }
    )
    (run_dir / "variant-plan.json").write_text(
        variant.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )


def test_approval_binds_every_visual_plan_and_review_file(tmp_path: Path) -> None:
    _write_reviewable_run(tmp_path)

    record = approval.approve_video_plan(tmp_path)
    approval.require_current_video_plan_approval(tmp_path)

    payload = json.loads((tmp_path / "video-plan-approval.json").read_text(encoding="utf-8"))
    assert payload == record.model_dump(mode="json")
    assert payload["schema_version"] == 1
    for filename in (
        "script.json",
        "story-chain.json",
        "continuity-plan.json",
        "production-plan.json",
        "local-sequence-plan.json",
        "online-plan.json",
        "variant-plan.json",
        "video-plan.md",
    ):
        key = filename.replace(".json", "").replace(".md", "").replace("-", "_") + "_sha256"
        assert payload[key] == _sha256(tmp_path / filename)


def test_preview_plan_checkpoint_is_automatic_and_preserves_unchanged_record(tmp_path):
    _write_reviewable_run(tmp_path)
    record = approval.prepare_video_plan(tmp_path)
    assert record.source == 'automatic_validation'
    original = (tmp_path / approval.APPROVAL_FILENAME).read_bytes()
    approval.prepare_video_plan(tmp_path)
    assert (tmp_path / approval.APPROVAL_FILENAME).read_bytes() == original
    approval.require_current_video_plan_approval(tmp_path)


@pytest.mark.parametrize(
    "filename",
    (
        "script.json",
        "story-chain.json",
        "continuity-plan.json",
        "production-plan.json",
        "local-sequence-plan.json",
        "online-plan.json",
        "variant-plan.json",
        "video-plan.md",
    ),
)
def test_any_reviewed_input_change_makes_approval_stale(
    tmp_path: Path,
    filename: str,
) -> None:
    _write_reviewable_run(tmp_path)
    approval.approve_video_plan(tmp_path)
    path = tmp_path / filename
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match=rf"오래되었습니다.*{filename}"):
        approval.require_current_video_plan_approval(tmp_path)


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.require_creative_plan", lambda *args, **kwargs: [])
