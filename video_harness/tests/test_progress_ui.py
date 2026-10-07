import hashlib
import json

from video_harness.progress_ui import ProgressMonitor
from video_harness.progress_ui import describe_postprocess


def test_postprocess_displays_the_actual_child_operation():
    assert describe_postprocess('ffmpeg -f concat -i concat.txt out.mp4')[0] == '영상 합치기'
    assert describe_postprocess('ffmpeg -vf blackframe=amount=98 out.mp4')[0] == '화면 품질 검사'
    assert describe_postprocess('ffmpeg -i in.mp4 /run/videoFiles/previews/half-second/001.png')[0] == '검사용 이미지 만들기'
    assert describe_postprocess('ffmpeg -filter_complex amix=inputs=2 /run/final-ko.m4a')[0] == '음성·배경음악 합치기'
    assert describe_postprocess('ffprobe -count_frames -show_streams /run/final.mp4')[0] == '영상 길이·프레임 검사'
    assert describe_postprocess('ffmpeg -i in.mp4 /run/videoFiles/onlineReferences/ON-B23.tmp.mp4')[0] == '장면별 참고 클립 만들기'
    assert describe_postprocess('')[0] == '최종 후처리'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_progress_waits_for_process_and_new_verified_output(tmp_path):
    run = tmp_path / 'run'
    staging = run / '.local-final-test'
    cache = staging / '.render-cache/sequences/final/SEQ01'
    write_json(run / 'script.json', {})
    write_json(cache / 'render-job.json', {'frame_count': 10})
    (cache / 'blender-render.log').write_text('Saved: frame-000004.png\n')
    alive = [True]
    monitor = ProgressMonitor(run, staging, 123, 10, 'final', alive=lambda: alive[0])
    assert monitor.status()['completed_frames'] == 5
    assert monitor.status()['state'] == 'rendering'
    (cache / 'blender-render.log').write_text('Saved: frame-000009.png\n')
    assert monitor.status()['state'] == 'finishing'
    write_json(run / 'pipeline-report.json', {
        'status': 'complete', 'quality': 'final',
        'script_sha256': hashlib.sha256((run / 'script.json').read_bytes()).hexdigest(),
    })
    write_json(run / 'qa-report.json', {'status': 'passed'})
    (run / 'final.mp4').write_bytes(b'video')
    assert monitor.status()['state'] == 'finishing'
    alive[0] = False
    assert monitor.status()['state'] == 'complete'


def test_old_output_is_not_current_success(tmp_path):
    write_json(tmp_path / 'pipeline-report.json', {'status': 'complete', 'quality': 'final'})
    write_json(tmp_path / 'qa-report.json', {'status': 'passed'})
    (tmp_path / 'final.mp4').write_bytes(b'old')
    monitor = ProgressMonitor(tmp_path, tmp_path / 'staging', 123, 10, 'final', alive=lambda: False)
    assert monitor.status()['state'] == 'stopped'


def test_delivery_failure_is_separate_from_local_video_completion(tmp_path):
    write_json(tmp_path / 'script.json', {})
    write_json(tmp_path / 'delivery-report.json', {'status': 'complete', 'items': []})
    monitor = ProgressMonitor(tmp_path, tmp_path / 'staging', 123, 10, 'final', alive=lambda: False)
    assert monitor.status()['delivery'] == {}
    write_json(tmp_path / 'pipeline-report.json', {'status': 'complete', 'quality': 'final',
        'script_sha256': hashlib.sha256((tmp_path / 'script.json').read_bytes()).hexdigest()})
    write_json(tmp_path / 'qa-report.json', {'status': 'passed'})
    (tmp_path / 'final.mp4').write_bytes(b'video')
    write_json(tmp_path / 'delivery-report.json', {'status': 'failed', 'error': 'delivery unavailable', 'items': []})
    status = monitor.status()
    assert status['state'] == 'complete'
    assert status['delivery']['status'] == 'failed'


def test_progress_requires_every_language_video_and_lists_downloads(tmp_path):
    write_json(tmp_path / 'script.json', {})
    write_json(tmp_path / 'run-settings.json', {'schema_version': 6, 'local_video': {
        'text_policy': 'subtitles', 'subtitle_languages': 'en,ja,zh,es', 'localized_delivery': 'videos'}})
    monitor = ProgressMonitor(tmp_path, tmp_path / 'staging', 123, 10, 'final', alive=lambda: False)
    write_json(tmp_path / 'pipeline-report.json', {'status': 'complete', 'quality': 'final',
        'script_sha256': hashlib.sha256((tmp_path / 'script.json').read_bytes()).hexdigest()})
    write_json(tmp_path / 'qa-report.json', {'status': 'passed'})
    (tmp_path / 'final.mp4').write_bytes(b'video')
    for lang in ('ko', 'en', 'ja', 'zh'):
        (tmp_path / f'final-{lang}.mp4').write_bytes(b'video')
    assert monitor.status()['state'] == 'stopped'
    assert monitor.status()['videos'] == []
    (tmp_path / 'final-es.mp4').write_bytes(b'video')
    status = monitor.status()
    assert status['state'] == 'complete'
    assert status['videos'] == [{'lang': lang, 'file': f'final-{lang}.mp4', 'url': f'/videos/{lang}.mp4'}
                                for lang in ('ko', 'en', 'ja', 'zh', 'es')]


def test_language_video_endpoint_serves_selected_video_only_after_completion(tmp_path):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from types import SimpleNamespace
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import pytest
    from video_harness.progress_ui import handler_for

    video = tmp_path / 'final-en.mp4'
    video.write_bytes(b'english-video')
    state = {'state': 'complete'}
    monitor = SimpleNamespace(language_videos={'en': video}, status=lambda: state, quality='final')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(monitor))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(Request(base + '/videos/en.mp4', headers={'Range': 'bytes=0-6'})) as response:
            assert response.status == 206 and response.read() == b'english'
        with pytest.raises(HTTPError) as missing:
            urlopen(base + '/videos/ja.mp4')
        assert missing.value.code == 404
        state['state'] = 'finishing'
        with pytest.raises(HTTPError) as unfinished:
            urlopen(base + '/videos/en.mp4')
        assert unfinished.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
