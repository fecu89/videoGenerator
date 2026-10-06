import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from video_harness.preview_ui import ReviewServer, build_review, revision, save_feedback, media_path


def write_run(run):
    def put(name, value):
        (run / name).write_text(json.dumps(value, ensure_ascii=False))
    put('script.json', {'selected_topic': {'title': '빛'}, 'scenes': [
        {'scene_id': 1, 'title': '첫 장면', 'narration': '첫 대본', 'visual_subject': '태양', 'duration_seconds': 2},
        {'scene_id': 2, 'title': '두 번째', 'narration': '둘째 대본', 'duration_seconds': 2}]})
    put('production-plan.json', {'visual_beats': [{'beat_id': 'B1', 'primary_event': '태양 확대'}]})
    sequences = []
    reports = []
    # Separate sequences both start at zero; mapping by global frame would mix scenes.
    for i in (1, 2):
        sequences.append({'sequence_id': f'S{i}', 'scene_spans': [{'scene_id': i, 'start_frame': 0, 'end_frame': 60}],
                          'timeline': [{'beat_id': f'B{i}', 'start_frame': 0, 'end_frame': 60,
                                        'controller_options': {'review_visual_description': f'연출 {i}'}}]})
        (run / f'{i}.png').write_bytes(b'PNG')
        reports.append({'sequence_id': f'S{i}', 'frames': [f'{i}.png'], 'state_samples': [{'canonical_frame': 30}]})
    put('local-sequence-plan.json', {'defaults': {'fps': 30}, 'sequences': sequences})
    put('preview-report.json', {'sequences': list(reversed(reports))})
    (run / 'story-review.md').write_text('# 전체 스토리\n첫 대본\n둘째 대본')


def test_reusable_payload_maps_sequence_local_frames_by_id(tmp_path):
    write_run(tmp_path)
    review = build_review(tmp_path)
    assert review['title'] == '빛'
    assert review['scenes'][0]['frames'][0] == {'url': '/media/1.png', 'time': 1.0, 'beat_id': 'B1'}
    assert review['scenes'][1]['frames'][0]['url'] == '/media/2.png'
    assert review['scenes'][1]['shots'][0]['direction'] == '연출 2'


def test_story_without_video_artifacts_and_optional_idea(tmp_path, monkeypatch):
    write_run(tmp_path)
    for name in ('production-plan.json', 'local-sequence-plan.json', 'preview-report.json'):
        (tmp_path / name).unlink()
    review = build_review(tmp_path, 'story')
    assert review['story'].startswith('# 전체 스토리')
    assert review['scenes'][0]['visual_subject'] == '태양'
    monkeypatch.setattr('video_harness.creative_gates.require_story_chain', lambda run: None)
    result = save_feedback(tmp_path, {'revision': review['revision'], 'comments': {}, 'action': 'approve'}, 'story')
    assert result['status'] == 'approved'
    assert result['visual_brief'] == ''
    assert (tmp_path / 'story-approval.json').exists()
    assert not (tmp_path / 'preview-approval.json').exists()


def test_feedback_saved_separately_without_changing_script(tmp_path):
    write_run(tmp_path)
    original = (tmp_path / 'script.json').read_bytes()
    payload = {'revision': revision(tmp_path, 'story'), 'comments': {'2': '더 짧게'}, 'overall': '설명 흐름 수정', 'visual_brief': '안개 낀 거리'}
    save_feedback(tmp_path, payload, 'story')
    review = build_review(tmp_path, 'story')
    assert review['feedback']['visual_brief'] == '안개 낀 거리'
    assert review['feedback']['comments']['2'] == '더 짧게'
    assert (tmp_path / 'script.json').read_bytes() == original
    assert not (tmp_path / 'story-approval.json').exists()


def test_stale_feedback_and_invalid_scenes_cannot_save(tmp_path):
    write_run(tmp_path)
    payload = {'revision': revision(tmp_path), 'comments': {'100': '없는 장면'}}
    with pytest.raises(ValueError, match='장면별'):
        save_feedback(tmp_path, payload)
    payload['comments'] = {'1': '수정'}
    (tmp_path / 'script.json').write_text((tmp_path / 'script.json').read_text() + '\n')
    with pytest.raises(ValueError, match='변경'):
        save_feedback(tmp_path, payload)


def test_new_revision_clears_old_comments_but_keeps_optional_idea_and_history(tmp_path):
    write_run(tmp_path)
    save_feedback(tmp_path, {'revision': revision(tmp_path, 'story'), 'comments': {'1': '짧게'}, 'visual_brief': '안개'}, 'story')
    (tmp_path / 'story-review.md').write_text('수정된 스토리')
    review = build_review(tmp_path, 'story')
    assert review['feedback_stale']
    assert review['feedback']['comments'] == {}
    assert review['feedback']['visual_brief'] == '안개'
    assert review['previous_feedback']['comments'] == {'1': '짧게'}
    save_feedback(tmp_path, {'revision': review['revision'], 'comments': {}, 'visual_brief': '안개'}, 'story')
    assert list((tmp_path / 'review-history').glob('story-feedback-*.json'))


