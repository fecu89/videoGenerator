import json
from pathlib import Path
import pytest
from video_harness import localize
from video_harness.settings import HarnessSettings
from video_harness.media import MediaInfo
from video_harness.tests.test_subtitles import two_sequence_plan


def subtitle_settings(langs='en,ja'):
    return HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': langs})


def test_language_outputs_only_for_subtitle_runs_with_languages():
    assert localize.language_outputs(subtitle_settings()) == ['ko', 'en', 'ja']
    assert localize.language_outputs(HarnessSettings()) == []
    assert localize.language_outputs(HarnessSettings(local_video={'text_policy': 'keywords', 'subtitle_languages': 'en'})) == []
    assert localize.language_outputs(HarnessSettings(local_video={'text_policy': 'subtitles'})) == []


def test_final_name_and_expected_outputs():
    # Subtitles differ per language, so every language is a burned-in video.
    assert localize.final_name('ko', 'final') == 'final-ko.mp4'
    assert localize.final_name('en', 'final') == 'final-en.mp4'
    assert localize.final_name('en', 'draft') == 'final-draft-en.mp4'
    assert localize.expected_language_outputs(subtitle_settings('en')) == {
        'final-ko.mp4', 'final-en.mp4', 'final-draft-ko.mp4', 'final-draft-en.mp4',
        'subtitles/ko.ass', 'subtitles/ko.srt', 'subtitles/en.ass', 'subtitles/en.srt'}
    assert localize.expected_language_outputs(HarnessSettings()) == set()


def seeded_run(tmp_path):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'subtitles', 'subtitle_languages': 'en'}}))
    (tmp_path / 'local-sequence-plan.json').write_text(two_sequence_plan().model_dump_json())
    report = lambda: {'schema_version': 1, 'sentence_leading_margin_ms': 100, 'sentence_trailing_margin_ms': 900,
        'scenes': [{'scene_id': 1, 'sample_rate': 1000, 'tempo_factor': 1.0, 'sentences': [{'text': 'One.', 'sample_count': 3000, 'tempo_factor': 1.0}]},
                   {'scene_id': 2, 'sample_rate': 1000, 'tempo_factor': 1.0, 'sentences': [{'text': 'Two.', 'sample_count': 3000, 'tempo_factor': 1.0}]}]}
    (tmp_path / 'voice-generation-report.json').write_text(json.dumps(report()))
    (tmp_path / 'voice-generation-report-en.json').write_text(json.dumps(report()))
    script = {'scenes': [{'scene_id': 1, 'audio_file': 'audioFiles/01_a.mp3'}, {'scene_id': 2, 'audio_file': 'audioFiles/02_b.mp3'}]}
    for lang_dir, names in (('audioFiles', ['01_a.mp3', '02_b.mp3']), ('audioFiles/en', ['01_a.mp3', '02_b.mp3'])):
        (tmp_path / lang_dir).mkdir(parents=True, exist_ok=True)
        for n in names:
            (tmp_path / lang_dir / n).write_bytes(b'mp3')
    (tmp_path / 'video-only.mp4').write_bytes(b'video')
    return script


def test_localize_outputs_muxes_then_burns_each_language(tmp_path, monkeypatch):
    seeded_run(tmp_path)
    mux_calls, burn_calls = [], []
    def fake_mux(video, placements, destination, spec, **kw):
        mux_calls.append((video.name, [(p.source.name, p.start_frame, p.end_frame) for p in placements], destination.name))
        destination.write_bytes(b'muxed'); return None
    def fake_runner(cmd, **kw):
        burn_calls.append([str(c) for c in cmd]); Path(cmd[-1]).write_bytes(b'burned')
        import subprocess; return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(localize, 'mux_audio_timeline', fake_mux)
    import video_harness.localize_voice as lv
    monkeypatch.setattr(lv, 'language_audio_issues', lambda run, lang: [])
    outputs = localize.localize_outputs(tmp_path, quality='final', artifact_root=tmp_path, video_only=tmp_path / 'video-only.mp4',
                                        scene_audio={1: 'audioFiles/01_a.mp3', 2: 'audioFiles/02_b.mp3'}, settings=subtitle_settings('en'),
                                        output_fps=10, width=160, height=90, frame_count=120, runner=fake_runner)
    assert outputs == ['final-ko.mp4', 'final-en.mp4']
    assert [m[0] for m in mux_calls] == ['video-only.mp4', 'video-only.mp4']
    assert mux_calls[0][1] == [('01_a.mp3', 0, 60), ('02_b.mp3', 65, 120)]
    assert len(burn_calls) == 2 and all('ass=' in ' '.join(c) for c in burn_calls)
    assert burn_calls[0][-1].endswith('final-ko.mp4') and burn_calls[1][-1].endswith('final-en.mp4')
    assert (tmp_path / 'subtitles' / 'en.ass').is_file() and (tmp_path / 'subtitles' / 'ko.ass').is_file()
    assert json.loads((tmp_path / 'subtitle-gate-en.json').read_text())['status'] == 'passed'


