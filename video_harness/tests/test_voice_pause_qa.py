"""Acoustic regressions: an exact transcript can still contain a wrong pause."""
import json
import subprocess

import numpy as np
import pytest


def policy(maximum=100, **voice_overrides):
    from video_harness.settings import HarnessSettings
    from video_harness.voice_pause_qa import PausePolicy
    return PausePolicy.from_settings(HarnessSettings(voice={
        'pause_mode': 'typed', 'max_internal_pause_ms': maximum, **voice_overrides}))


def test_configured_internal_pause_limit_replaces_any_universal_cutoff():
    from video_harness.voice_pause_qa import inspect_audio
    audio = np.r_[tone(.4), np.zeros(2640), tone(.5)]  # 110 ms
    assert inspect_audio(audio, 24000, policy=policy(120))['status'] == 'passed'
    assert inspect_audio(audio, 24000, policy=policy(80))['status'] == 'failed'


def test_encoded_pause_limit_uses_actual_tempo_without_speeding_planned_gaps():
    from video_harness.voice_pause_qa import inspect_audio
    audio = np.r_[tone(.4), np.zeros(2640), tone(.5)]
    assert inspect_audio(audio, 24000, policy=policy(120),
        speech_spans=[{'start_seconds': 0, 'end_seconds': 1.01, 'tempo_factor': 1}])['status'] == 'passed'
    assert inspect_audio(audio, 24000, policy=policy(120, max_tempo_factor=1.6),
        speech_spans=[{'start_seconds': 0, 'end_seconds': 1.01, 'tempo_factor': 1.5}])['status'] == 'failed'


def test_long_sentence_gap_selected_in_settings_is_allowed():
    from video_harness.voice_pause_qa import inspect_audio
    audio = np.r_[tone(.4), np.zeros(14400), tone(.5)]
    result = inspect_audio(audio, 24000, policy=policy(80, sentence_pause_ms=600),
        planned=[{'start_seconds': .4, 'duration_ms': 600, 'kind': 'sentence'}])
    assert result['status'] == 'passed'


def tone(seconds, rate=24000):
    return (.2 * np.sin(2 * np.pi * 220 * np.arange(round(seconds * rate)) / rate)).astype('float32')


@pytest.mark.parametrize('gap', [.12, .3])
def test_unplanned_pause_inside_second_energy_level_is_rejected(gap):
    from video_harness.voice_pause_qa import inspect_audio, PausePolicy
    audio = np.r_[tone(.4), np.zeros(round(24000 * gap)), tone(.5)]
    report = inspect_audio(audio, 24000, policy=policy())
    assert report['status'] == 'failed'
    assert report['issues'][0]['code'] == 'unexpected_pause'
    assert report['issues'][0]['start_seconds'] == pytest.approx(.4, abs=.02)
    assert report['issues'][0]['duration_ms'] == pytest.approx(gap*1000, abs=20)


def test_planned_comma_and_sentence_pauses_pass():
    from video_harness.voice_pause_qa import inspect_audio, PausePolicy
    audio = np.r_[tone(.4), np.zeros(2880), tone(.5), np.zeros(12000), tone(.4)]
    expected = [{'start_seconds': .4, 'duration_ms': 120, 'kind': 'comma'},
                {'start_seconds': 1.02, 'duration_ms': 500, 'kind': 'sentence'}]
    assert inspect_audio(audio, 24000, policy=policy(), planned=expected)['status'] == 'passed'


def test_longer_pause_at_a_planned_boundary_does_not_hide_behind_exemption():
    from video_harness.voice_pause_qa import inspect_audio, PausePolicy
    audio = np.r_[tone(.4), np.zeros(12000), tone(.5)]
    result = inspect_audio(audio, 24000, policy=policy(), planned=[
        {'start_seconds': .4, 'duration_ms': 120, 'kind': 'comma'}])
    assert result['status'] == 'failed'
    assert any(i['code'] == 'planned_pause_mismatch' for i in result['issues'])


def test_missing_planned_sentence_pause_fails():
    from video_harness.voice_pause_qa import inspect_audio, PausePolicy
    result = inspect_audio(tone(1.4), 24000, policy=policy(), planned=[
        {'start_seconds': .4, 'duration_ms': 500, 'kind': 'sentence'}])
    assert any(i['code'] == 'planned_pause_mismatch' for i in result['issues'])


