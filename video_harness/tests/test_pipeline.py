from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_harness.pipeline import PipelineArtifact, _stable_artifacts, produce
from video_harness.settings import HarnessSettings, LegacyHarnessSettings


def test_generated_artifact_supersedes_its_planned_reference_state() -> None:
    path = "videoFiles/onlineReferences/ON-B01.mp4"

    artifacts = _stable_artifacts(
        [
            PipelineArtifact(path=path, state="planned"),
            PipelineArtifact(path=path, state="generated"),
        ]
    )

    assert artifacts == [PipelineArtifact(path=path, state="generated")]


@pytest.fixture
def pipeline_spies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import video_harness.pipeline as module

    calls = SimpleNamespace(prompt=0, render=0, qualities=[])
    context = SimpleNamespace(
        run_dir=tmp_path,
        script=SimpleNamespace(scenes=[]),
        production=SimpleNamespace(),
        local=SimpleNamespace(sequences=[SimpleNamespace(sequence_id="SEQ01")]),
        online=SimpleNamespace(shots=[]),
        variant=SimpleNamespace(),
    )

    monkeypatch.setattr(module, "load_pipeline_context", lambda _run_dir: context)
    monkeypatch.setattr(module, "validate_pipeline_inputs", lambda *_args, **_kwargs: [])
    def resolve_settings(*_args, **kwargs):
        pipeline = kwargs["cli_overrides"]["pipeline"]
        return HarnessSettings(
            pipeline={
                "output_mode": pipeline["output_mode"] or "all",
                "variant_mode": pipeline["variant_mode"] or "four",
            }
        )

    monkeypatch.setattr(module, "resolve_run_settings", resolve_settings)
    monkeypatch.setattr(module, "_input_hashes", lambda *_args: {
        "script_sha256": "1" * 64,
        "production_plan_sha256": "2" * 64,
        "local_sequence_plan_sha256": "3" * 64,
        "online_plan_sha256": "4" * 64,
    })
    monkeypatch.setattr(module, "_write_settings_snapshot", lambda *_args: None)
    monkeypatch.setattr(module, "_write_pipeline_report", lambda *_args: None)
    monkeypatch.setattr(module, "validate_published_run", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "_video_protection_paths", lambda *_args: [])
    monkeypatch.setattr(module, "require_current_video_plan_approval", lambda *_args: None)
    monkeypatch.setattr(module, "require_stage_approval", lambda *_args: None, raising=False)

    def compile_prompts(*_args, **_kwargs):
        calls.prompt += 1
        path = Path(_args[0]) / "videoFiles/prompts/local/SEQ01.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("prompt", encoding="utf-8")
        return SimpleNamespace(generated=["videoFiles/prompts/local/SEQ01.md"], planned_references=[])

    def render(*_args, **_kwargs):
        calls.render += 1
        calls.qualities.append(_kwargs["quality"])
        is_final = _kwargs["quality"] == "final"
        return SimpleNamespace(
            draft_qa_file="videoFiles/sequences/draft/qa-report.json",
            final_qa_file="qa-report.json" if is_final else None,
            final_file="final.mp4" if is_final else None,
            final_original_file="video-only.mp4" if is_final else None,
            reference_files=[],
            variant_files=["final.mp4"] if is_final else [],
        )

    monkeypatch.setattr(module, "write_compiled_artifacts", compile_prompts)
    monkeypatch.setattr(module, "produce_local", render)
    return calls


def test_default_production_stops_at_draft(tmp_path, pipeline_spies):
    report = produce(tmp_path)

    assert report.quality == "draft"
    assert pipeline_spies.qualities == ["draft"]
    assert "final-draft.mp4" in {item.path for item in report.artifacts}


@pytest.mark.parametrize("mode", ["all", "video_only", "prompts_only"])
def test_cli_shows_review_path_only_after_draft_video_success(
    tmp_path, pipeline_spies, capsys, mode,
):
    from video_harness.pipeline import main

    assert main([str(tmp_path), "--output-mode", mode]) == 0
    output = capsys.readouterr().out
    assert ("final-draft.mp4" in output) == (mode != "prompts_only")
    if mode != "prompts_only":
        assert str(tmp_path / "final-draft.mp4") in output


