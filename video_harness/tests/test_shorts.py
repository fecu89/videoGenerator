import json
import shutil
import struct
import subprocess

import pytest

from video_harness import pipeline
from video_harness.models import ScriptArtifact
from video_harness.shorts import build_shorts, shorts_ass, shorts_titles, subtitle_cues, title_size, wrap_cjk
from video_harness.tests.test_translations import make_run
from video_harness.translations import load_translations, scaffold_translations, translation_issues, write_translations
from video_harness.language_voices import load_language_voices
from video_harness.production import script_sha256
from video_harness.upload_text import credit_warnings, model_credits, upload_markdown, write_upload_text

SRT = "1\n00:00:00,000 --> 00:00:01,150\n{a}\n{b}\n\n2\n00:00:01,150 --> 00:00:02,300\n{c}\n"


def titled_run(tmp_path, languages='en,ja'):
    make_run(tmp_path, languages=languages)
    script = ScriptArtifact.model_validate_json((tmp_path / 'script.json').read_text())
    script.shorts_title = '태풍이 북서쪽으로 가는 이유'
    script.upload_description = '태풍의 진로를 무역풍과 베타 효과로 설명합니다.'
    (tmp_path / 'script.json').write_text(script.model_dump_json(indent=2) + '\n')
    targets = [code for code in languages.split(',') if code]
    translations = scaffold_translations(tmp_path, targets)
    for scene in translations.scenes:
        scene.text = {lang: 'Short line.' for lang in targets}
    write_translations(tmp_path, translations)
    return script, translations


def write_glb(path, extras):
    payload = json.dumps({'asset': {'version': '2.0', **({'extras': extras} if extras else {})}}).encode()
    payload += b' ' * (-len(payload) % 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 20 + len(payload)) + struct.pack('<I4s', len(payload), b'JSON') + payload)


def test_scaffold_has_upload_slots_and_gate_requires_them_only_when_script_declares(tmp_path):
    script, translations = titled_run(tmp_path)
    assert translations.title == translations.shorts_title == translations.description == {'en': '', 'ja': ''}
    voices = load_language_voices(tmp_path)
    issues = translation_issues(translations, script, script_sha256(tmp_path / 'script.json'), voices, ['en', 'ja'])
    assert {'shorts_title_missing: en', 'title_missing: ja', 'description_missing: en'} <= set(issues)
    translations.title = translations.shorts_title = translations.description = {'en': 'Why', 'ja': '理由'}
    assert translation_issues(translations, script, script_sha256(tmp_path / 'script.json'), voices, ['en', 'ja']) == []
    script.shorts_title = script.upload_description = None
    translations.title = translations.shorts_title = translations.description = {}
    assert not [i for i in translation_issues(translations, script, script_sha256(tmp_path / 'script.json'), voices, ['en', 'ja'])
                if 'title' in i or 'description' in i]


def test_old_translations_without_upload_fields_still_load(tmp_path):
    _, translations = titled_run(tmp_path)
    payload = translations.model_dump()
    for key in ('title', 'shorts_title', 'description'):
        del payload[key]
    (tmp_path / 'translations.json').write_text(json.dumps(payload))
    assert load_translations(tmp_path).shorts_title == {}


def test_titles_come_from_script_then_translations_then_overrides(tmp_path):
    script, translations = titled_run(tmp_path)
    translations.shorts_title = {'en': 'Why Typhoons Head Northwest', 'ja': ''}
    write_translations(tmp_path, translations, force=True)
    assert shorts_titles(tmp_path, ['ko', 'en', 'ja']) == {'ko': script.shorts_title, 'en': 'Why Typhoons Head Northwest'}
    assert shorts_titles(tmp_path, ['ko', 'ja'], {'ja': '台風が北西へ進む理由'})['ja'] == '台風が北西へ進む理由'
    script.shorts_title = None
    (tmp_path / 'script.json').write_text(script.model_dump_json())
    assert shorts_titles(tmp_path, ['ko'])['ko'] == script.selected_topic.title


