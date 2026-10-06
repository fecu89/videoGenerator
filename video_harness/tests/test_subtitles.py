import json
import pytest
from video_harness import subtitles as st
from video_harness.sequence_models import LocalSequencePlan


def scene_report(sample_counts, *, rate=1000, tempo=1.0):
    return {'sample_rate': rate, 'tempo_factor': tempo,
            'sentences': [{'text': f's{i}', 'sample_count': n, 'tempo_factor': tempo} for i, n in enumerate(sample_counts)]}


def test_sentence_windows_follow_the_mp3_filter_arithmetic():
    windows = st.sentence_windows(scene_report([3000, 3000]), leading_ms=100, trailing_ms=900)
    assert windows == [pytest.approx((0.0, 3.0)), pytest.approx((3.0, 6.0))]
    fast = st.sentence_windows(scene_report([3000], tempo=1.25), leading_ms=100, trailing_ms=900)
    assert fast == [pytest.approx((0.0, 2.4))]


def two_sequence_plan():
    def seq(sid, scene_id, start_audio):
        return {'sequence_id': sid, 'scene_ids': [scene_id], 'duration_frames': 60, 'render_mode': 'simulation',
                'scene_graph': 'shared-science-scene',
                'scene_spans': [{'scene_id': scene_id, 'start_frame': 0, 'end_frame': 60, 'audio_start_frame': start_audio, 'audio_end_frame': 60, 'tail_silence_frames': 0}],
                'timeline': [{'beat_id': f'B0{scene_id}', 'start_frame': 0, 'end_frame': 60, 'simulation_time_start': 0, 'simulation_time_end': 6, 'controller': 'c', 'patch_targets': ['geometry']}]}
    return LocalSequencePlan.model_validate({'schema_version': 1, 'script_sha256': 'a' * 64, 'production_plan_sha256': 'b' * 64,
        'defaults': {'width': 160, 'height': 90, 'fps': 10}, 'sequences': [seq('SEQ01', 1, 0), seq('SEQ02', 2, 5)]})


def test_scene_offsets_accumulate_sequence_lengths():
    offsets = st.scene_offsets(two_sequence_plan(), output_fps=10)
    assert offsets[1] == pytest.approx((0.0, 6.0))
    assert offsets[2] == pytest.approx((6.5, 12.0))
    offsets_30 = st.scene_offsets(two_sequence_plan(), output_fps=30)
    assert offsets_30[2] == pytest.approx((6.5, 12.0))


def test_wrap_lines_by_language():
    assert st.wrap_lines('The quick brown fox jumps over the lazy dog near the river bank today.', 'en', 42) == [
        'The quick brown fox jumps over the lazy', 'dog near the river bank today.']
    assert st.wrap_lines('여기 이상한 바람이 있습니다 시속 이백 킬로미터를 넘기도 합니다', 'ko', 22) == [
        '여기 이상한 바람이 있습니다 시속 이백', '킬로미터를 넘기도 합니다']
    assert st.wrap_lines('这里有一股永不停息的奇怪的风它从不停止', 'zh', 10) == ['这里有一股永不停息的', '奇怪的风它从不停止']


def test_split_for_two_lines_cuts_long_sentences_at_a_central_break():
    text = 'Here is a strange wind, it blows without stopping across the whole planet, and nobody knew why it bends so sharply.'
    pieces = st.split_for_two_lines(text, 'en', 42)
    assert len(pieces) >= 2 and all(len(st.wrap_lines(p, 'en', 42)) <= 2 for p in pieces)
    assert ' '.join(pieces) == text
    assert st.split_for_two_lines('Short one.', 'en', 42) == ['Short one.']


def test_build_cues_places_sentences_in_absolute_time_and_splits_over_long_ones():
    report = {'sentence_leading_margin_ms': 100, 'sentence_trailing_margin_ms': 900,
              'scenes': [{'scene_id': 2, 'sample_rate': 1000, 'tempo_factor': 1.0,
                          'sentences': [{'text': 'First line here.', 'sample_count': 3000, 'tempo_factor': 1.0},
                                        {'text': 'Second one.', 'sample_count': 2000, 'tempo_factor': 1.0}]}]}
    offsets = {2: (6.5, 12.0)}
    cues = st.build_cues(report, offsets, lang='en', chars_per_line=42)
    assert [c.lines for c in cues] == [['First line here.'], ['Second one.']]
    # A cue never outlasts its own sentence window, even though the next
    # sentence only speaks after its 0.1 s leading margin.
    assert cues[0].start == pytest.approx(6.6) and cues[0].end == pytest.approx(9.5)
    assert cues[1].start == pytest.approx(9.6) and cues[1].end == pytest.approx(11.5)
    assert st.subtitle_issues(cues, chars_per_line=42) == []


