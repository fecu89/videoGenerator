import json
import pytest
from video_harness import music
from video_harness.settings import HarnessSettings


@pytest.mark.parametrize('fails', [False, True])
def test_score_master_replaces_only_after_success(tmp_path, monkeypatch, fails):
    master = tmp_path / 'final.mp4'; master.write_bytes(b'voice')
    monkeypatch.setattr(music, 'resolve_music_file', lambda *args: tmp_path / 'track.mp3')
    monkeypatch.setattr('video_harness.subtitles.speech_spans', lambda *args, **kwargs: [(0, 1)])
    def mix(_runner, **kwargs):
        assert kwargs['source'].read_bytes() == b'voice'
        kwargs['destination'].write_bytes(b'voice+music')
        if fails:
            raise RuntimeError('mix failed')
    monkeypatch.setattr(music, 'add_music', mix)
    if fails:
        with pytest.raises(RuntimeError, match='mix failed'):
            music.score_master(tmp_path, source=master, duration=2, fps=30, settings=HarnessSettings())
    else:
        music.score_master(tmp_path, source=master, duration=2, fps=30, settings=HarnessSettings())
    assert master.read_bytes() == (b'voice' if fails else b'voice+music')
    assert not list(tmp_path.glob('*.music.tmp.mp4'))


def test_music_settings_default_off_and_hash_excluded():
    import hashlib
    from video_harness import settings as settings_module
    settings = HarnessSettings()
    assert settings.music.file == "" and settings.music.duck_db == -16.0 and settings.music.fade_seconds == 1.2
    values = settings.model_dump(mode="json")
    for key in ("text_policy", "subtitle_languages", "localized_delivery", "camera_transition_seconds"):
        values["local_video"].pop(key)
    values.pop("music")
    values.pop("promotion")
    values.pop("pacing")
    values["local_video"].pop("target_beat_min_seconds")
    values["local_video"].pop("target_beat_max_seconds")
    values["voice"].pop("max_tempo_factor")
    for key in ('pause_mode', 'comma_pause_ms', 'semantic_pause_ms', 'emphasis_pause_ms', 'sentence_pause_ms'):
        values['voice'].pop(key)
    canonical = json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert settings_module.settings_sha256(settings) == hashlib.sha256(canonical.encode()).hexdigest()
    with_music = HarnessSettings(music={"file": "calm.mp3"})
    assert settings_module.settings_sha256(with_music) != settings_module.settings_sha256(settings)


def test_speech_intervals_keep_short_gaps_and_merge_only_overlaps():
    cues = [(1.0, 3.0), (3.5, 5.0), (4.8, 6.0), (9.0, 10.0)]
    assert music.speech_intervals(cues, fade_seconds=1.2) == [(1.0, 3.0), (3.5, 6.0), (9.0, 10.0)]
    assert music.speech_intervals([], fade_seconds=1.2) == []


def test_duck_expression_ramps_down_and_up_over_the_fade_setting():
    expr = music.duck_envelope_expression([(5.0, 8.0)], fade_seconds=1.2)
    from video_harness.tests.ffexpr import evaluate
    assert evaluate(expr, t=0.0) == pytest.approx(0.0)
    assert evaluate(expr, t=3.8) == pytest.approx(0.0)
    assert evaluate(expr, t=4.4) == pytest.approx(0.5)
    assert evaluate(expr, t=6.0) == pytest.approx(1.0)
    assert evaluate(expr, t=8.6) == pytest.approx(0.5)
    assert evaluate(expr, t=9.3) == pytest.approx(0.0)


def test_music_breathes_between_closely_spaced_sentences():
    # Speech ends ~0.5 s before the next sentence once the silent trailing margin is excluded.
    # Merged spans pinned the duck for the whole film; separate spans let it lift in each pause.
    cues = [(0.0, 3.0), (3.5, 6.0), (6.5, 9.0)]
    intervals = music.speech_intervals(cues, fade_seconds=1.0)
    assert len(intervals) == 3
    expr = music.duck_envelope_expression(intervals, fade_seconds=1.0)
    from video_harness.tests.ffexpr import evaluate
    assert evaluate(expr, t=1.5) == pytest.approx(1.0)
    assert evaluate(expr, t=3.25) == pytest.approx(0.75)
    assert evaluate(expr, t=7.5) == pytest.approx(1.0)


def test_music_filter_graph_contains_loudnorm_gain_duck_fade_and_limiter():
    graph = music.music_filter_graph(duration=100.0, gain_db=-12.0, duck_db=-16.0, fade_seconds=1.2,
                                     intervals=[(5.0, 8.0)], loop=True, target_lufs=-18.0, true_peak_db=-1.5)
    assert "loudnorm=I=-18.0" in graph and "atrim=duration=100.000" in graph
    assert "volume='pow(10,(-12.0+-16.0*" in graph and "afade=t=out:st=98.000:d=2" in graph
    assert "alimiter=limit=" in graph and "amix=inputs=2" in graph


def test_resolve_music_file_reads_bgmusic_library_and_copies_into_run(tmp_path):
    library = tmp_path / "bgmusic"; library.mkdir(); (library / "calm.mp3").write_bytes(b"music")
    run = tmp_path / "run"; run.mkdir()
    settings = HarnessSettings(music={"file": "calm.mp3"})
    path = music.resolve_music_file(run, settings, library=library)
    assert path == run / "input" / "bgmusic" / "calm.mp3" and path.read_bytes() == b"music"
    assert music.resolve_music_file(run, HarnessSettings(), library=library) is None
    with pytest.raises(FileNotFoundError, match="bgmusic"):
        music.resolve_music_file(run, HarnessSettings(music={"file": "missing.mp3"}), library=library)


def test_speech_spans_exclude_each_sentence_trailing_silence():
    from video_harness.subtitles import Cue, speech_spans_from_cues
    cues = [Cue(0.05, 1.5, ['a'], window=(0.0, 3.3)),      # first half of a two-line sentence
            Cue(1.5, 3.3, ['b'], window=(0.0, 3.3)),       # its last piece ends on the window
            Cue(3.35, 6.0, ['c'], window=(3.3, 6.0))]
    assert speech_spans_from_cues(cues, trailing_seconds=0.25) == [(0.05, 1.5), (1.5, 3.05), (3.35, 5.75)]
