"""New Blender galleries must not keyframe hide_render/hide_viewport.

Objects that carry both transform keys and visibility keys make EEVEE rebuild
the scene on every render: in the phantom-jam film (626 objects) a 384x216
frame took ~2.3 s instead of ~0.5 s. Park off-stage objects out of view and
fade overlays through their animated opacity instead. The listed galleries
predate the rule and are frozen by approved renderer hashes.
"""
import re
from pathlib import Path
import pytest

BLENDER = Path(__file__).resolve().parents[1] / 'blender_renderer'
LEGACY = {'bonding.py', 'bonding_flow.py', 'coriolis_story.py', 'eclipse.py', 'vorticity.py', 'vorticity_story.py'}
VISIBILITY_KEY = re.compile(
    r"keyframe_insert\([^)]*hide_(?:render|viewport)"
    r"|for\s+\w+\s+in\s*[\(\[][^\)\]]*['\"]hide_(?:render|viewport)['\"]")


def sources():
    return sorted(p for p in BLENDER.glob('*.py') if p.name not in LEGACY)


def test_legacy_list_only_names_existing_files():
    assert LEGACY <= {p.name for p in BLENDER.glob('*.py')}


def test_pattern_catches_both_styles():
    assert VISIBILITY_KEY.search("o.keyframe_insert(data_path='hide_render',frame=f)")
    assert VISIBILITY_KEY.search("for prop in ('location', 'hide_viewport'):")
    assert not VISIBILITY_KEY.search("for prop in ('location', 'rotation_euler'):")


@pytest.mark.parametrize('path', sources(), ids=lambda p: p.name)
def test_new_galleries_do_not_keyframe_visibility(path):
    hits = [m.group(0) for m in VISIBILITY_KEY.finditer(path.read_text(encoding='utf-8'))]
    assert not hits, (f'{path.name} keyframes visibility {hits}; park objects out of view '
                      'or fade their opacity (see docs/blender-rendering.md)')
