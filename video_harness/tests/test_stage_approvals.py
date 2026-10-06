import json
from pathlib import Path
import pytest
import video_harness.stage_approvals as stage


import hashlib


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def keywords_run(tmp_path, versions=None, gate='passed'):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'keywords'}}))
    (tmp_path / 'video-plan-approval.json').write_text('{"approved": true}\n')
    (tmp_path / 'local-sequence-plan.json').write_text('{}')
    (tmp_path / 'preview-report.json').write_text(json.dumps({'renderer_versions': versions or {'SEQ01': 'v1'},
        'local_sequence_plan_sha256': sha(tmp_path / 'local-sequence-plan.json')}))
    (tmp_path / 'text-preview-gate.json').write_text(json.dumps({'status': gate, 'issues': []}))
    return tmp_path


def draft_outputs(run, status='passed'):
    (run / 'final-draft.mp4').write_bytes(b'draft')
    qa = run / 'videoFiles/sequences/draft'; qa.mkdir(parents=True, exist_ok=True)
    (qa / 'qa-report.json').write_text(json.dumps({'status': status, 'local_sequence_plan_sha256': sha(run / 'local-sequence-plan.json')}))
    (run / 'text-draft-gate.json').write_text(json.dumps({'status': 'passed', 'issues': []}))


def test_preview_approval_refuses_failed_gate_or_stale_plan(tmp_path, current_versions):
    run = keywords_run(tmp_path, gate='failed')
    with pytest.raises(ValueError, match='text-preview-gate'):
        stage.approve_preview(run)
    run = keywords_run(tmp_path)
    (run / 'local-sequence-plan.json').write_text('{"changed": 1}')
    with pytest.raises(ValueError, match='계획'):
        stage.approve_preview(run)


def test_draft_approval_refuses_failed_qa_or_stale_plan(tmp_path, current_versions):
    run = keywords_run(tmp_path)
    stage.approve_preview(run)
    draft_outputs(run, status='failed')
    with pytest.raises(ValueError, match='QA'):
        stage.approve_draft(run)
    draft_outputs(run)
    (run / 'text-draft-gate.json').write_text(json.dumps({'status': 'failed', 'issues': ['x']}))
    with pytest.raises(ValueError, match='text-draft-gate'):
        stage.approve_draft(run)


@pytest.fixture
def current_versions(monkeypatch):
    holder = {'SEQ01': 'v1'}
    monkeypatch.setattr(stage, 'current_renderer_versions', lambda _run: dict(holder))
    return holder


def test_preview_approval_binds_video_plan_report_and_renderer_versions(tmp_path, current_versions):
    run = keywords_run(tmp_path)
    record = stage.approve_preview(run)
    assert (run / stage.PREVIEW_APPROVAL).is_file() and record.renderer_versions == {'SEQ01': 'v1'}
    stage.require_current_preview_approval(run)
    (run / 'preview-report.json').write_text(json.dumps({'renderer_versions': {'SEQ01': 'v1'}, 'changed': 1}))
    with pytest.raises(ValueError, match='프리뷰'):
        stage.require_current_preview_approval(run)


def test_renderer_source_change_invalidates_preview_approval(tmp_path, current_versions):
    run = keywords_run(tmp_path)
    stage.approve_preview(run)
    current_versions['SEQ01'] = 'v2'
    with pytest.raises(ValueError, match='렌더러'):
        stage.require_current_preview_approval(run)


def test_draft_approval_requires_current_preview_and_binds_draft_outputs(tmp_path, current_versions):
    run = keywords_run(tmp_path)
    with pytest.raises(ValueError, match='프리뷰'):
        stage.approve_draft(run)
    stage.approve_preview(run)
    draft_outputs(run)
    stage.approve_draft(run)
    stage.require_current_draft_approval(run)
    (run / 'final-draft.mp4').write_bytes(b'draft2')
    with pytest.raises(ValueError, match='초본'):
        stage.require_current_draft_approval(run)


def test_require_stage_approval_maps_quality_to_stage(tmp_path, current_versions):
    run = keywords_run(tmp_path)
    with pytest.raises(ValueError, match='프리뷰승인'):
        stage.require_stage_approval(run, 'draft')
    stage.approve_preview(run)
    stage.require_stage_approval(run, 'draft')
    with pytest.raises(ValueError, match='초본승인'):
        stage.require_stage_approval(run, 'final')


def test_legacy_policy_skips_stage_approvals(tmp_path):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'legacy'}}))
    stage.require_stage_approval(tmp_path, 'draft')
    stage.require_stage_approval(tmp_path, 'final')
    stage.require_stage_approval(tmp_path / 'missing-run', 'final')


def test_stage_approvals_apply_to_subtitles_runs(tmp_path):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'subtitles'}}))
    with pytest.raises(ValueError, match='프리뷰승인'):
        stage.require_stage_approval(tmp_path, 'draft')