def test_edges_short_consonant_closures_and_low_noise_are_handled():
    from video_harness.voice_pause_qa import inspect_audio, PausePolicy
    normal = np.r_[np.zeros(18000), tone(.4), np.zeros(1920), tone(.4), np.zeros(24000)]
    assert inspect_audio(normal, 24000, policy=policy())['status'] == 'passed'
    # A pause is rarely digital zero after encoding. A quiet noise floor must
    # not fool a per-sample zero-crossing detector.
    noisy_pause = np.random.default_rng(42).normal(0, .0002, 7200)
    assert inspect_audio(np.r_[tone(.4), noisy_pause, tone(.4)], 24000,
                         policy=policy())['status'] == 'failed'


@pytest.mark.parametrize('audio', [np.zeros(24000), np.array([np.nan]), np.array([])])
def test_unusable_audio_never_passes(audio):
    from video_harness.voice_pause_qa import inspect_audio, PausePolicy
    assert inspect_audio(audio, 24000, policy=policy())['status'] == 'failed'


def write_run(tmp_path, *, gap=.3):
    from video_harness.tests.test_voice import make_script
    from video_harness.voice_audio import read_mp3_duration
    script = make_script(1)
    scene = script.scenes[0]
    scene.narration = '두 번째 준위입니다.'
    scene.audio_file = 'audioFiles/01.mp3'
    path = tmp_path / scene.audio_file
    path.parent.mkdir(exist_ok=True)
    audio = np.r_[tone(.4), np.zeros(round(24000 * gap)), tone(.5), np.zeros(12000)].astype('<f4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', '24000', '-ac', '1',
                    '-i', '-', '-c:a', 'libmp3lame', str(path)], input=audio.tobytes(), check=True)
    scene.duration_seconds = read_mp3_duration(path)
    (tmp_path / 'script.json').write_text(script.model_dump_json())
    generation = {'schema_version': 1, 'scenes': [{'scene_id': 1, 'sentence_leading_margin_ms': 0,
        'sentence_trailing_margin_ms': 500, 'sentences': [{'text': scene.narration,
            'output_seconds': .9 + gap + .5, 'pause_events': []}]}]}
    (tmp_path / 'voice-generation-report.json').write_text(json.dumps(generation))
    from video_harness.settings import HarnessSettings
    settings = HarnessSettings(voice={'pause_mode': 'typed', 'max_internal_pause_ms': 100, 'min_scene_seconds': .1})
    (tmp_path / 'run-settings.json').write_text(settings.model_dump_json())
    return script, path


def test_cli_checks_existing_mp3_without_editing_it_and_invalidates_old_pass(tmp_path):
    from video_harness.voice_pause_qa import main, gate_issues
    script, path = write_run(tmp_path, gap=.08)
    original = path.read_bytes()
    assert main([str(tmp_path)]) == 0
    assert path.read_bytes() == original
    assert gate_issues(tmp_path, script) == []
    write_run(tmp_path, gap=.3)
    assert gate_issues(tmp_path, script)  # old pass cannot certify new bytes
    assert main([str(tmp_path)]) == 1
    report = json.loads((tmp_path / 'voice-pause-gate.json').read_text())
    assert report['status'] == 'failed'
    issue = report['scenes'][0]['issues'][0]
    assert issue['sentence_index'] == 1
    assert issue['text'] == '두 번째 준위입니다.'


def test_missing_or_stale_gate_blocks_only_opted_in_runs(tmp_path):
    from video_harness.voice_pause_qa import gate_issues, load_policy
    script, _ = write_run(tmp_path, gap=.08)
    assert gate_issues(tmp_path, script) == []  # existing runs retain compatibility
    load_policy(tmp_path, create=True)
    assert gate_issues(tmp_path, script)


def test_generation_report_timing_and_text_cannot_silently_change(tmp_path):
    from video_harness.voice_pause_qa import main, gate_issues
    script, _ = write_run(tmp_path, gap=.08)
    assert main([str(tmp_path)]) == 0
    report_path = tmp_path / 'voice-generation-report.json'
    generation = json.loads(report_path.read_text())
    generation['scenes'][0]['sentences'][0]['output_seconds'] += .3
    report_path.write_text(json.dumps(generation))
    assert gate_issues(tmp_path, script)


