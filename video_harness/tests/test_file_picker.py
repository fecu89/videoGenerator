from types import SimpleNamespace


from video_harness import file_picker
from video_harness.tests.test_settings_ui import running_server, request, api_headers


def test_native_picker_preserves_filename_and_handles_cancel(tmp_path, monkeypatch):
    audio = tmp_path / '별빛 "목소리".wav'
    audio.touch()
    monkeypatch.setattr(file_picker, 'BGMUSIC_DIR', tmp_path)
    calls = []
    results = iter([str(audio) + '\n', '\n'])
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=next(results))
    monkeypatch.setattr(file_picker.sys, 'platform', 'darwin')
    monkeypatch.setattr(file_picker.subprocess, 'run', run)
    assert file_picker.choose_local_path('bgmusic') == audio.name
    assert file_picker.choose_local_path('bgmusic') is None
    assert all(cmd[:2] == ['osascript', '-e'] for cmd in calls)
    assert all(str(audio) not in cmd[2] for cmd in calls)


def test_picker_requires_session_auth_and_does_not_save_settings(running_server, monkeypatch):
    calls = []
    def pick(kind):
        calls.append(kind)
        return '/tmp/참조.wav'
    monkeypatch.setattr('video_harness.settings_ui.choose_local_path', pick)
    before = running_server.settings_file.read_bytes()
    status, _, _ = request(running_server, 'POST', '/api/pick-bgmusic')
    assert status == 403
    assert calls == []
    status, payload, _ = request(running_server, 'POST', '/api/pick-bgmusic',
                               headers=api_headers(running_server))
    assert status == 200 and payload == {'path': '/tmp/참조.wav', 'cancelled': False}
    assert calls == ['bgmusic']
    assert running_server.settings_file.read_bytes() == before
    with running_server.picker_lock:
        status, _, _ = request(running_server, 'POST', '/api/pick-bgmusic',
                               headers=api_headers(running_server))
    assert status == 409 and len(calls) == 1


def test_picker_cancel_and_error_release_lock(running_server, monkeypatch):
    monkeypatch.setattr('video_harness.settings_ui.choose_local_path', lambda kind: None)
    status, payload, _ = request(running_server, 'POST', '/api/pick-bgmusic',
                               headers=api_headers(running_server))
    assert status == 200 and payload == {'path': None, 'cancelled': True}
    def fail(kind):
        raise RuntimeError('선택 오류')
    monkeypatch.setattr('video_harness.settings_ui.choose_local_path', fail)
    status, payload, _ = request(running_server, 'POST', '/api/pick-bgmusic',
                               headers=api_headers(running_server))
    assert status == 400 and payload['message'] == '선택 오류'
    assert running_server.picker_lock.acquire(blocking=False)
    running_server.picker_lock.release()


def test_bgmusic_picker_starts_in_library_and_returns_the_file_name(tmp_path, monkeypatch):
    library = tmp_path / 'bgmusic'; library.mkdir()
    inside = library / 'calm.mp3'; inside.write_bytes(b'a')
    outside = tmp_path / 'elsewhere' / 'wild.wav'; outside.parent.mkdir(); outside.write_bytes(b'b')
    monkeypatch.setattr(file_picker, 'BGMUSIC_DIR', library)
    monkeypatch.setattr(file_picker.sys, 'platform', 'darwin')
    calls = []
    results = iter([str(inside) + '\n', str(outside) + '\n', '\n'])
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=next(results))
    monkeypatch.setattr(file_picker.subprocess, 'run', run)
    assert file_picker.choose_local_path('bgmusic') == 'calm.mp3'
    assert file_picker.choose_local_path('bgmusic') == 'wild.wav' and (library / 'wild.wav').read_bytes() == b'b'
    assert file_picker.choose_local_path('bgmusic') is None
    assert all('default location' in cmd[2] and str(library) in cmd[2] for cmd in calls)


def test_server_exposes_bgmusic_picker(running_server, monkeypatch):
    calls = []
    def pick(kind):
        calls.append(kind); return 'calm.mp3'
    monkeypatch.setattr('video_harness.settings_ui.choose_local_path', pick)
    status, payload, _ = request(running_server, 'POST', '/api/pick-bgmusic', headers=api_headers(running_server))
    assert status == 200 and payload == {'path': 'calm.mp3', 'cancelled': False}
    assert calls == ['bgmusic']
