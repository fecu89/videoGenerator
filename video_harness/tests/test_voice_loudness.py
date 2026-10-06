"""The real FFmpeg graph must level speech without moving sentence timing."""
import subprocess
from types import SimpleNamespace
import numpy as np
import soundfile as sf
from video_harness.settings import VoiceSettings
from video_harness.mlx_voice import MLXAudioSynthesizer
from video_harness.voice_audio import RuntimeBindings
from video_harness.models import Scene


def test_leveling_reduces_sentence_volume_jump_without_changing_duration(tmp_path):
    class Model:
        def get_supported_speakers(self): return ["Sohee"]
        def get_supported_languages(self): return ["Korean"]
        index=0
        def generate_custom_voice(self,**kwargs):
            amplitude=[.025,.4][self.index%2]; self.index+=1
            return [SimpleNamespace(audio=(amplitude*np.sin(2*np.pi*220*np.arange(144000)/48000)).astype('float32'),sample_rate=48000,token_count=30)]
    runtime=RuntimeBindings(lambda *a,**k:Model(),lambda p,a,r,f:sf.write(p,a,r),lambda s:None,np.asarray,np.concatenate,lambda n,d:np.zeros(n,dtype=d),lambda a:bool(np.isfinite(a).all()))
    scene=Scene(scene_id=1,title='음량',narration='지구에서 바라보는 행성의 움직임을 살펴봅시다. 지구에서 바라보는 행성의 움직임을 살펴봅시다.',narrative_role='CONTEXT',visual_subject='지구')
    results=[]
    for mode in ['off','leveled']:
        settings=VoiceSettings(loudness_mode=mode,loudness_target_lufs=-18,min_scene_seconds=1)
        result=MLXAudioSynthesizer(settings,runtime_loader=lambda:runtime).synthesize([scene],{1:tmp_path/f'{mode}.mp3'})[0]
        raw=subprocess.run(['ffmpeg','-v','error','-i',str(result.path),'-ac','1','-ar','24000','-f','f32le','-'],capture_output=True,check=True).stdout
        pcm=np.frombuffer(raw,dtype='<f4'); duration=len(pcm)/24000
        rms=lambda start:np.sqrt(np.mean(pcm[round(start*24000):round((start+.8)*24000)]**2))
        jump=abs(20*np.log10(rms(duration/2+.7)/rms(.7)))
        results.append((duration,jump))
        assert np.all(np.isfinite(pcm)) and max(abs(pcm))<1
    assert results[0][1]>20
    assert results[1][1]<1
    assert abs(results[1][0]-results[0][0])<.05


def test_leveling_softens_large_volume_change_inside_one_sentence(tmp_path):
    class Model:
        def get_supported_speakers(self): return ["Sohee"]
        def get_supported_languages(self): return ["Korean"]
        def generate_custom_voice(self,**kwargs):
            a=np.sin(2*np.pi*220*np.arange(288000)/48000)
            a[:144000]*=.08; a[144000:]*=.4
            return [SimpleNamespace(audio=a.astype('float32'),sample_rate=48000,token_count=60)]
    runtime=RuntimeBindings(lambda *a,**k:Model(),lambda p,a,r,f:sf.write(p,a,r),lambda s:None,np.asarray,np.concatenate,lambda n,d:np.zeros(n,dtype=d),lambda a:bool(np.isfinite(a).all()))
    scene=Scene(scene_id=1,title='강약',narration='지구에서 바라보는 행성의 움직임과 두 행성의 상대적인 위치가 바뀌는 모습을 함께 살펴봅시다.',narrative_role='CONTEXT',visual_subject='지구')
    jumps=[]
    for mode in ['off','leveled']:
        result=MLXAudioSynthesizer(VoiceSettings(loudness_mode=mode,min_scene_seconds=1),runtime_loader=lambda:runtime).synthesize([scene],{1:tmp_path/f'{mode}.mp3'})[0]
        raw=subprocess.run(['ffmpeg','-v','error','-i',str(result.path),'-ac','1','-ar','24000','-f','f32le','-'],capture_output=True,check=True).stdout
        pcm=np.frombuffer(raw,dtype='<f4')
        rms=lambda start:np.sqrt(np.mean(pcm[int(start*24000):int((start+.5)*24000)]**2))
        jumps.append(abs(20*np.log10(rms(4)/rms(1))))
    assert jumps[0]>12
    assert jumps[1]<jumps[0]-3