def test_saved_overrides_reach_both_the_shorts_titles_and_the_upload_sheet(tmp_path):
    """A run approved before these fields existed cannot edit script.json or translations.json."""
    from video_harness.shorts import save_shorts_title_overrides
    from video_harness.upload_text import upload_sheet
    script, _ = titled_run(tmp_path)
    save_shorts_title_overrides(tmp_path, {'ko': '태풍은 왜 무역풍을 따라가지 않을까?'})
    save_shorts_title_overrides(tmp_path, {'en': "Why Don't Typhoons Follow the Trade Winds?"})
    assert shorts_titles(tmp_path, ['ko', 'en', 'ja']) == {
        'ko': '태풍은 왜 무역풍을 따라가지 않을까?', 'en': "Why Don't Typhoons Follow the Trade Winds?"}
    assert shorts_titles(tmp_path, ['ko'], {'ko': '명령줄 제목'})['ko'] == '명령줄 제목'
    saved = json.loads((tmp_path / 'upload-overrides.json').read_text())
    saved['title'] = {'en': 'Why Typhoons Head Northwest'}
    saved['description'] = {'en': 'An explanation of the beta effect.'}
    (tmp_path / 'upload-overrides.json').write_text(json.dumps(saved, ensure_ascii=False))
    english = next(e for e in upload_sheet(tmp_path)['languages'] if e['lang'] == 'en')
    assert english['title'] == 'Why Typhoons Head Northwest'
    assert english['description'].startswith('An explanation of the beta effect.')


def test_title_size_shrinks_long_titles_and_caps_short_ones():
    assert title_size('台風が北西へ進む理由') == 92
    assert title_size('¿Por qué el tifón va al noroeste?') < title_size('Why Typhoons Head Northwest') < 92


