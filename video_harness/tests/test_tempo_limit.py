import pytest
from video_harness.settings import HarnessSettings, VoiceSettings, settings_sha256
from video_harness.voice_audio import SceneFitError, fit_scene_tempo, tempo_limit


def test_default_cap_is_the_old_fixed_value_and_keeps_hashes():
    assert VoiceSettings().max_tempo_factor == 1.25
    default = HarnessSettings()
    raised = HarnessSettings(voice=VoiceSettings(max_tempo_factor=1.4))
    assert settings_sha256(default) != settings_sha256(raised)


def test_scene_fit_uses_the_given_limit():
    assert fit_scene_tempo(13.0, 10.0, limit=1.4) == pytest.approx(1.3)
    with pytest.raises(SceneFitError, match='above 1.25'):
        fit_scene_tempo(13.0, 10.0)


def test_archived_settings_without_the_field_fall_back_to_125():
    class Archived:
        pass
    assert tempo_limit(Archived()) == 1.25


def test_cap_bounds():
    with pytest.raises(ValueError):
        VoiceSettings(max_tempo_factor=1.61)
    with pytest.raises(ValueError):
        VoiceSettings(max_tempo_factor=0.99)
