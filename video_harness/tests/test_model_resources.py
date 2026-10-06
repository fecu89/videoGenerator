from contextlib import nullcontext
from dataclasses import replace

import pytest

from video_harness.settings import VoiceSettings
from video_harness.mlx_voice import MLXAudioSynthesizer
from video_harness.voice_audio import RuntimeBindings


def test_sentence_failure_and_context_exit_both_cleanup(tmp_path, monkeypatch, caplog):
    from video_harness.models import Scene
    calls=[]
    runtime=RuntimeBindings(lambda *a,**k:None,lambda *a:None,lambda s:None,
        lambda a:a,lambda a:a,lambda *a:None,lambda a:True,lambda:calls.append('cleanup'))
    synth=MLXAudioSynthesizer(VoiceSettings(),runtime_loader=lambda:runtime,command_locator=lambda _: '/ffmpeg')
    def load():
        synth._runtime=runtime
        synth._model=object()
        return runtime,synth._model
    monkeypatch.setattr(synth,'_load_model_runtime',load)
    def fail(**kwargs): raise RuntimeError('original inference failure')
    monkeypatch.setattr(synth,'_generate_sentence',fail)
    scene=Scene(scene_id=1,title='검사',narration='검사합니다.',narrative_role='HOOK',visual_subject='검사')
    with pytest.raises(RuntimeError,match='original inference failure'):
        with synth:
            synth.synthesize([scene],{1:tmp_path/'audio.mp3'})
    assert calls==['cleanup','cleanup']
    assert synth._model is None
    # Cleanup failures are reported without replacing the original exception.
    def broken_cleanup(): raise RuntimeError('cleanup failed')
    runtime=replace(runtime,release_unused_memory=broken_cleanup)
    with pytest.raises(RuntimeError,match='original inference failure'):
        with synth:
            synth.synthesize([scene],{1:tmp_path/'audio.mp3'})
    assert '모델 메모리 정리 실패' in caplog.text


@pytest.mark.parametrize('owned',[True,False])
@pytest.mark.parametrize('failure',[True,False])
def test_pipeline_closes_only_owned_models_even_on_failure(tmp_path,monkeypatch,owned,failure):
    from video_harness import voice
    from video_harness.tests.test_voice import FakeSynthesizer, make_script
    from video_harness.settings import HarnessSettings
    calls=[]
    class Tracked(FakeSynthesizer):
        def synthesize(self,*args,**kwargs):
            if failure: raise RuntimeError('inference failed')
            return super().synthesize(*args,**kwargs)
        def close(self): calls.append('close')
    synth=Tracked({1:6.0})
    # Editorial gates are covered separately; this test isolates model ownership.
    monkeypatch.setattr('video_harness.creative_gates.require_story_chain',lambda *a,**k:[])
    monkeypatch.setattr(voice,'create_synthesizer',lambda *a,**k:synth)
    script=tmp_path/'script.json'
    script.write_text(make_script(1).model_dump_json())
    context=pytest.raises(RuntimeError,match='inference failed') if failure else nullcontext()
    with context:
        voice.generate_audio(script,synthesizer=None if owned else synth,
                             duration_reader=lambda p:6.0,settings=HarnessSettings())
    assert calls==(['close'] if owned else [])