def test_render_ass_and_srt_formats():
    cues = [st.Cue(1.0, 2.5, ['Hello', 'world']), st.Cue(3.0, 4.0, ['Bye.'])]
    ass = st.render_ass(cues, width=1920, height=1080, font='Helvetica Neue')
    assert 'PlayResX: 1920' in ass and 'PlayResY: 1080' in ass
    style = next(l for l in ass.splitlines() if l.startswith('Style:'))
    fields = [f.strip() for f in style[len('Style:'):].split(',')]
    assert fields[1] == 'Helvetica Neue' and fields[2] == '48'
    assert fields[15] == '1' and fields[18] == '2' and fields[19] == '115' and fields[20] == '115' and fields[21] == '54'
    assert 'Dialogue: 0,0:00:01.00,0:00:02.50,Sub,,0,0,0,,Hello\\Nworld' in ass
    srt = st.render_srt(cues)
    assert srt.startswith('1\n00:00:01,000 --> 00:00:02,500\nHello\nworld\n\n2\n')


def test_subtitle_issues_cover_every_code():
    windows = [(0.0, 3.0), (3.0, 6.0)]
    good = [st.Cue(0.1, 2.9, ['ok']), st.Cue(3.1, 5.9, ['ok'])]
    assert st.subtitle_issues(good, chars_per_line=10, windows=windows) == []
    bad = [st.Cue(0.1, 3.5, ['ok']), st.Cue(3.1, 3.5, ['a' * 11, 'b', 'c'])]
    codes = {i.split(':')[0] for i in st.subtitle_issues(bad, chars_per_line=10, windows=windows)}
    assert codes == {'cue_outside_window', 'cue_overlap', 'cue_too_many_lines', 'cue_line_too_long', 'cue_too_short'}


def test_write_subtitles_creates_ass_srt_and_gate(tmp_path):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'subtitles', 'subtitle_languages': 'en'}}))
    (tmp_path / 'local-sequence-plan.json').write_text(two_sequence_plan().model_dump_json())
    (tmp_path / 'voice-generation-report-en.json').write_text(json.dumps({
        'schema_version': 1, 'language': 'en', 'sentence_leading_margin_ms': 100, 'sentence_trailing_margin_ms': 900,
        'scenes': [{'scene_id': 1, 'sample_rate': 1000, 'tempo_factor': 1.0, 'sentences': [{'text': 'One.', 'sample_count': 3000, 'tempo_factor': 1.0}]},
                   {'scene_id': 2, 'sample_rate': 1000, 'tempo_factor': 1.0, 'sentences': [{'text': 'Two.', 'sample_count': 3000, 'tempo_factor': 1.0}]}]}))
    from video_harness.language_voices import load_language_voices
    load_language_voices(tmp_path)
    ass_path = st.write_subtitles(tmp_path, 'en', quality='draft', width=384, height=216, output_fps=10)
    assert ass_path == tmp_path / 'subtitles' / 'en.ass' and (tmp_path / 'subtitles' / 'en.srt').is_file()
    assert json.loads((tmp_path / 'subtitle-gate-en.json').read_text())['status'] == 'passed'
    assert 'Dialogue: 0,0:00:06.60' in ass_path.read_text()


def test_sentence_windows_prefer_reported_output_seconds():
    scene = {'sample_rate': 1000, 'tempo_factor': 1.2,
             'sentences': [{'text': 'a', 'sample_count': 3400, 'tempo_factor': 1.2, 'output_seconds': 3.5},
                           {'text': 'b', 'sample_count': 3400, 'tempo_factor': 1.2, 'output_seconds': 3.5}]}
    assert st.sentence_windows(scene, leading_ms=100, trailing_ms=950) == [pytest.approx((0.0, 3.5)), pytest.approx((3.5, 7.0))]


