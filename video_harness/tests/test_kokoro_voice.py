import numpy as np
import pytest
from types import SimpleNamespace
from video_harness.models import Scene
from video_harness.settings import VoiceSettings
from video_harness.kokoro_voice import KokoroSynthesizer
from video_harness.tests.test_mlx_voice import FakeFFmpegRunner


class FakeKokoroModel:
    sample_rate = 1000

    def __init__(self):
        self.calls = []

    def generate(self, *, text, voice, lang_code, speed):
        self.calls.append((text, voice, lang_code, speed))
        # Two chunks per sentence: 0.5 s + 0.25 s
        yield SimpleNamespace(audio=np.full(500, 0.2, dtype=np.float32), sample_rate=self.sample_rate)
        yield SimpleNamespace(audio=np.full(250, 0.2, dtype=np.float32), sample_rate=self.sample_rate)


class FakeKokoroRuntime:
    def __init__(self, model, voices=('af_heart', 'jf_alpha')):
        self.model = model; self.voices = list(voices); self.loaded = []
    def load_model(self, model_id, **kwargs):
        self.loaded.append(model_id); return self.model
    def list_voices(self, model_id):
        return self.voices
    def release_unused_memory(self): pass
    def write_audio(self, path, audio, rate, fmt): path.write_bytes(b'wav')
    def seed(self, value): pass
    to_numpy = staticmethod(np.asarray)
    concatenate = staticmethod(np.concatenate)
    zeros = staticmethod(lambda n, dtype: np.zeros(n, dtype=dtype))
    all_finite = staticmethod(lambda a: bool(np.isfinite(a).all()))


def build(tmp_path, *, voice='af_heart', voices=('af_heart', 'jf_alpha')):
    model = FakeKokoroModel(); runtime = FakeKokoroRuntime(model, voices)
    synth = KokoroSynthesizer(VoiceSettings(), voice=voice, lang_code='a', model_id='mlx-community/Kokoro-82M-bf16',
                              runtime_loader=lambda: runtime, runner=FakeFFmpegRunner(),
                              command_locator=lambda n: f'/usr/bin/{n}', duration_reader=lambda p: 1.5)
    return synth, model, runtime


def test_kokoro_generates_sentences_with_preset_and_joins_chunks(tmp_path):
    synth, model, runtime = build(tmp_path)
    scene = Scene(scene_id=1, title='t', narration='Hello there. Second one.', narrative_role='r', visual_subject='v')
    results = synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    assert runtime.loaded == ['mlx-community/Kokoro-82M-bf16']
    assert [c[1:] for c in model.calls] == [('af_heart', 'a', 1.0)] * 2
    sentences = results[0].generation.sentences
    assert [s.sample_count for s in sentences] == [750, 750]
    assert {s.tempo_factor for s in sentences} == {1.0}
    assert sentences[0].spoken_units == 10


def test_kokoro_rejects_unknown_voice_preset_before_generating(tmp_path):
    synth, model, _ = build(tmp_path, voice='zz_nobody')
    scene = Scene(scene_id=1, title='t', narration='Hello.', narrative_role='r', visual_subject='v')
    with pytest.raises(RuntimeError, match='프리셋'):
        synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    assert model.calls == []


def test_create_synthesizer_kokoro_requires_language_voice():
    from video_harness.voice import create_synthesizer
    with pytest.raises(ValueError, match='language voice'):
        create_synthesizer(VoiceSettings(engine='kokoro'))


def test_kokoro_uses_pinned_local_snapshot_and_caps_internal_silence(tmp_path):
    snapshot = tmp_path / 'snap'; (snapshot / 'voices').mkdir(parents=True)
    (snapshot / 'voices' / 'af_heart.safetensors').write_bytes(b'v')
    calls = []
    class SnapModel(FakeKokoroModel):
        def generate(self, *, text, voice, lang_code, speed):
            calls.append(text)
            yield SimpleNamespace(audio=np.concatenate([np.full(200, 0.2, np.float32), np.zeros(900, np.float32), np.full(200, 0.2, np.float32)]), sample_rate=1000)
    class SnapRuntime(FakeKokoroRuntime):
        def __init__(self, model):
            super().__init__(model, voices=[]); self.snapshots = []
        def snapshot(self, model_id, revision):
            self.snapshots.append((model_id, revision)); return snapshot
    model = SnapModel(); runtime = SnapRuntime(model)
    synth = KokoroSynthesizer(VoiceSettings(max_internal_pause_ms=300), voice='af_heart', lang_code='a', model_id='mlx-community/Kokoro-82M-bf16',
                              revision='a71e4d38b236d968966a2002c4c895dbd12b1c3c', runtime_loader=lambda: runtime, runner=FakeFFmpegRunner(),
                              command_locator=lambda n: f'/usr/bin/{n}', duration_reader=lambda p: 1.0)
    scene = Scene(scene_id=1, title='t', narration='Hello there.', narrative_role='r', visual_subject='v')
    results = synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    assert runtime.snapshots == [('mlx-community/Kokoro-82M-bf16', 'a71e4d38b236d968966a2002c4c895dbd12b1c3c')]
    assert runtime.loaded == [str(snapshot)]
    assert results[0].generation.sentences[0].sample_count < 1300      # 0.9 s pause capped to 300 ms


def test_kokoro_configure_switches_language_without_reload(tmp_path):
    synth, model, runtime = build(tmp_path, voices=('af_heart', 'jf_alpha'))
    scene = Scene(scene_id=1, title='t', narration='Hello.', narrative_role='r', visual_subject='v')
    synth.synthesize([scene], {1: tmp_path / '01.mp3'})
    synth.configure(voice='jf_alpha', lang_code='j', scene_target_seconds={1: 9.0})
    synth.synthesize([scene], {1: tmp_path / '01b.mp3'}, )
    assert runtime.loaded == ['mlx-community/Kokoro-82M-bf16']
    assert [c[1:3] for c in model.calls] == [('af_heart', 'a'), ('jf_alpha', 'j')]