def test_cues_rewrap_for_portrait_and_ass_retimes_for_speed(tmp_path):
    (tmp_path / 'en.srt').write_text(SRT.format(a='North of the equator,', b='a steady wind blows.', c='Next.'))
    (tmp_path / 'ja.srt').write_text(SRT.format(a='衛星を引き裂く潮汐力が、まとめる力を上回', b='ることがあります。', c='次。'))
    assert subtitle_cues(tmp_path / 'en.srt', 'en')[0] == (0.0, 1.15, 'North of the equator, a steady wind blows.')
    japanese = subtitle_cues(tmp_path / 'ja.srt', 'ja')[0][2].split('\\N')
    assert ''.join(japanese) == '衛星を引き裂く潮汐力が、まとめる力を上回ることがあります。' and max(map(len, japanese)) <= 14
    assert all(line[0] not in '、。' for line in wrap_cjk('あ' * 12 + '、' + 'い' * 12 + '。', 13))
    ass = shorts_ass(lang='en', font='Helvetica Neue', title='Why', cues=subtitle_cues(tmp_path / 'en.srt', 'en'))
    assert 'Dialogue: 0,0:00:00.00,10:00:00.00,Title,,0,0,0,,Why' in ass
    assert 'Dialogue: 0,0:00:00.00,0:00:01.00,Sub,,0,0,0,,North of the equator, a steady wind blows.' in ass
    assert 'Style: Title' not in shorts_ass(lang='en', font='Helvetica Neue', title=None, cues=[])


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg required')
@pytest.mark.parametrize('delivery', ['audio_tracks', 'videos', 'video_and_audio'])
def test_build_shorts_makes_one_portrait_video_per_language_and_upload_sheet_lists_them(tmp_path, delivery):
    script, translations = titled_run(tmp_path, languages='en')
    translations.title, translations.shorts_title, translations.description = {'en': 'Why Typhoons Turn'}, {'en': 'Why Northwest'}, {'en': 'Trade winds and the beta effect.'}
    write_translations(tmp_path, translations, force=True)
    settings = json.loads((tmp_path / 'run-settings.json').read_text())
    settings['local_video']['localized_delivery'] = delivery
    (tmp_path / 'run-settings.json').write_text(json.dumps(settings))
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=30:duration=2.3',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2.3', '-shortest', '-pix_fmt', 'yuv420p', str(tmp_path / 'final.mp4')], check=True)
    for lang in ('ko', 'en'):
        if delivery == 'audio_tracks' or (delivery == 'video_and_audio' and lang != 'ko'):
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', str(tmp_path / 'final.mp4'), '-vn', '-c:a', 'copy', str(tmp_path / f'final-{lang}.m4a')], check=True)
        else:
            shutil.copyfile(tmp_path / 'final.mp4', tmp_path / f'final-{lang}.mp4')
        (tmp_path / 'subtitles').mkdir(exist_ok=True)
        (tmp_path / 'subtitles' / f'{lang}.srt').write_text(SRT.format(a='One', b='two.', c='Three.'))
    write_glb(tmp_path / 'assets' / 'earth.glb', {'author': 'Akshat (https://sketchfab.com/shooter24994)', 'title': 'Earth',
              'license': 'CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)', 'source': 'https://sketchfab.com/3d-models/earth-41fc'})
    write_glb(tmp_path / 'assets' / 'probe.glb', None)

    outputs = build_shorts(tmp_path)

    assert [path.name for path in outputs] == ['shorts-ko.mp4', 'shorts-en.mp4']
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(outputs[1])],
                                      capture_output=True, text=True, check=True).stdout)
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert (video['width'], video['height']) == (1080, 1920) and any(s['codec_type'] == 'audio' for s in probe['streams'])
    assert abs(float(probe['format']['duration']) - 2.3 / 1.15) < 0.15
    assert 'Title,,0,0,0,,Why Northwest' in (tmp_path / 'shorts' / 'shorts-en.ass').read_text()

    sheet = write_upload_text(tmp_path).read_text()
    assert '## English (en)' in sheet and '```text\nWhy Typhoons Turn\n```' in sheet and '```text\nWhy Northwest\n```' in sheet
    assert f'```text\n{script.upload_description}\n\n3D 모델 (수정하여 사용)\n- "Earth" by Akshat — https://sketchfab.com/3d-models/earth-41fc (CC BY 4.0)' in sheet
    assert 'Trade winds and the beta effect.\n\n#Shorts\n\n3D models (modified)' in sheet
    assert 'CC BY 4.0: http://creativecommons.org/licenses/by/4.0/' in sheet and '`probe.glb`: 파일 안에 출처' in sheet


def test_credit_warnings_flag_noncommercial_and_no_derivatives(tmp_path):
    write_glb(tmp_path / 'assets' / 'a.glb', {'title': 'Quartz', 'author': 'Uni', 'license': 'CC-BY-NC-4.0 (http://x/nc)', 'source': 'http://s/a'})
    write_glb(tmp_path / 'assets' / 'b.glb', {'title': 'Snack', 'author': 'B', 'license': 'CC-BY-ND-4.0 (http://x/nd)', 'source': 'http://s/b'})
    write_glb(tmp_path / 'assets' / 'copy' / 'a.glb', {'title': 'Quartz', 'author': 'Uni', 'license': 'CC-BY-NC-4.0 (http://x/nc)', 'source': 'http://s/a'})
    credits = model_credits(tmp_path)
    assert [c.title for c in credits] == ['Quartz', 'Snack']
    warnings = credit_warnings(credits)
    assert '비영리 전용' in warnings[0] and '변경 금지' in warnings[1]


def test_upload_sheet_without_shorts_or_translated_title_says_so(tmp_path):
    titled_run(tmp_path, languages='en')
    sheet = upload_markdown(tmp_path)
    assert '쇼츠 제목' not in sheet and '`title.en`을 채운 뒤' in sheet