@pytest.mark.parametrize(
    ("mode", "prompt_calls", "render_calls"),
    [("all", 1, 1), ("video_only", 0, 1), ("prompts_only", 1, 0)],
)
def test_produce_dispatches_exact_selected_stages(
    tmp_path: Path,
    mode: str,
    prompt_calls: int,
    render_calls: int,
    pipeline_spies: SimpleNamespace,
):
    """Changing the mode branch must not run an unselected public stage."""
    report = produce(tmp_path, output_mode=mode)

    assert pipeline_spies.prompt == prompt_calls
    assert pipeline_spies.render == render_calls
    assert report.output_mode == mode


def test_produce_refuses_to_start_without_current_video_plan_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
) -> None:
    import video_harness.pipeline as module
    from video_harness.video_plan_approval import require_current_video_plan_approval

    monkeypatch.setattr(
        module,
        "require_current_video_plan_approval",
        require_current_video_plan_approval,
    )

    with pytest.raises(ValueError, match="영상 생성대본 승인이 없습니다"):
        produce(tmp_path, output_mode="all")

    assert pipeline_spies.prompt == 0
    assert pipeline_spies.render == 0


def test_produce_accepts_schema_v1_settings_for_existing_audio_and_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    import video_harness.pipeline as module

    legacy_settings = LegacyHarnessSettings(
        pipeline={"output_mode": "video_only", "variant_mode": "four"},
        voice={
            "model": "legacy-model",
            "voice": "legacy-voice",
            "instructions": "legacy instructions",
        },
    )
    monkeypatch.setattr(
        module,
        "resolve_run_settings",
        lambda *_args, **_kwargs: legacy_settings,
    )

    report = produce(tmp_path, quality="draft")

    assert report.output_mode == "video_only"
    assert pipeline_spies.render == 1


def test_final_writes_pipeline_report_before_publication_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
) -> None:
    import video_harness.pipeline as module

    report_path = tmp_path / "pipeline-report.json"

    def write_report(_run_dir: Path, _report: object) -> None:
        report_path.write_text("current", encoding="utf-8")

    def validate(_run_dir: Path, *, settings: HarnessSettings) -> list[object]:
        assert report_path.read_text(encoding="utf-8") == "current"
        return []

    monkeypatch.setattr(module, "_write_pipeline_report", write_report)
    monkeypatch.setattr(module, "validate_published_run", validate)

    produce(tmp_path, output_mode="all", quality="final")


def test_prompts_only_never_loads_or_writes_local_production(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    """A prompts-only run must remain usable where renderer dependencies are absent."""
    import video_harness.pipeline as module

    monkeypatch.setattr(
        module,
        "produce_local",
        lambda *_args, **_kwargs: pytest.fail("prompts-only invoked local production"),
    )

    report = produce(tmp_path, output_mode="prompts_only")

    assert report.output_mode == "prompts_only"
    assert not (tmp_path / "local-production-report.json").exists()


def test_generated_reference_replaces_its_earlier_planned_artifact_state():
    """A produced online reference resolves, rather than conflicts with, its plan."""
    assert _stable_artifacts(
        [
            PipelineArtifact(
                path="videoFiles/onlineReferences/ON-B01.mp4", state="planned"
            ),
            PipelineArtifact(
                path="videoFiles/onlineReferences/ON-B01.mp4", state="generated"
            ),
        ]
    ) == [
        PipelineArtifact(
            path="videoFiles/onlineReferences/ON-B01.mp4", state="generated"
        )
    ]


def test_pipeline_import_keeps_renderer_dependencies_lazy():
    """Importing the prompt-only boundary must not load the local renderer module."""
    project_dir = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import video_harness.pipeline; "
            "assert 'video_harness.produce_local' not in sys.modules; "
            "assert 'video_harness.sequence_render' not in sys.modules",
        ],
        cwd=project_dir,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_invalid_inputs_do_not_persist_snapshot_or_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    """A failed input gate must leave the run untouched before publication starts."""
    import video_harness.pipeline as module

    monkeypatch.setattr(module, "validate_pipeline_inputs", lambda *_args, **_kwargs: ["bad audio"])

    with pytest.raises(ValueError, match="input validation failed"):
        produce(tmp_path, output_mode="prompts_only")

    assert not (tmp_path / "run-settings.json").exists()
    assert not (tmp_path / "pipeline-report.json").exists()


