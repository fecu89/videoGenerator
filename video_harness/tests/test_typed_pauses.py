import numpy as np
import pytest
from pydantic import ValidationError
from video_harness.models import Scene
from video_harness.settings import VoiceSettings
from video_harness.voice_pauses import sentence_phrases


def scene(text, pauses=()):
    return Scene(scene_id=1, title='t', narration=text, narrative_role='r', visual_subject='v', sentence_pauses=list(pauses))


def test_comma_semantic_emphasis_and_sentence_pauses():
    s = scene('빛은, 안개를 통과하며 점점 약해집니다.', [
        {'sentence_index': 1, 'after': '통과하며', 'kind': 'semantic'},
        {'sentence_index': 1, 'after': '점점', 'kind': 'emphasis'},
    ])
    parts = sentence_phrases(s.narration, s.sentence_pauses, VoiceSettings(pause_mode='typed'))
    assert [(p.text, p.pause_ms) for p in parts] == [('빛은', 120), ('안개를 통과하며', 200), ('점점', 350), ('약해집니다.', 500)]


def test_numeric_commas_are_not_phrase_boundaries():
    parts = sentence_phrases('1,000개, 또는 2,500개입니다.', [], VoiceSettings(pause_mode='typed'))
    assert [p.text for p in parts] == ['1,000개', '또는 2,500개입니다.']


@pytest.mark.parametrize('after', ['없는말', '빛', '끝입니다.'])
def test_ambiguous_missing_and_terminal_cues_are_rejected(after):
    with pytest.raises(ValidationError):
        scene('빛과 빛이 끝입니다.', [{'sentence_index': 1, 'after': after, 'kind': 'emphasis'}])


def test_explicit_cue_overrides_comma_without_duplicate_silence():
    s = scene('빛은, 약해집니다.', [{'sentence_index': 1, 'after': '빛은', 'kind': 'emphasis'}])
    assert [p.pause_ms for p in sentence_phrases(s.narration, s.sentence_pauses, VoiceSettings(pause_mode='typed'))] == [350, 500]


def test_typed_pauses_survive_tempo_and_keep_sentence_reports(tmp_path):
    from video_harness.tests.test_kokoro_voice import FakeKokoroModel, FakeKokoroRuntime
    from video_harness.tests.test_mlx_voice import FakeFFmpegRunner
    from video_harness.kokoro_voice import KokoroSynthesizer
    model = FakeKokoroModel(); runtime = FakeKokoroRuntime(model); runner = FakeFFmpegRunner()
    synth = KokoroSynthesizer(VoiceSettings(pause_mode='typed', max_internal_pause_ms=50),
        voice='af_heart', lang_code='a', model_id='fake', runtime_loader=lambda: runtime,
        runner=runner, command_locator=lambda n:n, duration_reader=lambda p:3.3,
        scene_target_seconds={1:3.3})
    s = scene('Light, gets weaker. Look.', [{'sentence_index':1, 'after':'Light', 'kind':'emphasis'}])
    result = synth.synthesize([s], {1:tmp_path/'voice.mp3'})[0]
    assert [c[0] for c in model.calls] == ['Light', 'gets weaker.', 'Look.']
    assert len(result.generation.sentences) == 2
    assert result.generation.sentence_gap_milliseconds == 500
    first = result.generation.sentences[0]
    assert first.text == 'Light, gets weaker.'
    assert first.pause_events[0]['duration_ms'] == 350
    graph = next(c[c.index('-filter_complex')+1] for c in runner.commands if '-filter_complex' in c)
    assert 'apad=pad_dur=0.350' in graph and 'apad=pad_dur=0.500' in graph
    assert graph.index('atempo=') < graph.index('apad=')
    assert sum(r.output_seconds for r in result.generation.sentences) <= 3.3 + 1e-6


def test_real_encoder_keeps_pause_lengths_after_speedup(tmp_path):
    import subprocess
    import wave
    from types import SimpleNamespace
    from video_harness.tests.test_kokoro_voice import FakeKokoroRuntime
    from video_harness.kokoro_voice import KokoroSynthesizer
    from video_harness.voice_audio import read_mp3_duration
    class Model:
        def generate(self, **kwargs):
            rate = 24000
            tone = (0.2 * np.sin(2 * np.pi * 220 * np.arange(rate * 3 // 4) / rate)).astype(np.float32)
            yield SimpleNamespace(audio=tone, sample_rate=rate)
    runtime = FakeKokoroRuntime(Model())
    def write_audio(path, data, rate, fmt):
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
            output.writeframes((np.asarray(data) * 32767).astype('<i2').tobytes())
    runtime.write_audio = write_audio
    synth = KokoroSynthesizer(VoiceSettings(pause_mode='typed', loudness_mode='off', max_internal_pause_ms=50),
        voice='af_heart', lang_code='a', model_id='fake', runtime_loader=lambda: runtime,
        duration_reader=read_mp3_duration, scene_target_seconds={1:3.3})
    s = scene('Light, gets weaker. Look.', [{'sentence_index':1, 'after':'Light', 'kind':'emphasis'}])
    dest = tmp_path/'voice.mp3'; result = synth.synthesize([s], {1:dest})[0]
    raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(dest),'-f','f32le','-ac','1','-ar','24000','-'])
    audio = np.frombuffer(raw, dtype='<f4')
    quiet = np.abs(audio) < .003
    edges = np.diff(np.r_[False, quiet, False].astype(int))
    spans = [(end-start)/24 for start,end in zip(np.where(edges==1)[0],np.where(edges==-1)[0]) if end-start > 2400]
    assert spans == pytest.approx([350,500,500], abs=25)
    assert len(result.generation.sentences) == 2


def test_legacy_snapshot_hash_is_unchanged_and_typed_mode_changes_it():
    from video_harness.settings import HarnessSettings, settings_sha256
    assert settings_sha256(HarnessSettings()) == '1a83ee8dc1f349f8ab1896a10544c3899267397a7e12bd5a2bb6c5ad49753dfc'
    assert settings_sha256(HarnessSettings(voice={'pause_mode':'typed'})) != settings_sha256(HarnessSettings())


def test_qwen_uses_typed_phrases_without_speaking_annotations(tmp_path):
    from video_harness.tests.test_mlx_voice import FakeModel, configured_synthesizer
    model = FakeModel(samples_per_call=300, audio_value=.2)
    synth, runtime, runner = configured_synthesizer(tmp_path, fake_model=model,
        voice_settings=VoiceSettings(pause_mode='typed', max_internal_pause_ms=50))
    s = scene('빛은, 안개를 지나며 약해집니다.', [{'sentence_index':1,'after':'지나며','kind':'emphasis'}])
    result = synth.synthesize([s], {1:tmp_path/'voice.mp3'})[0]
    from itertools import groupby
    # Qwen may retry a short phrase under its existing duration/token gates.
    assert [text for text, _ in groupby(call['text'] for call in model.calls)] == ['빛은', '안개를 지나며', '약해집니다.']
    assert [e['duration_ms'] for e in result.generation.sentences[0].pause_events] == [120,350]