def test_final_produce_makes_shorts_and_upload_text_but_draft_does_not(tmp_path, monkeypatch, capsys):
    calls = []
    report = lambda quality: type('Report', (), {'quality': quality, 'output_mode': 'all'})()
    monkeypatch.setattr(pipeline, 'produce', lambda run, quality, **_: report(quality))
    monkeypatch.setattr('video_harness.shorts.build_shorts', lambda run, quality: calls.append(('shorts', quality)) or [tmp_path / 'shorts-ko.mp4'])
    monkeypatch.setattr('video_harness.upload_text.write_upload_text', lambda run: calls.append(('upload',)) or tmp_path / 'upload.md')
    monkeypatch.setattr('video_harness.delivery.run_delivery', lambda run, automatic: calls.append(('deliver', automatic)) or 0)
    assert pipeline.main([str(tmp_path)]) == 0 and calls == []
    assert pipeline.main([str(tmp_path), '--quality', 'final']) == 0 and calls == [('shorts', 'final'), ('upload',), ('deliver', True)]
    assert 'shorts ready' in capsys.readouterr().out

    def broken(run, quality):
        raise RuntimeError('ffmpeg')
    monkeypatch.setattr('video_harness.shorts.build_shorts', broken)
    calls.clear()
    assert pipeline.main([str(tmp_path), '--quality', 'final']) == 1
    assert not any(call[0] == 'deliver' for call in calls)
    assert 'final video is complete' in capsys.readouterr().out


def test_core_only_cut_keeps_marked_scenes_and_moves_subtitles():
    from video_harness.shorts import cut_cues, _filter_graph
    from pathlib import Path
    segments = [(0.0, 4.0), (10.0, 14.0)]
    cues = [(1.0, 3.0, 'a'), (5.0, 6.0, 'cut'), (10.5, 15.0, 'b')]
    assert cut_cues(cues, segments) == [(1.0, 3.0, 'a'), (4.5, 8.0, 'b')]
    assert cut_cues(cues, None) == cues
    graph = _filter_graph(Path('x.ass'), 1, segments)
    assert "select='gte(t,0.0000)*lt(t,4.0000)+gte(t,10.0000)*lt(t,14.0000)',setpts=N/FRAME_RATE/TB," in graph
    assert "[1:a]aselect='gte(t,0.0000)*lt(t,4.0000)+gte(t,10.0000)*lt(t,14.0000)',asetpts=N/SR/TB,atempo=1.15[au]" in graph
    assert 'select' not in _filter_graph(Path('x.ass'), 1, None)


def test_shorts_length_gate_and_kept_segments(tmp_path):
    from video_harness.shorts import MAX_SECONDS, SPEED, estimated_seconds, kept_segments, require_shorts_length
    from video_harness.sequence_plans import load_local_sequence_plan
    script = make_run(tmp_path)
    assert kept_segments(tmp_path) is None
    assert require_shorts_length(tmp_path) == pytest.approx(8.0 * len(script.scenes) / SPEED)
    script.scenes[0].duration_seconds = MAX_SECONDS * SPEED + 5
    (tmp_path / 'script.json').write_text(script.model_dump_json())
    with pytest.raises(ValueError, match='한도를 넘습니다'):
        require_shorts_length(tmp_path)
    script.scenes[0].in_shorts = False
    (tmp_path / 'script.json').write_text(script.model_dump_json())
    if len(script.scenes) > 1:
        assert require_shorts_length(tmp_path) <= MAX_SECONDS
        local = load_local_sequence_plan(tmp_path / 'local-sequence-plan.json')
        first = min(span.end_frame for seq in local.sequences[:1] for span in seq.scene_spans if span.scene_id == 1)
        assert kept_segments(tmp_path)[0][0] == pytest.approx(first / local.defaults.fps)
    for scene in script.scenes:
        scene.in_shorts = False
    (tmp_path / 'script.json').write_text(script.model_dump_json())
    with pytest.raises(ValueError, match='넣을 장면이 없습니다'):
        require_shorts_length(tmp_path)
    assert estimated_seconds([{'narration': '가나다라마', 'in_shorts': True}, {'narration': '생략', 'in_shorts': False}], 5.0) == pytest.approx(1 / SPEED)
