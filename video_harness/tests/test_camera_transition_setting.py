import pytest
from video_harness.settings import CAMERA_TRANSITION_DEFAULT, HarnessSettings, LocalVideoSettings, settings_sha256
from video_harness.sequence_models import LocalSequence
from video_harness.sequence_render import build_sequence_job


def sequence():
    return LocalSequence.model_validate(dict(
        sequence_id='SEQ01', scene_ids=[1], duration_frames=60, render_mode='simulation', scene_graph='any',
        scene_spans=[dict(scene_id=1, start_frame=0, end_frame=60, audio_start_frame=0, audio_end_frame=60,
                          tail_silence_frames=0)],
        timeline=[dict(beat_id='B01', start_frame=0, end_frame=60, simulation_time_start=0.0,
                       simulation_time_end=2.0, controller='any', patch_targets=['camera'])]))


class Sim:
    preset = 'stellar-spectra-blender'

    class physics:
        @staticmethod
        def model_dump(mode):
            return {}

    style = physics


def job(value, tmp_path):
    return build_sequence_job(sequence(), width=64, height=36, output_fps=30, canonical_fps=30,
                              cache_dir=tmp_path, simulation=Sim(), camera_transition_seconds=value)


def test_default_is_advisory_and_keeps_hashes():
    assert LocalVideoSettings().camera_transition_seconds == CAMERA_TRANSITION_DEFAULT == 0.35
    default = HarnessSettings()
    slower = HarnessSettings(local_video=LocalVideoSettings(camera_transition_seconds=0.8))
    assert settings_sha256(default) != settings_sha256(slower)


def test_job_carries_only_a_non_default_value(tmp_path):
    assert 'camera_transition_seconds' not in job(None, tmp_path)
    assert 'camera_transition_seconds' not in job(0.35, tmp_path)
    assert job(0.6, tmp_path)['camera_transition_seconds'] == 0.6


def test_bounds():
    with pytest.raises(ValueError):
        LocalVideoSettings(camera_transition_seconds=3.01)
    with pytest.raises(ValueError):
        LocalVideoSettings(camera_transition_seconds=-0.1)