def test_require_localization_checks_lengths_and_audio(tmp_path, monkeypatch):
    seeded_run(tmp_path)
    for name in ('final-ko.mp4', 'final-en.mp4'):
        (tmp_path / name).write_bytes(b'x')
    (tmp_path / 'subtitle-gate-ko.json').write_text('{"status":"passed"}'); (tmp_path / 'subtitle-gate-en.json').write_text('{"status":"passed"}')
    infos = {'video-only.mp4': dict(frames=120, duration=12.0), 'final-ko.mp4': dict(frames=120, duration=12.0), 'final-en.mp4': dict(frames=120, duration=12.0)}
    def fake_probe(path, *, require_audio=False):
        info = infos[Path(path).name]
        audio_only = Path(path).suffix == '.m4a'
        return MediaInfo(video_codec='' if audio_only else 'h264', audio_codec=None if Path(path).name == 'video-only.mp4' else 'aac',
                         width=0 if audio_only else 160, height=0 if audio_only else 90, fps=0.0 if audio_only else 10.0,
                         duration_seconds=info['duration'], frame_count=info['frames'])
    monkeypatch.setattr(localize, 'probe_media', fake_probe)
    localize.require_localization(tmp_path, tmp_path, 'final', ['ko', 'en'])
    assert json.loads((tmp_path / 'localization-final-gate.json').read_text())['status'] == 'passed'
    infos['final-en.mp4'] = dict(frames=118, duration=11.8)
    with pytest.raises(ValueError, match='localized_length_mismatch: en'):
        localize.require_localization(tmp_path, tmp_path, 'final', ['ko', 'en'])


def test_owned_public_files_include_language_outputs_and_subtitles(tmp_path):
    from video_harness.produce_local import _current_owned_public_files
    (tmp_path / 'final-ja.mp4').write_bytes(b'x'); (tmp_path / 'final-draft-ja.mp4').write_bytes(b'x')
    (tmp_path / 'subtitles').mkdir(); (tmp_path / 'subtitles' / 'ja.ass').write_text('x'); (tmp_path / 'subtitles' / 'ja.srt').write_text('x')
    (tmp_path / 'final.mp4').write_bytes(b'x')
    assert {'final-ja.mp4', 'final-draft-ja.mp4', 'subtitles/ja.ass', 'subtitles/ja.srt', 'final.mp4'} <= _current_owned_public_files(tmp_path)


def test_ass_filter_argument_escapes_special_characters():
    assert localize.ass_filter_argument(Path("/tmp/a:b,c'd[e].ass")) == "ass=/tmp/a\\:b\\,c\\'d\\[e\\].ass"
    assert localize.ass_filter_argument(Path('/plain/en.ass')) == 'ass=/plain/en.ass'


def writing_runner(cmd, **kw):
    import subprocess
    Path(cmd[-1]).write_bytes(b'burned'); return subprocess.CompletedProcess(cmd, 0, '', '')


def test_stale_language_audio_stops_before_subtitles_are_written(tmp_path, monkeypatch):
    seeded_run(tmp_path)
    import video_harness.localize_voice as lv
    monkeypatch.setattr(lv, 'language_audio_issues', lambda run, lang: ['language_audio_stale: en'])
    monkeypatch.setattr(localize, 'mux_audio_timeline', lambda video, placements, destination, spec, **kw: Path(destination).write_bytes(b'm'))
    with pytest.raises(ValueError, match='language_audio_stale'):
        localize.localize_outputs(tmp_path, quality='final', artifact_root=tmp_path, video_only=tmp_path / 'video-only.mp4',
                                  scene_audio={1: 'audioFiles/01_a.mp3', 2: 'audioFiles/02_b.mp3'}, settings=subtitle_settings('en'),
                                  output_fps=10, width=160, height=90, frame_count=120, runner=writing_runner)
    assert not (tmp_path / 'subtitles' / 'en.ass').exists()


