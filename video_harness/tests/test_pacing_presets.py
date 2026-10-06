import json

import pytest

from video_harness.settings import ArchivedV5HarnessSettings, HarnessSettings, resolve_run_settings, settings_sha256
from video_harness.pacing_presets import apply_pacing_preset, pacing_status, pacing_warnings


@pytest.mark.parametrize('preset,target,gap,beat,fade', [
    ('calm', 5.2, .3, (5, 8), .8),
    ('standard', 5.8, .15, (3, 5), .5),
    ('shorts', 6.5, 0, (2, 4), .3),
])
def test_preset_coordinates_pacing_and_preserves_independent_choices(preset, target, gap, beat, fade):
    original = HarnessSettings()
    settings = apply_pacing_preset(original, preset)
    assert settings.voice.target_syllables_per_second == target
    assert settings.local_video.scene_gap_seconds == gap
    assert (settings.local_video.target_beat_min_seconds, settings.local_video.target_beat_max_seconds) == beat
    assert settings.music.fade_seconds == fade
    assert settings.voice.max_scene_seconds + gap < settings.local_video.max_scene_seconds
    assert settings.render == original.render
    assert settings.pipeline == original.pipeline
    assert settings.voice.model_id == original.voice.model_id
    assert settings.voice.instructions_file == original.voice.instructions_file
    assert settings.voice.emotion_mode == original.voice.emotion_mode
    assert settings.music.file == original.music.file
    assert original.pacing.preset == 'custom'
    assert pacing_status(settings)['customized'] is False


def test_customization_tracks_only_preset_fields_and_survives_snapshot(tmp_path):
    settings = apply_pacing_preset(HarnessSettings(), 'shorts')
    payload = settings.model_dump()
    payload['music']['file'] = 'chosen.mp3'
    assert not pacing_status(HarnessSettings.model_validate(payload))['customized']
    payload['local_video']['camera_transition_seconds'] = .6
    settings = HarnessSettings.model_validate(payload)
    assert pacing_status(settings) == {'preset': 'shorts', 'version': 2, 'label': '쇼츠 템포', 'customized': True}
    path = tmp_path / 'run-settings.json'
    path.write_text(settings.model_dump_json())
    assert resolve_run_settings(tmp_path) == settings


def test_old_v5_snapshot_hash_and_bytes_stay_unchanged(tmp_path):
    payload = ArchivedV5HarnessSettings().model_dump()
    payload.pop('pacing')
    payload['local_video'].pop('target_beat_min_seconds')
    payload['local_video'].pop('target_beat_max_seconds')
    path = tmp_path / 'run-settings.json'
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    restored = resolve_run_settings(tmp_path)
    assert restored.pacing.preset == 'custom'
    assert settings_sha256(restored) == 'edc13165a23486886befbdd244af025b975313aaa8b9a9162e89100e684a2623'
    assert path.read_bytes() == before


def test_beat_advice_is_optional_and_reports_long_shots():
    from types import SimpleNamespace as NS
    local = NS(defaults=NS(fps=30), sequences=[NS(sequence_id='SEQ01', timeline=[NS(beat_id='B01',start_frame=0,end_frame=300)])])
    assert not pacing_warnings(local, HarnessSettings())
    warnings = pacing_warnings(local, apply_pacing_preset(HarnessSettings(), 'shorts'))
    assert len(warnings) == 1 and 'B01' in warnings[0] and '10.0' in warnings[0]


def test_reject_unknown_preset_and_invalid_beat_range():
    with pytest.raises(ValueError):
        apply_pacing_preset(HarnessSettings(), 'fastest')
    payload = apply_pacing_preset(HarnessSettings(), 'shorts').model_dump()
    payload['local_video']['target_beat_min_seconds'] = 6
    with pytest.raises(ValueError):
        HarnessSettings.model_validate(payload)


def test_cli_preview_save_and_existing_run_guard(monkeypatch, tmp_path, capsys):
    import video_harness.settings as settings_module
    from video_harness.settings_cli import main
    path = tmp_path / 'settings.json'
    settings_module.write_project_settings(HarnessSettings(), path)
    monkeypatch.setattr(settings_module, 'PROJECT_SETTINGS_FILE', path)
    original = path.read_bytes()
    assert main(['--preset', 'calm']) == 0
    assert json.loads(capsys.readouterr().out)['settings']['voice']['max_scene_seconds'] == 16
    assert path.read_bytes() == original
    assert main(['--preset', 'shorts', '--save']) == 0
    capsys.readouterr()
    assert settings_module.load_project_settings(path).pacing.preset == 'shorts'
    with pytest.raises(SystemExit):
        main([str(tmp_path), '--preset', 'calm', '--save'])
    assert not (tmp_path / 'run-settings.json').exists()


def test_plan_review_and_render_job_use_run_snapshot_not_project(tmp_path):
    from types import SimpleNamespace as NS
    from video_harness.settings import write_settings_snapshot
    from video_harness.pacing_presets import render_pacing_review, render_pacing_values
    from video_harness.tests.test_camera_transition_setting import sequence, Sim
    from video_harness.sequence_render import build_sequence_job
    settings = apply_pacing_preset(HarnessSettings(), 'calm')
    write_settings_snapshot(tmp_path, settings)
    local = NS(defaults=NS(fps=30), sequences=[sequence()])
    review = render_pacing_review(tmp_path, local)
    assert '차분한 설명' in review and '5–8초' in review
    assert 'SEQ01/B01' in review  # two-second beat is short for calm pacing
    job = build_sequence_job(sequence(), width=64, height=36, output_fps=30, canonical_fps=30,
                             cache_dir=tmp_path, simulation=Sim(), pacing=render_pacing_values(settings))
    assert job['pacing']['target_beat_max_seconds'] == 8
    assert job['camera_transition_seconds'] == .7
    shorts = apply_pacing_preset(settings, 'shorts')
    job = build_sequence_job(sequence(), width=64, height=36, output_fps=30, canonical_fps=30,
                             cache_dir=tmp_path, simulation=Sim(), pacing=render_pacing_values(shorts))
    assert job['camera_transition_seconds'] == .35  # explicit even though legacy default was omitted
    assert render_pacing_values(HarnessSettings()) is None


def test_long_physical_process_reason_is_visible_in_pacing_review():
    from types import SimpleNamespace as NS
    beat = NS(beat_id='B01', start_frame=0, end_frame=300,
              controller_options={'pacing_exception_reason': '감속 파동이 뒤차까지 전파되는 과정'})
    local = NS(defaults=NS(fps=30), sequences=[NS(sequence_id='SEQ01', timeline=[beat])])
    assert '감속 파동' in pacing_warnings(local, apply_pacing_preset(HarnessSettings(), 'shorts'))[0]


def test_gallery_transition_uses_preset_duration_and_preserves_legacy_motion():
    from video_harness.blender_renderer.spectra import camera_transition_progress
    legacy = {'camera_transition_seconds': .35}
    shorts = {'pacing': {'preset': 'shorts'}, 'camera_transition_seconds': .35}
    calm = {'pacing': {'preset': 'calm'}, 'camera_transition_seconds': .7}
    assert camera_transition_progress(shorts, .35) == 1
    assert camera_transition_progress(calm, .35) == pytest.approx(.5)
    assert camera_transition_progress(legacy, .35) < .5
    assert camera_transition_progress(legacy, .75) == 1
    assert camera_transition_progress({**shorts, 'camera_transition_seconds': 0}, 0) == 1
