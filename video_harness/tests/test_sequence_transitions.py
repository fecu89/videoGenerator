import json
from pathlib import Path

import pytest
from PIL import Image

from video_harness.sequence_transitions import apply_entry_transitions


def test_transition_preserves_timeline_and_updates_actual_frame_evidence(tmp_path):
    previous = tmp_path / 'previous.png'
    Image.new('RGB', (64, 36), 'red').save(previous)
    frames = []
    for i in range(12):
        path = tmp_path / f'frame-{i:06d}.png'
        Image.new('RGB', (64, 36), 'blue').save(path)
        frames.append(str(path))
    original = Path(frames[8]).read_bytes()
    report = tmp_path / 'frame-report.json'
    report.write_text(json.dumps(dict(frames=frames, state_samples=[dict(state_fingerprint='raw', geometry_operation_keys=['B1']) for _ in frames])))
    job = dict(canonical_fps=10, output=dict(fps=10), timeline=[dict(start_frame=0, end_frame=12, controller_options=dict(entry_transition=dict(style='fade', duration_seconds=.5)))])
    apply_entry_transitions(job, report, previous_frame=previous)
    data = json.loads(report.read_text())
    assert len(data['frames']) == 12
    assert Image.open(frames[0]).getpixel((32, 18))[0] > 240
    middle = Image.open(frames[2]).getpixel((32, 18))
    assert middle[0] > 60 and middle[2] > 60
    assert Image.open(frames[4]).getpixel((32, 18))[2] > 240
    assert Path(frames[8]).read_bytes() == original
    assert data['state_samples'][0]['state_fingerprint'] != 'raw'
    assert data['state_samples'][8]['state_fingerprint'] == 'raw'
    assert 'editorial_transition:fade' in data['state_samples'][2]['geometry_operation_keys']


def test_no_transition_is_noop(tmp_path):
    report = tmp_path / 'frame-report.json'
    report.write_text('{}')
    apply_entry_transitions(dict(timeline=[]), report)
    assert report.read_text() == '{}'


def test_unknown_transition_rejected_before_frame_mutation(tmp_path):
    report = tmp_path / 'frame-report.json'
    report.write_text('{}')
    with pytest.raises(ValueError, match='unsupported'):
        apply_entry_transitions(dict(timeline=[dict(controller_options=dict(entry_transition=dict(style='unknown', duration_seconds=.5)))]), report)


@pytest.mark.parametrize('style', ['smoothleft', 'smoothup', 'circleopen', 'zoomin'])
def test_internal_scene_transition_uses_previous_frame_at_draft_fps(tmp_path, style):
    frames = []
    for i in range(16):
        path = tmp_path / f'frame-{i:06d}.png'
        Image.new('RGB', (64, 36), 'red' if i < 4 else 'blue').save(path)
        frames.append(str(path))
    report = tmp_path / 'frame-report.json'
    report.write_text(json.dumps(dict(frames=frames, state_samples=[dict(state_fingerprint='raw', geometry_operation_keys=[]) for _ in frames])))
    job = dict(canonical_fps=30, output=dict(fps=12), timeline=[dict(start_frame=10, end_frame=40,
        controller_options=dict(entry_transition=dict(style=style, duration_seconds=.45)))])
    untouched = [Path(p).read_bytes() for p in frames]
    apply_entry_transitions(job, report)
    data = json.loads(report.read_text())
    assert len(data['frames']) == 16
    assert Image.open(frames[4]).getpixel((32, 18))[0] > 240
    assert Image.open(frames[9]).getpixel((32, 18))[2] > 240
    assert all(Path(frames[i]).read_bytes() == untouched[i] for i in [0,1,2,3,10,11,12,13,14,15])
    assert all(data['state_samples'][i]['state_fingerprint'] != 'raw' for i in range(4,10))
