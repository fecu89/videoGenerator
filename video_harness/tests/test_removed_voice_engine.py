from pathlib import Path

import pytest
from pydantic import ValidationError

from video_harness.settings import VoiceSettings, resolve_run_settings, settings_sha256
from video_harness.voice import build_parser, create_synthesizer, generate_audio


def test_new_voice_defaults_to_qwen_without_removed_controls():
    settings = VoiceSettings()
    assert type(create_synthesizer(settings)).__name__ == 'MLXAudioSynthesizer'
    with pytest.raises(ValidationError):
        VoiceSettings(engine='voxcpm2')
    for field in ('voxcpm_cfg', 'acting_style', 'speed_mode'):
        with pytest.raises(ValidationError):
            VoiceSettings(**{field: 1})


@pytest.mark.parametrize('args', [
    ['--engine', 'voxcpm2'], ['--voxcpm-model-id', 'OpenBMB/VoxCPM2'],
    ['--speed-mode', 'manual'],
])
def test_cli_rejects_removed_engine_before_generation(args):
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(['script.json', *args])
    assert error.value.code == 2


@pytest.mark.parametrize('engine,digest', [
    ('qwen3', '35518ecd4b1db409604b9c3563bab16e340cc2afe0a0449a1c9119ca725d8a06'),
    ('voxcpm2', '6bc81d654f21603ee10a56368317c766ba66d1aced456dd8075f91fea90ba19b'),
])
def test_v4_snapshots_keep_bytes_and_approval_hash(tmp_path, engine, digest):
    raw = (Path(__file__).parent / 'fixtures' / f'archived-v4-{engine}.json').read_bytes()
    snapshot = tmp_path / 'run-settings.json'
    snapshot.write_bytes(raw)
    settings = resolve_run_settings(tmp_path)
    assert settings_sha256(settings) == digest
    assert snapshot.read_bytes() == raw
    if engine == 'qwen3':
        assert type(create_synthesizer(settings.voice)).__name__ == 'MLXAudioSynthesizer'
    else:
        with pytest.raises(ValueError, match='removed|제거'):
            create_synthesizer(settings.voice)
        with pytest.raises(RuntimeError, match='removed|제거'):
            generate_audio(tmp_path / 'script.json', settings=settings)