def test_settings_change_stales_gate_and_explicit_recheck_uses_new_snapshot(tmp_path):
    from video_harness.voice_pause_qa import main, gate_issues
    script, _ = write_run(tmp_path, gap=.08)
    assert main([str(tmp_path)]) == 0
    path = tmp_path/'run-settings.json'
    settings = json.loads(path.read_text())
    settings['voice']['max_internal_pause_ms'] = 120
    path.write_text(json.dumps(settings))
    saved = path.read_bytes()
    assert any('settings_stale' in issue for issue in gate_issues(tmp_path, script))
    assert main([str(tmp_path)]) == 0
    assert path.read_bytes() == saved
    assert gate_issues(tmp_path, script) == []


def test_missing_declared_comma_metadata_cannot_pass_as_an_unplanned_short_gap(tmp_path):
    from video_harness.voice_pause_qa import main
    script, _ = write_run(tmp_path, gap=.08)
    script.scenes[0].narration = '두 번째, 준위입니다.'
    (tmp_path/'script.json').write_text(script.model_dump_json())
    path = tmp_path/'voice-generation-report.json'
    generation = json.loads(path.read_text())
    generation['scenes'][0]['sentences'][0]['text'] = script.scenes[0].narration
    path.write_text(json.dumps(generation))
    assert main([str(tmp_path)]) == 1


def test_different_phrase_tempos_are_not_collapsed_to_sentence_maximum(tmp_path):
    from video_harness.voice_pause_qa import check_scene
    audio = np.r_[tone(.4), np.zeros(2640), tone(.5), np.zeros(3600), tone(.5), np.zeros(12000)].astype('<f4')
    path = tmp_path/'mixed.mp3'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', '24000', '-ac', '1',
        '-i', '-', '-c:a', 'libmp3lame', str(path)], input=audio.tobytes(), check=True)
    generation = {'sentence_leading_margin_ms': 0, 'sentence_trailing_margin_ms': 500,
        'sentences': [{'text': '두 번째 준위, 바닥 준위.', 'output_seconds': 2.16,
            'tempo_factor': 1.5,
            'pause_events': [{'kind': 'comma', 'start_seconds': 1.01, 'duration_ms': 150}],
            'phrase_spans': [
                {'text': '두 번째 준위', 'start_seconds': 0, 'end_seconds': 1.01, 'tempo_factor': 1},
                {'text': '바닥 준위.', 'start_seconds': 1.16, 'end_seconds': 1.66, 'tempo_factor': 1.5}]}]}
    result = check_scene(path, generation, '두 번째 준위, 바닥 준위.',
        policy(120, comma_pause_ms=150, max_tempo_factor=1.6))
    assert result['status'] == 'passed'


@pytest.mark.parametrize('gap,passes', [(.08, True), (.12, False)])
def test_voice_api_automatically_enrolls_typed_runs_and_checks_before_publication(tmp_path, monkeypatch, gap, passes):
    import dataclasses
    import shutil
    from video_harness.tests.test_voice import fake_generation
    from video_harness.voice import generate_audio
    from video_harness.voice_audio import AudioResult, read_mp3_duration
    from video_harness.settings import HarnessSettings
    from video_harness.models import ScriptArtifact
    from video_harness.voice_pause_qa import gate_issues
    # This test exercises actual MP3 inspection/publication; editorial approval
    # validation has independent fixtures and is unrelated to acoustic quality.
    monkeypatch.setattr('video_harness.creative_gates.require_story_chain', lambda _: None)
    script, source = write_run(tmp_path, gap=gap)
    before = (tmp_path / 'script.json').read_bytes()
    class Synthesizer:
        def synthesize(self, scenes, destinations):
            results = []
            for scene in scenes:
                path = destinations[scene.scene_id]
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, path)
                generation = fake_generation(scene)
                generation = dataclasses.replace(generation, sentence_leading_margin_ms=0,
                    sentence_trailing_margin_ms=500, sentences=(dataclasses.replace(
                        generation.sentences[0], output_seconds=1.4 + gap),))
                results.append(AudioResult(scene.scene_id, path, read_mp3_duration(path), generation))
            return results
    settings = HarnessSettings(voice={'pause_mode': 'typed', 'max_internal_pause_ms': 100, 'min_scene_seconds': .1})
    if passes:
        generate_audio(tmp_path/'script.json', settings=settings, synthesizer=Synthesizer())
        updated = ScriptArtifact.model_validate_json((tmp_path/'script.json').read_text())
        assert gate_issues(tmp_path, updated) == []
    else:
        with pytest.raises(RuntimeError, match='voice_pause_gate_failed'):
            generate_audio(tmp_path/'script.json', settings=settings, synthesizer=Synthesizer())
        assert (tmp_path/'script.json').read_bytes() == before
        assert not (tmp_path/'audioFiles/01_장면_1.mp3').exists()
        assert gate_issues(tmp_path, script)