def test_subtitle_gate_reports_speech_that_overflows_the_scene_slot():
    report = {'sentence_leading_margin_ms': 100, 'sentence_trailing_margin_ms': 900,
              'scenes': [{'scene_id': 1, 'sample_rate': 1000, 'tempo_factor': 1.0,
                          'sentences': [{'text': 'Long.', 'sample_count': 3000, 'tempo_factor': 1.0, 'output_seconds': 4.0}]}]}
    cues = st.build_cues(report, {1: (0.0, 3.0)}, lang='en', chars_per_line=42)
    issues = st.subtitle_issues(cues, chars_per_line=42)
    assert any(i.startswith('cue_overflows_slot') for i in issues)


def test_write_subtitles_targets_the_artifact_root_not_the_run(tmp_path):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': 'subtitles', 'subtitle_languages': 'en'}}))
    (tmp_path / 'local-sequence-plan.json').write_text(two_sequence_plan().model_dump_json())
    (tmp_path / 'voice-generation-report-en.json').write_text(json.dumps({
        'schema_version': 1, 'language': 'en', 'sentence_leading_margin_ms': 100, 'sentence_trailing_margin_ms': 900,
        'scenes': [{'scene_id': 1, 'sample_rate': 1000, 'tempo_factor': 1.0, 'sentences': [{'text': 'One.', 'sample_count': 3000, 'tempo_factor': 1.0}]},
                   {'scene_id': 2, 'sample_rate': 1000, 'tempo_factor': 1.0, 'sentences': [{'text': 'Two.', 'sample_count': 3000, 'tempo_factor': 1.0}]}]}))
    from video_harness.language_voices import load_language_voices
    load_language_voices(tmp_path)
    staging = tmp_path / '.staging'
    ass_path = st.write_subtitles(tmp_path, 'en', quality='final', width=384, height=216, output_fps=10, out_root=staging)
    assert ass_path == staging / 'subtitles' / 'en.ass' and (staging / 'subtitles' / 'en.srt').is_file()
    assert not (tmp_path / 'subtitles').exists()


def test_cue_times_round_inward_to_stay_inside_their_window():
    report = {'sentence_leading_margin_ms': 100, 'sentence_trailing_margin_ms': 900,
              'scenes': [{'scene_id': 1, 'sample_rate': 1000, 'tempo_factor': 1.0,
                          'sentences': [{'text': 'One.', 'sample_count': 2000, 'tempo_factor': 1.0, 'output_seconds': 2.1234567},
                                        {'text': 'Two.', 'sample_count': 2000, 'tempo_factor': 1.0, 'output_seconds': 2.1115}]}]}
    cues = st.build_cues(report, {1: (0.0004, 9.0)}, lang='en', chars_per_line=42)
    assert st.subtitle_issues(cues, chars_per_line=42) == []


def test_off_centre_comma_does_not_leave_a_tiny_cue():
    text = 'In the end, these meanders hold both the motion of the air and the rotation of the Earth.'
    pieces = st.split_for_two_lines(text, 'en', 42)
    assert len(pieces) == 2 and min(len(p) for p in pieces) > len(text) / 3
    centred = 'The planetary part of the spin falls, so the relative part must rise again.'
    assert centred.index(',') > len(centred) / 3
    assert st.split_for_two_lines(centred, 'en', 30)[0].endswith(',')


def test_older_master_reports_use_audible_speech_plus_margins():
    # Measured on the 2026-09-22 Korean master: raw 1.92 s holds model silence,
    # audible speech is 1.79 s; the second sentence speaks from 2.94 s to 8.16 s.
    scene = {'sample_rate': 24000, 'tempo_factor': 1.0, 'sentences': [
        {'text': 'a.', 'sample_count': 46080, 'tempo_factor': 1.0, 'adjusted_speech_seconds': 1.7909},
        {'text': 'b.', 'sample_count': 127462, 'tempo_factor': 1.0, 'adjusted_speech_seconds': 5.2287}]}
    windows = st.sentence_windows(scene, leading_ms=100, trailing_ms=950)
    assert windows[0] == pytest.approx((0.0, 2.8409), abs=1e-3)
    assert windows[1][0] + 0.1 == pytest.approx(2.94, abs=0.01)
    assert windows[1][0] + 0.1 + 5.2287 == pytest.approx(8.16, abs=0.01)