def test_video_production_publishes_performance_report_before_final_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    """A completed video run must publish one atomic, quality-bound performance report."""
    import video_harness.pipeline as module

    validation_seen: list[dict[str, object]] = []

    def validate(run_dir: Path, **_kwargs):
        validation_seen.append(
            json.loads((run_dir / "render-performance.json").read_text(encoding="utf-8"))
        )
        return []

    monkeypatch.setattr(module, "validate_published_run", validate)

    produce(tmp_path, output_mode="video_only", quality="draft")

    assert validation_seen == []
    payload = json.loads((tmp_path / "render-performance.json").read_text(encoding="utf-8"))
    assert payload["quality"] == "draft"
    assert payload["encoder_settings"] == {
        "codec": "libx264", "crf": 18, "preset": "medium"
    }


def test_validation_failure_restores_prior_performance_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    """A rejected publication must restore, rather than expose, new diagnostics."""
    import video_harness.pipeline as module

    prior = b'{"quality":"final","prior":true}\n'
    (tmp_path / "render-performance.json").write_bytes(prior)
    validated_payloads: list[dict[str, object]] = []

    def reject(run_dir: Path, **_kwargs):
        validated_payloads.append(
            json.loads((run_dir / "render-performance.json").read_text(encoding="utf-8"))
        )
        return ["bad final QA"]

    monkeypatch.setattr(module, "validate_published_run", reject)

    with pytest.raises(ValueError, match="published artifact validation failed"):
        produce(tmp_path, output_mode="video_only", quality="final")

    assert validated_payloads == [{
        "schema_version": 1,
        "quality": "final",
            "phase_events": [],
            "phase_totals_ms": {},
            "output_totals_ms": {},
            "output_frame_counts": {},
            "rendered_frame_count": 0,
            "reused_frame_count": 0,
            "rendered_sequence_ids": [],
        "reused_sequence_ids": [],
        "avoided_copy_files": 0,
        "avoided_copy_bytes": 0,
        "renderer_reports": [],
        "encoder_settings": {"codec": "libx264", "crf": 18, "preset": "medium"},
    }]
    assert (tmp_path / "render-performance.json").read_bytes() == prior


def test_pipeline_report_failure_restores_prior_prompt_snapshot_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    """The final report write must not expose a half-refreshed successful run."""
    import video_harness.pipeline as module

    protected = {
        "videoFiles/prompts/local/SEQ01.md": b"old prompt",
        "run-settings.json": b"old settings",
        "pipeline-report.json": b"old report",
    }
    for relative, value in protected.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    monkeypatch.setattr(
        module,
        "_write_settings_snapshot",
        lambda run_dir, _settings: (run_dir / "run-settings.json").write_bytes(b"new settings"),
    )

    def fail_report(run_dir: Path, _report):
        (run_dir / "pipeline-report.json").write_bytes(b"new report")
        raise OSError("report disk failure")

    monkeypatch.setattr(module, "_write_pipeline_report", fail_report)

    with pytest.raises(OSError, match="report disk failure"):
        produce(tmp_path, output_mode="all", refresh_settings=True)

    assert {relative: (tmp_path / relative).read_bytes() for relative in protected} == protected


def test_final_validation_failure_restores_staged_prompt_and_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
):
    """A post-publication validation error must restore the prior successful bytes."""
    import video_harness.pipeline as module

    protected = {
        "videoFiles/prompts/local/SEQ01.md": b"old prompt",
        "run-settings.json": b"old settings",
        "pipeline-report.json": b"old report",
    }
    for relative, value in protected.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    monkeypatch.setattr(
        module,
        "_write_settings_snapshot",
        lambda run_dir, _settings: (run_dir / "run-settings.json").write_bytes(b"new settings"),
    )
    monkeypatch.setattr(module, "validate_published_run", lambda *_args, **_kwargs: ["bad final QA"])

    with pytest.raises(ValueError, match="published artifact validation failed"):
        produce(tmp_path, output_mode="all", refresh_settings=True, quality="final")

    assert {relative: (tmp_path / relative).read_bytes() for relative in protected} == protected


def test_produce_refuses_keywords_run_without_preview_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipeline_spies: SimpleNamespace,
) -> None:
    import video_harness.pipeline as module
    from video_harness.stage_approvals import require_stage_approval

    monkeypatch.setattr(module, "require_stage_approval", require_stage_approval)
    (tmp_path / "run-settings.json").write_text('{"schema_version": 4, "local_video": {"text_policy": "keywords"}}')

    with pytest.raises(ValueError, match="프리뷰승인"):
        produce(tmp_path, quality="draft")

    assert pipeline_spies.render == 0