def test_planning_and_render_preflight_reject_unverified_enrolled_audio(tmp_path):
    from video_harness.voice_pause_qa import load_policy
    from video_harness.migration import _require_audio_ready
    from video_harness.video_plan_approval import require_current_video_plan_approval
    from video_harness.sequence_render import render_sequence_quality
    from video_harness.creative_gates import require_legacy_render_gate
    script, _ = write_run(tmp_path, gap=.08)
    load_policy(tmp_path, create=True)
    with pytest.raises(ValueError, match='voice_pause_gate'):
        _require_audio_ready(tmp_path, script)
    with pytest.raises(ValueError, match='voice_pause_gate'):
        require_current_video_plan_approval(tmp_path)
    with pytest.raises(ValueError, match='voice_pause_gate'):
        render_sequence_quality(tmp_path, quality='draft')
    with pytest.raises(ValueError, match='voice_pause_gate'):
        require_legacy_render_gate(tmp_path, 'draft')


def test_deleting_policy_alone_cannot_bypass_a_failed_gate(tmp_path):
    from video_harness.voice_pause_qa import main, gate_issues
    script, _ = write_run(tmp_path, gap=.3)
    assert main([str(tmp_path)]) == 1
    (tmp_path/'voice-pause-policy.json').unlink()
    assert gate_issues(tmp_path, script)


def test_qwen_retries_bad_raw_pause_before_trimming_it(tmp_path):
    from types import SimpleNamespace
    from video_harness.tests.test_mlx_voice import FakeModel, configured_synthesizer
    from video_harness.settings import VoiceSettings
    from video_harness.voice_pause_qa import PausePolicy
    class Model(FakeModel):
        def generate_custom_voice(self, **kwargs):
            self.calls.append(kwargs)
            gap = .3 if len(self.calls) == 1 else .08
            yield SimpleNamespace(audio=np.r_[tone(.4), np.zeros(round(gap * 24000)), tone(.4)],
                                  sample_rate=24000, token_count=5)
    model = Model()
    synth, runtime, _ = configured_synthesizer(tmp_path, fake_model=model,
        voice_settings=VoiceSettings(pause_mode='typed', max_internal_pause_ms=50))
    synth.pause_policy = policy()
    _, _, report = synth._generate_sentence(model=model, runtime=runtime,
        sentence='두 번째 준위입니다.', instruction='', scene_id=1, sentence_index=1)
    assert report.attempt_count == 2


def test_persistent_bad_pause_fails_without_publishing(tmp_path):
    from types import SimpleNamespace
    from video_harness.tests.test_mlx_voice import FakeModel, configured_synthesizer
    from video_harness.settings import VoiceSettings
    from video_harness.models import Scene
    from video_harness.voice_pause_qa import PausePolicy
    class Model(FakeModel):
        def generate_custom_voice(self, **kwargs):
            yield SimpleNamespace(audio=np.r_[tone(.4), np.zeros(7200), tone(.4)],
                                  sample_rate=24000, token_count=5)
    synth, _, _ = configured_synthesizer(tmp_path, fake_model=Model(),
        voice_settings=VoiceSettings(pause_mode='typed', max_internal_pause_ms=50))
    synth.pause_policy = policy()
    dest = tmp_path / 'voice.mp3'
    dest.write_bytes(b'approved existing audio')
    scene = Scene(scene_id=1, title='t', narration='두 번째 준위입니다.', narrative_role='r', visual_subject='v')
    with pytest.raises(RuntimeError, match='unexpected_pause'):
        synth.synthesize([scene], {1: dest})
    assert dest.read_bytes() == b'approved existing audio'
