import json
import shutil
import subprocess

import pytest

from video_harness.shorts import _filter_graph, shorts_ass, subtitle_cues, title_size
from video_harness.shorts_layout import contains, inspect_ass_bounds, load_layout, subtitle_font_size

SRT = "1\n00:00:00,000 --> 00:00:03,000\n{a}\n"


def test_default_layout_matches_the_geomagnetic_shorts_composition():
    # runs/20261010-geomagnetic-dynamo/shorts: title above, 84%-crop picture at full width from y=500, subtitles from y=1279.
    layout = load_layout()
    assert layout['picture_box'] == [0, 500, 1080, 724]
    assert layout['title_box'][0] + layout['title_box'][2] / 2 == 540 and layout['title_box'][1] + layout['title_box'][3] <= 500
    assert layout['subtitle_box'][1] == 1279 and layout['subtitle_box'][0] + layout['subtitle_box'][2] / 2 == 540
    assert layout['title_font_size'] == 92 and layout['picture_fit'] == 'cover'


def test_cover_fit_crops_the_landscape_sides_like_the_approved_shorts(tmp_path):
    graph = _filter_graph(tmp_path / 'x.ass', 0, None, load_layout())
    assert 'scale=1080:724:force_original_aspect_ratio=increase' in graph and 'crop=1080:724' in graph
    assert 'overlay=0+(1080-overlay_w)/2:500+(724-overlay_h)/2' in graph


def test_subtitle_size_follows_language_in_layout():
    layout = load_layout()
    assert subtitle_font_size(layout, 'ko') == 70
    assert subtitle_font_size(layout, 'ja') == 66
    assert subtitle_font_size(layout, 'en') == 64
    style = [line for line in shorts_ass(lang='ko', font='AppleGothic', title='왜?', cues=[]).splitlines() if line.startswith('Style:')]
    assert ',70,' in style[0] and ',92,' in style[1]


def test_layout_rejects_boxes_outside_the_declared_area_or_overlapping(tmp_path):
    layout = load_layout()
    layout['subtitle_box'][1] = 1800
    (tmp_path / 'shorts-layout.json').write_text(json.dumps(layout))
    with pytest.raises(ValueError, match='안전영역'):
        load_layout(tmp_path)
    layout = load_layout()
    layout['title_box'][1] = 450
    (tmp_path / 'shorts-layout.json').write_text(json.dumps(layout))
    with pytest.raises(ValueError, match='겹칩니다'):
        load_layout(tmp_path)


def test_title_shrinks_to_the_layout_title_box_not_a_fixed_width():
    layout = load_layout()
    assert title_size('台風が北西へ進む理由', layout) == 92
    wide = title_size('¿Por qué el tifón va al noroeste? ¿Y por qué no al sur?', layout)
    layout['title_box'][2] = 1400
    assert wide < title_size('¿Por qué el tifón va al noroeste? ¿Y por qué no al sur?', layout)


def test_latin_cues_are_left_for_libass_to_wrap_and_cjk_limit_follows_box_width(tmp_path):
    layout = load_layout()
    (tmp_path / 'es.srt').write_text(SRT.format(a='¿Qué mantiene este metal líquido en movimiento? Nadie lo sabe con certeza todavía.'))
    (tmp_path / 'ja.srt').write_text(SRT.format(a='衛星を引き裂く潮汐力が、まとめる力を上回ることがあります。'))
    assert '\\N' not in subtitle_cues(tmp_path / 'es.srt', 'es', layout)[0][2]
    assert '\\N' not in shorts_ass(lang='es', font='Helvetica Neue', title=None, cues=subtitle_cues(tmp_path / 'es.srt', 'es', layout), layout=layout)
    japanese = subtitle_cues(tmp_path / 'ja.srt', 'ja', layout)[0][2].split('\\N')
    assert max(map(len, japanese)) <= layout['subtitle_box'][2] // 66


def test_probe_failure_is_reported_as_runtime_error(tmp_path, monkeypatch):
    layout = load_layout()
    ass = tmp_path / 'test.ass'
    ass.write_text(shorts_ass(lang='en', font='Helvetica Neue', title=None, cues=[(0, 1, 'North.')], layout=layout))

    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr='libass failed')
    monkeypatch.setattr(subprocess, 'run', boom)
    with pytest.raises(RuntimeError, match='libass failed'):
        inspect_ass_bounds(ass, layout)


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg/libass required')
def test_actual_glyphs_are_checked_not_just_ass_margin_settings(tmp_path):
    layout = load_layout()
    ass = tmp_path / 'test.ass'
    text = shorts_ass(lang='en', font='Helvetica Neue', title='Why north?', cues=[(0, 1, 'North.')])
    ass.write_text(text)
    assert len(inspect_ass_bounds(ass, layout)) == 2
    # A valid style box cannot rescue a dialogue explicitly positioned outside it.
    ass.write_text(text.replace(',,North.', r',,{\pos(500,1700)}North.'))
    with pytest.raises(ValueError, match='영역 초과'):
        inspect_ass_bounds(ass, layout)


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg/libass required')
@pytest.mark.parametrize('lang,font,title,cue', [
    ('es', 'Helvetica Neue', '¿Por qué la brújula apunta al norte?', '¿Qué mantiene este metal líquido en movimiento? Nadie lo sabe con certeza todavía.'),
    ('en', 'Helvetica Neue', 'Why Does a Compass Point North?', 'The core has two parts: a solid inner core and a liquid metal outer core, and it spins.'),
    ('ko', 'Apple SD Gothic Neo', '나침반은 왜 북쪽을 가리킬까?', '그렇다면 지구 안에 거대한 자석이 들어 있어서 바늘을 움직이는 걸까요?'),
    ('ja', 'Hiragino Sans', 'なぜ方位磁針は北を指すのか？', '衛星を引き裂く潮汐力が、まとめる力を上回ることがあります。それでも答えは核の中です。'),
])
def test_real_length_cues_fit_their_boxes_in_every_language(tmp_path, lang, font, title, cue):
    layout = load_layout()
    (tmp_path / f'{lang}.srt').write_text(SRT.format(a=cue))
    ass = tmp_path / 'test.ass'
    ass.write_text(shorts_ass(lang=lang, font=font, title=title, cues=subtitle_cues(tmp_path / f'{lang}.srt', lang, layout), layout=layout))
    bounds = inspect_ass_bounds(ass, layout)
    assert [b['style'] for b in bounds] == ['Title', 'Sub']
