"""Versioned Shorts composition, separate from approved main-film settings.

The default follows the approved shorts of runs/20261010-geomagnetic-dynamo:
title above, the landscape picture across the full width, subtitles below.
See docs/shorts-safe-area.md.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name('shorts-safe-layout.json')
OUTLINE, SHADOW = 3, 1


def contains(outer, inner):
    x, y, w, h = outer
    a, b, c, d = inner
    return w > 0 and h > 0 and c > 0 and d > 0 and x <= a and y <= b and a+c <= x+w and b+d <= y+h


def load_layout(run_dir: Path | None = None) -> dict:
    """Explicit run override wins; never mutate run-settings or approval hashes."""
    path = Path(run_dir) / 'shorts-layout.json' if run_dir else DEFAULT_PATH
    if not path.is_file():
        path = DEFAULT_PATH
    layout = json.loads(path.read_text(encoding='utf-8'))
    if layout.get('schema_version') != 1 or layout.get('canvas') != [1080, 1920]:
        raise ValueError('쇼츠 배치 버전/캔버스가 올바르지 않습니다.')
    for key in ('safe_area', 'title_box', 'picture_box', 'subtitle_box'):
        box = layout.get(key)
        if not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box):
            raise ValueError(f'쇼츠 영역 좌표가 올바르지 않습니다: {key}')
    if not contains((0, 0, 1080, 1920), layout['safe_area']):
        raise ValueError('쇼츠 안전영역이 화면을 벗어납니다.')
    if layout.get('picture_fit', 'cover') not in ('cover', 'contain'):
        raise ValueError('쇼츠 그림 맞춤은 cover 또는 contain이어야 합니다.')
    boxes = [layout[key] for key in ('title_box', 'picture_box', 'subtitle_box')]
    if any(not contains(layout['safe_area'], box) for box in boxes):
        raise ValueError('쇼츠 제목/그림/자막 영역이 안전영역을 벗어납니다.')
    if any(a[1]+a[3] > b[1] for a, b in zip(boxes, boxes[1:])):
        raise ValueError('쇼츠 제목/그림/자막 영역이 겹칩니다.')
    sizes = {key: layout.get(key) for key in ('title_font_size', 'subtitle_font_size')}
    sizes.update(layout.get('subtitle_font_size_by_language') or {})
    for key, size in sizes.items():
        if type(size) is not int or not 40 <= size <= 96:
            raise ValueError(f'쇼츠 글자 크기가 올바르지 않습니다: {key}')
    return layout


def subtitle_font_size(layout: dict, lang: str) -> int:
    return (layout.get('subtitle_font_size_by_language') or {}).get(lang, layout['subtitle_font_size'])


def cjk_chars_per_line(layout: dict, lang: str) -> int:
    """Japanese and Chinese have no spaces for libass to wrap at: full-width glyphs are
    about one em wide, so this many fit the subtitle box at the language's size."""
    return max(4, layout['subtitle_box'][2] // subtitle_font_size(layout, lang))


def ass_style(name: str, font: str, layout: dict, size: int) -> str:
    """Top-aligned style whose margins are the box inset by the outline and shadow, so
    libass (WrapStyle 0) wraps the glyph advances inside and the strokes still fit the box."""
    key = 'title' if name == 'Title' else 'subtitle'
    x, y, w, _ = layout[key+'_box']
    color = '&H0078D7FF' if name == 'Title' else '&H00FFFFFF'
    inset = OUTLINE + SHADOW
    return (f'Style: {name},{font},{size},{color},&H00FFFFFF,&H00201A0F,&H80000000,1,0,0,0,100,100,0,0,1,'
            f'{OUTLINE},{SHADOW},8,{x+inset},{1080-x-w+inset},{y},1')


def picture_filter(layout: dict, *, source: str = 'fg') -> str:
    """`cover` fills the picture box and crops the landscape sides (the approved shorts keep
    84% of the width); `contain` fits the whole picture inside. Never stretches."""
    _, _, w, h = layout['picture_box']
    if layout.get('picture_fit', 'cover') == 'contain':
        return f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,setsar=1[{source}]'
    return f'scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1[{source}]'


def inspect_ass_bounds(ass: Path, layout: dict) -> list[dict]:
    """Rasterize every actual dialogue with libass and reject overflow before encode.

    This checks glyph bounds, not the meaning/visibility of 3D objects or phone UI.
    Fonts, wrapping and outlines are measured by the production renderer on a black
    canvas; the 1px black shadow is invisible there and is not counted.
    """
    from .localize import ass_filter_argument

    source = ass.read_text(encoding='utf-8').splitlines()
    events = [line.split(',', 9) for line in source if line.startswith('Dialogue:')]
    if not events:
        return []
    lines = [line for line in source if not line.startswith('Dialogue:')]
    for i, event in enumerate(events):
        def stamp(n):
            return f'{n//3600}:{n//60%60:02}:{n%60:02}.00'
        fields = event.copy()
        fields[1:3] = [stamp(i), stamp(i+1)]
        lines.append(','.join(fields))
    with tempfile.TemporaryDirectory(prefix='shorts-glyphs-') as tmp:
        check = Path(tmp) / 'bounds.ass'
        check.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        try:
            result = subprocess.run(['ffmpeg', '-hide_banner', '-f', 'lavfi', '-i',
                f'color=c=black:s=1080x1920:r=1:d={len(events)}', '-vf',
                f'{ass_filter_argument(check)},bbox=min_val=17', '-an', '-f', 'null', '-'],
                capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f'쇼츠 글자 실측 실패: {(error.stderr or "").strip()[-400:]}') from error
    found = re.findall(r'n:(\d+).*?x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)', result.stderr)
    if len(found) != len(events):
        raise ValueError('쇼츠 글자 실측 실패: 빈 글자/누락 프레임을 확인하세요.')
    evidence = []
    for n, x1, x2, y1, y2 in found:
        index, x1, x2, y1, y2 = map(int, (n, x1, x2, y1, y2))
        event = events[index]
        box = layout['title_box' if event[3] == 'Title' else 'subtitle_box']
        bounds = [x1, y1, x2-x1+1, y2-y1+1]
        if not contains(box, bounds):
            raise ValueError(f'쇼츠 글자 영역 초과: {ass.name} {event[3]} {event[-1]} {bounds} / {box}')
        evidence.append({'event': index, 'style': event[3], 'bounds': bounds})
    return evidence
