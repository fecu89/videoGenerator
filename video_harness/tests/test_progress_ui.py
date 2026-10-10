import hashlib
import json
import pytest

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


@pytest.mark.parametrize('delivery', ['videos', 'video_and_audio'])
def test_progress_requires_every_language_output_and_lists_downloads(tmp_path, delivery):
    write_json(tmp_path / 'script.json', {})
    write_json(tmp_path / 'run-settings.json', {'schema_version': 6, 'local_video': {
        'text_policy': 'subtitles', 'subtitle_languages': 'en,ja,zh,es', 'localized_delivery': delivery}})
    monitor = ProgressMonitor(tmp_path, tmp_path / 'staging', 123, 10, 'final', alive=lambda: False)
    write_json(tmp_path / 'pipeline-report.json', {'status': 'complete', 'quality': 'final',
        'script_sha256': hashlib.sha256((tmp_path / 'script.json').read_bytes()).hexdigest()})
    write_json(tmp_path / 'qa-report.json', {'status': 'passed'})
    (tmp_path / 'final.mp4').write_bytes(b'video')
    for lang in ('ko', 'en', 'ja', 'zh'):
        suffix = '.m4a' if delivery == 'video_and_audio' and lang != 'ko' else '.mp4'
        (tmp_path / f'final-{lang}{suffix}').write_bytes(b'media')
    assert monitor.status()['state'] == 'stopped'
    assert monitor.status()['videos'] == []
    (tmp_path / ('final-es.m4a' if delivery == 'video_and_audio' else 'final-es.mp4')).write_bytes(b'media')
    status = monitor.status()
    assert status['state'] == 'complete'
    assert status['videos'] == [{'lang': lang, 'file': f'final-{lang}.mp4', 'url': f'/videos/{lang}.mp4'}
                                for lang in (('ko',) if delivery == 'video_and_audio' else ('ko', 'en', 'ja', 'zh', 'es'))]
    assert status['audio_tracks'] == ([{'lang': lang, 'file': f'final-{lang}.m4a', 'url': f'/audio/{lang}.m4a'}
                                       for lang in ('en', 'ja', 'zh', 'es')] if delivery == 'video_and_audio' else [])


@pytest.mark.parametrize('audio', [False, True])
def test_language_media_endpoint_serves_selected_output_only_after_completion(tmp_path, audio):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from types import SimpleNamespace
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import pytest
    from video_harness.progress_ui import handler_for

    suffix = 'm4a' if audio else 'mp4'
    endpoint = 'audio' if audio else 'videos'
    video = tmp_path / f'final-en.{suffix}'
    video.write_bytes(b'english-video')
    state = {'state': 'complete'}
    monitor = SimpleNamespace(language_videos={} if audio else {'en': video},
                              language_audio={'en': video} if audio else {}, status=lambda: state, quality='final')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(monitor))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(Request(base + f'/{endpoint}/en.{suffix}', headers={'Range': 'bytes=0-6'})) as response:
            assert response.status == 206 and response.read() == b'english'
            assert response.headers['Content-Type'] == ('audio/mp4' if audio else 'video/mp4')
        with pytest.raises(HTTPError) as missing:
            urlopen(base + f'/{endpoint}/ja.{suffix}')
        assert missing.value.code == 404
        state['state'] = 'finishing'
        with pytest.raises(HTTPError) as unfinished:
            urlopen(base + f'/{endpoint}/en.{suffix}')
        assert unfinished.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_progress_shows_fresh_failure_after_qa_rollback(tmp_path):
    monitor = ProgressMonitor(tmp_path, tmp_path, 123, 10, 'draft', alive=lambda: False)
    write_json(tmp_path / 'production-failure.json', {'quality': 'draft', 'pid': 123,
        'error': 'draft QA failed', 'issues': [{'code': 'bad_frame', 'message': 'frame 42'}]})
    status = monitor.status()
    assert status['state'] == 'stopped'
    assert status['issues'] == [{'code': 'bad_frame', 'message': 'frame 42'}]
    # A prior attempt or another producer must not be attributed to this process.
    write_json(tmp_path / 'production-failure.json', {'quality': 'draft', 'pid': 456,
        'error': 'another failure', 'issues': [{'code': 'unrelated'}]})
    assert monitor.status()['issues'] == []
