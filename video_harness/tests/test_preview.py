import json
from pathlib import Path
import pytest
from video_harness.preview import representative_output_frames, transition_boundaries, render_preview
from video_harness.sequence_models import LocalSequencePlan


def plan():
    return LocalSequencePlan.model_validate({
        'schema_version': 1, 'script_sha256': 'a' * 64, 'production_plan_sha256': 'b' * 64,
        'defaults': {'width': 160, 'height': 90, 'fps': 10},
        'sequences': [{'sequence_id': 'SEQ01', 'scene_ids': [1], 'duration_frames': 60, 'render_mode': 'simulation',
            'scene_graph': 'shared-science-scene',
            'scene_spans': [{'scene_id': 1, 'start_frame': 0, 'end_frame': 60, 'audio_start_frame': 0, 'audio_end_frame': 60, 'tail_silence_frames': 0}],
            'timeline': [
                {'beat_id': 'B01', 'start_frame': 0, 'end_frame': 30, 'simulation_time_start': 0, 'simulation_time_end': 3, 'controller': 'c', 'patch_targets': ['geometry']},
                {'beat_id': 'B02', 'start_frame': 30, 'end_frame': 60, 'simulation_time_start': 3, 'simulation_time_end': 6, 'controller': 'c', 'patch_targets': ['geometry']}]}]})


def test_transition_boundaries_take_non_cut_to_beat_starts():
    continuity = {'transitions': [{'from_beat': 'B01', 'to_beat': 'B02', 'mode': 'continuous_3d'}]}
    assert transition_boundaries(plan(), continuity) == {'SEQ01': [30]}
    assert transition_boundaries(plan(), {'transitions': [{'from_beat': 'B01', 'to_beat': 'B02', 'mode': 'cut'}]}) == {'SEQ01': []}


def test_representative_frames_are_beat_centres_plus_boundary_window_in_output_frames():
    frames = representative_output_frames(plan().sequences[0], [30], canonical_fps=10, output_fps=10)
    assert frames == [15, 25, 30, 35, 45]
    frames_12 = representative_output_frames(plan().sequences[0], [30], canonical_fps=10, output_fps=12)
    assert frames_12 == [18, 30, 36, 42, 54]
    edge = representative_output_frames(plan().sequences[0], [0, 60], canonical_fps=10, output_fps=10)
    assert edge[0] == 0 and edge[-1] == 59


def _png_1x1() -> bytes:
    import struct, zlib
    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(b'\x00\x10\x20\x30')) + chunk(b'IEND', b'')


PNG_1x1 = _png_1x1()


class FakeBackend:
    version = 'fake-preview-v1'

    def __init__(self):
        self.jobs = []

    def check_dependencies(self):
        return None

    def render_frames(self, job, cache_dir):
        self.jobs.append(job)
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        frames = []
        samples = []
        for index in job['sample_frames']:
            path = Path(cache_dir) / f'frame-{index:06d}.png'
            path.write_bytes(PNG_1x1)
            frames.append(str(path))
            samples.append({'canonical_frame': index, 'simulation_time': index / 10, 'continuity': {'camera': {}, 'actors': {}, 'paths': {}},
                            'visible_layers': [], 'geometry_operation_keys': [], 'camera': {'position': [0, 0, 0], 'target': [0, 0, -1]},
                            'entity_scales': {}, 'state_fingerprint': 'x', 'callouts': []})
        report = Path(cache_dir) / 'frame-report.json'
        report.write_text(json.dumps({'sequence_id': job['sequence_id'], 'frame_count': len(frames), 'width': job['output']['width'],
            'height': job['output']['height'], 'frames': frames, 'sample_frames': job['sample_frames'], 'state_samples': samples,
            'backend': {'actual': 'fake'}}))
        return report


def test_render_preview_writes_frames_sheet_report_and_gate(tmp_path, monkeypatch):
    import video_harness.preview as module
    import video_harness.sequence_render as sequence_render
    from video_harness.settings import HarnessSettings
    from video_harness.tests.test_video_plan_approval import _write_reviewable_run
    _write_reviewable_run(tmp_path)
    (tmp_path / 'continuity-plan.json').write_text(json.dumps({'transitions': []}))
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'keywords'}}))
    monkeypatch.setattr(module, 'prepare_video_plan', lambda _run: None)
    monkeypatch.setattr(module, 'load_simulation', lambda *_a, **_k: None)
    monkeypatch.setattr(sequence_render, '_physics_payload', lambda _s: {})
    monkeypatch.setattr(sequence_render, '_style_payload', lambda _s: {})
    backend = FakeBackend()

    report = render_preview(tmp_path, settings=HarnessSettings(local_video={'text_policy': 'keywords'}), backend=backend)

    assert backend.jobs and backend.jobs[0]['sample_frames'] == report.sequences[0].sample_frames
    assert (tmp_path / 'preview-report.json').is_file()
    assert (tmp_path / report.contact_sheet_file).is_file()
    assert all((tmp_path / f).is_file() for f in report.sequences[0].frames)
    assert report.renderer_versions == {report.sequences[0].sequence_id: 'fake-preview-v1'}
    assert json.loads((tmp_path / 'text-preview-gate.json').read_text())['status'] == 'passed'
