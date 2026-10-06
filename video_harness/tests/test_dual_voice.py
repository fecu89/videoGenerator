import pytest
from video_harness.settings import VoiceSettings, ArchivedVoiceSettings, ArchivedV4HarnessSettings, ArchivedV4VoiceSettings, HarnessSettings, settings_sha256
from video_harness.voice import create_synthesizer


def test_factory_routes_current_and_historical_qwen_without_loading_models():
    qwen = create_synthesizer(VoiceSettings(engine='qwen3'))
    assert type(qwen).__name__ == 'MLXAudioSynthesizer'
    assert qwen._model is None
    assert 'Sohee' == qwen.settings.speaker
    assert type(create_synthesizer(ArchivedVoiceSettings())).__name__ == 'MLXAudioSynthesizer'


def test_existing_vox_snapshot_hash_is_unchanged():
    import hashlib
    import json
    from video_harness.settings import QWEN_SETTING_FIELDS
    for style in ('natural', 'youtube_exuberant'):
        settings = ArchivedV4HarnessSettings(voice=ArchivedV4VoiceSettings(acting_style=style))
        old = settings.model_dump(mode='json')
        for key in QWEN_SETTING_FIELDS:
            old['voice'].pop(key)
        if style == 'natural':
            old['voice'].pop('acting_style')
        old['voice'].pop('max_tempo_factor')   # fixed 1.25 before it became a setting
        old['local_video'].pop('text_policy')   # legacy default is hash-excluded
        old['local_video'].pop('subtitle_languages')
        old['local_video'].pop('localized_delivery', None)
        old['local_video'].pop('camera_transition_seconds', None)
        old.pop('music', None)
        old.pop("pacing")
        old["local_video"].pop("target_beat_min_seconds")
        old["local_video"].pop("target_beat_max_seconds")
        encoded = json.dumps(old, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        assert settings_sha256(settings) == hashlib.sha256(encoded.encode()).hexdigest()


@pytest.mark.parametrize("version", [3, 4])
def test_historical_qwen_publishes_audio_without_migrating_snapshot(tmp_path, version):
    import json
    from video_harness.settings import ArchivedHarnessSettings, resolve_run_settings
    from video_harness.tests.test_voice import make_script, FakeSynthesizer
    from video_harness.voice import generate_audio
    script_path = tmp_path / 'script.json'
    from video_harness.tests.test_creative_gates import write_story
    story, review = write_story(tmp_path)
    script = make_script(1)
    script.scenes[0].narration = story['scenes'][0]['narration']
    script_path.write_text(script.model_dump_json())
    from video_harness.creative_gates import story_digest
    review["script_sha256"] = story_digest(script.model_dump(mode="json"))
    (tmp_path / "story-chain.json").write_text(json.dumps(review))
    original = (ArchivedHarnessSettings() if version == 3 else ArchivedV4HarnessSettings(voice={"engine": "qwen3"})).model_dump_json()
    snapshot = tmp_path / 'run-settings.json'
    snapshot.write_text(original)
    report = generate_audio(script_path, settings=resolve_run_settings(tmp_path),
                            synthesizer=FakeSynthesizer({1: 6.0}), duration_reader=lambda _: 6.0)
    assert report.invalid_scene_ids == []
    assert snapshot.read_text() == original
    entry = json.loads((tmp_path / 'voice-generation-report.json').read_text())['scenes'][0]
    assert entry['engine'] == 'qwen3'
    assert entry['speaker'] == 'Sohee'
    assert entry['global_instruction_sha256']
    assert entry['temperature'] == .5


def test_qwen_closes_model_and_runtime_after_failure(tmp_path):
    import pytest
    from video_harness.mlx_voice import MAX_SENTENCE_GENERATION_ATTEMPTS
    from video_harness.tests.test_mlx_voice import configured_synthesizer, FakeModel, make_scene, destinations
    synth, runtime, _ = configured_synthesizer(
        tmp_path, fake_model=FakeModel(token_counts=[10000] * MAX_SENTENCE_GENERATION_ATTEMPTS),
    )
    cleanups = []
    runtime.release_unused_memory = lambda: cleanups.append(synth._model is None)
    with pytest.raises(RuntimeError):
        with synth:
            synth.synthesize([make_scene(1, '별을 봅니다.')], destinations(tmp_path, 1))
    assert cleanups[-1] is True
    assert synth._model is None
    assert synth._runtime is None


def test_current_qwen_requires_complete_script_acting_before_loading_model(tmp_path):
    import pytest
    from video_harness.tests.test_voice import make_scene
    synth = create_synthesizer(VoiceSettings(engine='qwen3', emotion_mode='script_only'))
    with pytest.raises(ValueError, match='sentence_delivery missing'):
        synth.synthesize([make_scene(1)], {1: tmp_path/'unused.mp3'})
    assert synth._model is None