def test_localize_mixes_background_music_before_burning(tmp_path, monkeypatch):
    seeded_run(tmp_path)
    (tmp_path / 'language-voices.json').unlink(missing_ok=True)
    import video_harness.localize_voice as lv
    monkeypatch.setattr(lv, 'language_audio_issues', lambda run, lang: [])
    monkeypatch.setattr(localize, 'mux_audio_timeline', lambda video, placements, destination, spec, **kw: Path(destination).write_bytes(b'm'))
    track = tmp_path / 'input' / 'bgmusic' / 'calm.mp3'; track.parent.mkdir(parents=True); track.write_bytes(b'music')
    monkeypatch.setattr(localize, 'resolve_music_file', lambda run, settings: track)
    commands = []
    def runner(cmd, **kw):
        commands.append([str(c) for c in cmd]); Path(cmd[-1]).write_bytes(b'out')
        import subprocess; return subprocess.CompletedProcess(cmd, 0, '', '')
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'}, music={'file': 'calm.mp3'})
    localize.localize_outputs(tmp_path, quality='final', artifact_root=tmp_path, video_only=tmp_path / 'video-only.mp4',
                              scene_audio={1: 'audioFiles/01_a.mp3', 2: 'audioFiles/02_b.mp3'}, settings=settings,
                              output_fps=10, width=160, height=90, frame_count=120, runner=runner)
    music_cmds = [c for c in commands if any('loudnorm' in part for part in c)]
    burn_cmds = [c for c in commands if any(part.startswith('ass=') for part in c)]
    assert len(music_cmds) == 2 and len(burn_cmds) == 2          # ko + en, each: music mix then burn
    graph = next(part for part in music_cmds[0] if 'loudnorm' in part)
    assert "-16.0*" in graph and "-stream_loop" in music_cmds[0]
    assert burn_cmds[0][burn_cmds[0].index('-i') + 1].endswith('.music.mp4')


def audio_track_settings(langs='en'):
    return HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': langs, 'localized_delivery': 'audio_tracks'})


def test_delivery_setting_defaults_to_burned_videos_and_is_hash_excluded():
    from video_harness import settings as settings_module
    assert HarnessSettings().local_video.localized_delivery == 'burned_videos'
    assert settings_module.settings_sha256(HarnessSettings()) != settings_module.settings_sha256(audio_track_settings())
    payload = json.loads((settings_module.PROJECT_ROOT / 'settings.json').read_text())
    assert payload['local_video']['localized_delivery'] in ('burned_videos', 'audio_tracks')


def test_audio_track_delivery_names_and_expected_outputs():
    assert localize.final_name('en', 'final', delivery='audio_tracks') == 'final-en.m4a'
    assert localize.final_name('ko', 'draft', delivery='audio_tracks') == 'final-draft-ko.m4a'
    assert localize.final_name('en', 'final') == 'final-en.mp4'
    assert localize.expected_language_outputs(audio_track_settings('en')) == {
        'final-ko.m4a', 'final-en.m4a', 'final-draft-ko.m4a', 'final-draft-en.m4a',
        'subtitles/ko.ass', 'subtitles/ko.srt', 'subtitles/en.ass', 'subtitles/en.srt'}


def test_audio_track_delivery_extracts_audio_instead_of_burning(tmp_path, monkeypatch):
    seeded_run(tmp_path)
    import video_harness.localize_voice as lv
    monkeypatch.setattr(lv, 'language_audio_issues', lambda run, lang: [])
    monkeypatch.setattr(localize, 'mux_audio_timeline', lambda video, placements, destination, spec, **kw: Path(destination).write_bytes(b'm'))
    commands = []
    def runner(cmd, **kw):
        commands.append([str(c) for c in cmd]); Path(cmd[-1]).write_bytes(b'out')
        import subprocess; return subprocess.CompletedProcess(cmd, 0, '', '')
    outputs = localize.localize_outputs(tmp_path, quality='final', artifact_root=tmp_path, video_only=tmp_path / 'video-only.mp4',
                                        scene_audio={1: 'audioFiles/01_a.mp3', 2: 'audioFiles/02_b.mp3'}, settings=audio_track_settings('en'),
                                        output_fps=10, width=160, height=90, frame_count=120, runner=runner)
    assert outputs == ['final-ko.m4a', 'final-en.m4a']
    assert all('-vn' in c and not any(p.startswith('ass=') for p in c) for c in commands)
    assert (tmp_path / 'subtitles' / 'en.srt').is_file()


def test_audio_track_delivery_gate_compares_durations_only(tmp_path, monkeypatch):
    seeded_run(tmp_path)
    for name in ('final-ko.m4a', 'final-en.m4a'):
        (tmp_path / name).write_bytes(b'x')
    for lang in ('ko', 'en'):
        (tmp_path / f'subtitle-gate-{lang}.json').write_text('{"status":"passed"}')
    monkeypatch.setattr(localize, 'probe_media', lambda path, **kw: MediaInfo(video_codec='h264', audio_codec=None, width=160, height=90, fps=10.0, duration_seconds=12.0, frame_count=120))
    durations = {'final-ko.m4a': 12.02, 'final-en.m4a': 12.0}
    monkeypatch.setattr(localize, 'probe_audio_track', lambda path: (durations[Path(path).name], 'aac'))
    localize.require_localization(tmp_path, tmp_path, 'final', ['ko', 'en'], delivery='audio_tracks')
    assert json.loads((tmp_path / 'localization-final-gate.json').read_text())['status'] == 'passed'
    durations['final-en.m4a'] = 11.5
    with pytest.raises(ValueError, match='localized_length_mismatch: en'):
        localize.require_localization(tmp_path, tmp_path, 'final', ['ko', 'en'], delivery='audio_tracks')