def test_new_edit_request_revokes_previous_approval_without_losing_it(tmp_path):
    write_run(tmp_path)
    (tmp_path / 'preview-approval.json').write_text('{}')
    save_feedback(tmp_path, {'revision': revision(tmp_path), 'comments': {'1': '수정해줘'}})
    assert not (tmp_path / 'preview-approval.json').exists()
    assert list((tmp_path / 'review-history').glob('preview-approval-*.json'))


@pytest.mark.parametrize('mode', ['preview', 'story'])
def test_approve_with_comments_is_blocked(tmp_path, mode, monkeypatch):
    write_run(tmp_path)
    def unexpected_approval(*args):
        pytest.fail('수정 요청을 승인으로 기록하면 안 됩니다.')
    monkeypatch.setattr('video_harness.stage_approvals.approve_preview', unexpected_approval)
    monkeypatch.setattr('video_harness.creative_gates.require_story_chain', unexpected_approval)
    with pytest.raises(ValueError, match='수정 의견이 남아'):
        save_feedback(tmp_path, {'revision': revision(tmp_path, mode), 'comments': {'1': '고쳐줘'}, 'action': 'approve'}, mode)
    assert not (tmp_path / 'preview-approval.json').exists()
    assert not (tmp_path / 'story-approval.json').exists()


def test_regeneration_saves_feedback_queues_work_and_blocks_duplicate_and_approval(tmp_path):
    from video_harness.preview_ui import update_regeneration
    write_run(tmp_path)
    payload = {'revision': revision(tmp_path), 'comments': {'1': '태양에서 가로등으로 전환'}, 'action': 'regenerate'}
    result = save_feedback(tmp_path, payload)
    assert result['regeneration']['status'] == 'queued'
    assert result['regeneration']['feedback']['comments'] == payload['comments']
    assert build_review(tmp_path)['regeneration']['status'] == 'queued'
    assert not (tmp_path / 'preview-approval.json').exists()
    repeated = save_feedback(tmp_path, payload)
    assert repeated['regeneration']['request_id'] == result['regeneration']['request_id']
    with pytest.raises(ValueError, match='이미'):
        save_feedback(tmp_path, dict(payload, comments={'1': '다른 요청'}))
    with pytest.raises(ValueError, match='재생성 중'):
        save_feedback(tmp_path, dict(payload, action='approve', comments={}))
    update_regeneration(tmp_path, 'rendering', '렌더링 중')
    assert build_review(tmp_path)['regeneration']['status'] == 'rendering'
    plan = tmp_path / 'local-sequence-plan.json'
    plan.write_text(plan.read_text() + '\n')
    assert save_feedback(tmp_path, payload)['regeneration']['request_id'] == result['regeneration']['request_id']
    update_regeneration(tmp_path, 'completed', '완료')
    assert build_review(tmp_path)['regeneration']['result_revision'] == revision(tmp_path)


def test_media_cannot_escape_run_or_read_json(tmp_path):
    write_run(tmp_path)
    for path in ('../private.png', 'script.json'):
        with pytest.raises(ValueError):
            media_path(tmp_path, path)


def test_local_http_feedback_round_trip_and_origin_guard(tmp_path):
    write_run(tmp_path)
    server = ReviewServer(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = json.load(urlopen(server.origin + '/api/review'))
        assert b'review.js' in urlopen(server.origin).read()
        payload = json.dumps({'revision': data['revision'], 'comments': {'1': '카메라 천천히'}}).encode()
        req = Request(server.origin + '/api/feedback', data=payload, headers={'Content-Type': 'application/json', 'Origin': server.origin, 'X-Review-Token': data['token']})
        assert json.load(urlopen(req))['status'] == 'changes_requested'
        assert json.load(urlopen(server.origin + '/api/review'))['feedback']['comments']['1'] == '카메라 천천히'
        req.headers['Origin'] = 'https://unrelated.example'
        with pytest.raises(HTTPError) as error:
            urlopen(req)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_story_approval_closes_the_review_server(tmp_path, monkeypatch):
    write_run(tmp_path)
    monkeypatch.setattr('video_harness.creative_gates.require_story_chain', lambda run: None)
    server = ReviewServer(tmp_path, mode='story')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = json.load(urlopen(server.origin + '/api/review'))
        headers = {'Content-Type': 'application/json', 'Origin': server.origin, 'X-Review-Token': data['token']}

        def post(action):
            body = json.dumps({'revision': data['revision'], 'comments': {}, 'action': action}).encode()
            return json.load(urlopen(Request(server.origin + '/api/feedback', data=body, headers=headers)))

        # Saving keeps the review open; only an approval ends it.
        assert post('save')['closing'] is False
        assert thread.is_alive()
        result = post('approve')
        assert result['status'] == 'approved' and result['closing'] is True
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert (tmp_path / 'story-approval.json').exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_preview_command_opens_review_after_render(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from video_harness import preview, preview_ui
    calls = []
    monkeypatch.setattr(preview, 'render_preview', lambda run: calls.append('render') or SimpleNamespace(contact_sheet_file='sheet.png'))
    monkeypatch.setattr(preview_ui, 'serve_review', lambda run, **kwargs: calls.append('web') or 0)
    assert preview.main([str(tmp_path)]) == 0
    assert calls == ['render', 'web']
    calls.clear()
    assert preview.main([str(tmp_path), '--no-ui']) == 0
    assert calls == ['render']
