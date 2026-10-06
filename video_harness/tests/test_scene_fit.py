from pathlib import Path
import numpy as np
import pytest
from video_harness.models import Scene
from video_harness.narration import split_narration_sentences
from video_harness.settings import VoiceSettings
from video_harness.voice_audio import (AudioSynthesizer, SceneFitError, SentenceGeneration, fit_scene_tempo,
    spoken_unit_count, MAX_TEMPO_FACTOR)
from video_harness.tests.test_mlx_voice import FakeRuntime, FakeFFmpegRunner, FakeModel


def test_split_handles_cjk_terminators_without_spaces():
    assert split_narration_sentences('这里有风。它从不停止！为什么？') == ['这里有风。', '它从不停止！', '为什么？']
    assert split_narration_sentences('ここに風があります。止まりません。') == ['ここに風があります。', '止まりません。']
    assert split_narration_sentences('첫 문장입니다. 둘째? 셋째!') == ['첫 문장입니다.', '둘째?', '셋째!']


def test_spoken_units_count_cjk_and_kana():
    assert spoken_unit_count('这里有风。') == 4
    assert spoken_unit_count('ここに風') == 4
    assert spoken_unit_count('Hello, world!') == 10
    assert spoken_unit_count('바람 200 km') == 7


def test_fit_scene_tempo_clamps_and_raises():
    assert fit_scene_tempo(10.0, 8.0) == pytest.approx(1.25)
    assert fit_scene_tempo(9.0, 8.0) == pytest.approx(1.125)
    assert fit_scene_tempo(6.0, 8.0) == 1.0          # never slow down below natural pace
    with pytest.raises(SceneFitError) as info:
        fit_scene_tempo(10.5, 8.0)
    assert info.value.ratio == pytest.approx(1.3125)
    assert MAX_TEMPO_FACTOR == 1.25


class UnitSynthesizer(AudioSynthesizer):
    """Each sentence is exactly `seconds_per_sentence` of audio at the fake model rate (1 kHz), tempo 1.0."""
    seconds_per_sentence = 3.0

    def _load_model_runtime(self):
        if self._runtime is None:
            self._runtime = self.runtime_loader()
        return self._runtime, object()

    def effective_instruction(self, delivery):
        return ''

    def _generate_sentence(self, *, model, runtime, sentence, instruction, scene_id, sentence_index):
        rate = 1000
        audio = np.full(int(rate * self.seconds_per_sentence), 0.1, dtype=np.float32)
        return audio, rate, SentenceGeneration(text=sentence, seed=0, instruction_sha256='0' * 64, sample_count=len(audio),
                                               token_count=None, processing_time_seconds=None, peak_memory_usage=None,
                                               spoken_units=spoken_unit_count(sentence), tempo_factor=1.0)


def build(tmp_path, *, targets, runner=None):
    runner = runner or FakeFFmpegRunner()
    runtime = FakeRuntime(FakeModel())
    synth = UnitSynthesizer(VoiceSettings(max_scene_seconds=14.0), runtime_loader=lambda: runtime, runner=runner,
                            command_locator=lambda name: f'/usr/bin/{name}', duration_reader=lambda p: 6.0,
                            scene_target_seconds=targets)
    return synth, runner


def test_synthesizer_applies_uniform_scene_tempo(tmp_path):
    scene = Scene(scene_id=1, title='t', narration='One sentence. Two sentence.', narrative_role='r', visual_subject='v')
    synth, runner = build(tmp_path, targets={1: 7.1})      # speech 6.0 s, margins 2×1.05 s → available 5.0 s → tempo 1.2
    results = synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    assert all(s.tempo_factor == pytest.approx(1.2) for s in results[0].generation.sentences)
    joined = ' '.join(runner.commands[-1])
    assert joined.count('atempo=1.200000000') == 2


def test_synthesizer_keeps_natural_pace_when_shorter_than_target(tmp_path):
    scene = Scene(scene_id=1, title='t', narration='One sentence. Two sentence.', narrative_role='r', visual_subject='v')
    synth, runner = build(tmp_path, targets={1: 9.0})
    results = synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    assert {s.tempo_factor for s in results[0].generation.sentences} == {1.0}


