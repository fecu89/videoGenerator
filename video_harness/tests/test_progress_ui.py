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