def test_synthesizer_raises_scene_fit_error_when_too_long(tmp_path):
    scene = Scene(scene_id=1, title='t', narration='One sentence. Two sentence.', narrative_role='r', visual_subject='v')
    synth, _ = build(tmp_path, targets={1: 4.0})           # available 1.9 s → 6.0/1.9 ≈ 3.16
    with pytest.raises(SceneFitError) as info:
        synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    assert info.value.scene_id == 1 and info.value.ratio == pytest.approx(6.0 / 1.9)


class PaddedSynthesizer(UnitSynthesizer):
    """0.1 s silence + 3.0 s tone + 0.3 s silence per sentence at 1 kHz, like a real model."""

    def _generate_sentence(self, *, model, runtime, sentence, instruction, scene_id, sentence_index):
        rate = 1000
        audio = np.concatenate([np.zeros(100, np.float32), np.full(3000, 0.3, np.float32), np.zeros(300, np.float32)])
        return audio, rate, SentenceGeneration(text=sentence, seed=0, instruction_sha256='0' * 64, sample_count=len(audio),
                                               token_count=None, processing_time_seconds=None, peak_memory_usage=None,
                                               spoken_units=spoken_unit_count(sentence), tempo_factor=1.0)


def build_padded(tmp_path, *, targets):
    runner = FakeFFmpegRunner(); runtime = FakeRuntime(FakeModel())
    synth = PaddedSynthesizer(VoiceSettings(max_scene_seconds=14.0), runtime_loader=lambda: runtime, runner=runner,
                              command_locator=lambda name: f'/usr/bin/{name}', duration_reader=lambda p: 6.0,
                              scene_target_seconds=targets)
    return synth, runner


def test_fit_accounts_for_fixed_margins_and_audible_speech(tmp_path):
    # Two sentences: audible 6.0 s total; margins 100+950 ms each are fixed, so the slot must hold 2×1.05 s + speech/tempo.
    scene = Scene(scene_id=1, title='t', narration='One sentence. Two sentence.', narrative_role='r', visual_subject='v')
    synth, _ = build_padded(tmp_path, targets={1: 7.0})     # available 4.9 s → tempo 6.0/4.9 ≈ 1.2245
    results = synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    sentences = results[0].generation.sentences
    assert all(s.tempo_factor == pytest.approx(6.0 / 4.9, rel=1e-3) for s in sentences)
    assert all(s.output_seconds == pytest.approx(3.0 / (6.0 / 4.9) + 1.05, rel=1e-3) for s in sentences)
    assert sum(s.output_seconds for s in sentences) <= 7.0 + 1e-6
    synth, _ = build_padded(tmp_path, targets={1: 6.8})     # available 4.7 s → 1.277 > 1.25
    with pytest.raises(SceneFitError):
        synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    synth, _ = build_padded(tmp_path, targets={1: 2.0})     # margins alone exceed the slot
    with pytest.raises(SceneFitError):
        synth.synthesize([scene], {1: tmp_path / '01.mp3'})


def test_mlx_sentence_tempo_rejection_is_deferred_to_scene_fit():
    source = Path(__file__).resolve().parents[1].joinpath('mlx_voice.py').read_text(encoding='utf-8')
    assert 'scene_target_seconds' in source and 'not self.scene_target_seconds' in source


def test_encoded_overflow_re_solves_the_tempo_instead_of_failing(tmp_path, monkeypatch):
    # The first tempo fits audible speech; if the encoded sentences still overflow the
    # slot (here: 0.2 s of extra speech-rate audio each), the fit re-solves the tempo.
    import video_harness.voice_audio as va
    original = va.normalize_sentence_edges

    def longer(audio, **kwargs):
        out = original(audio, **kwargs)
        extra = np.full(200, 0.3, dtype=out.dtype)
        return np.concatenate([out, extra])

    monkeypatch.setattr(va, 'normalize_sentence_edges', longer)
    scene = Scene(scene_id=1, title='t', narration='One sentence. Two sentence.', narrative_role='r', visual_subject='v')
    synth, _ = build_padded(tmp_path, targets={1: 8.1})     # audible speech alone fits at natural pace
    results = synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    sentences = results[0].generation.sentences
    assert sum(s.output_seconds for s in sentences) <= 8.1 + 1e-6
    assert 1.0 < sentences[0].tempo_factor <= MAX_TEMPO_FACTOR


def test_scene_fit_error_reports_output_and_slot_lengths():
    error = SceneFitError(20, 1.31, output_seconds=12.9, slot_seconds=12.672)
    assert '12.900s > slot 12.672s' in str(error)
