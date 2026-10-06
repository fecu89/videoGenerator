"""New renderers draw text only through CalloutLayer; legacy galleries are frozen by hash."""
import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
BLENDER = ROOT / 'blender_renderer'
THREEJS = ROOT / 'science_renderer/src/sequences'
LEGACY_BLENDER = {'scene.py', 'vorticity_story.py', 'vorticity.py', 'vorticity_direction.py', 'bonding.py', 'bonding_flow.py',
                  'eclipse.py', 'eclipse_continuity.py', 'blackbody_presentation.py', 'blackbody_gallery.py',
                  'distance_flight.py', 'optics_journey.py', 'directed_optics.py'}
LEGACY_THREEJS = {'apparent-motion.ts', 'apparent-motion-full-cycle.ts', 'stellar-spectra.ts'}
INFRASTRUCTURE = {'callout.py', 'callout_math.py', 'worker.py', '__init__.py', 'continuity_capture.py', 'animated_materials.py', 'spectra.py'}
DIRECT_TEXT = re.compile(r"\b(self|g|gallery)\.text\(|\bcaption\(|\bhud\(|\btitle\(|^\s*LABELS\s*=|\bsmall\(", re.M)
DIRECT_TEXT_TS = re.compile(r"\bthis\.text\(|\bfillText\(|titles\s*:\s*Record<string,\s*string\[\]>")


def python_sources():
    return sorted(p for p in BLENDER.glob('*.py') if p.name not in LEGACY_BLENDER | INFRASTRUCTURE and not p.name.endswith('_math.py'))


def threejs_sources():
    return sorted(p for p in THREEJS.glob('*.ts') if p.name not in LEGACY_THREEJS)


def test_legacy_lists_only_name_existing_files():
    assert LEGACY_BLENDER <= {p.name for p in BLENDER.glob('*.py')}
    assert LEGACY_THREEJS <= {p.name for p in THREEJS.glob('*.ts')}


@pytest.mark.parametrize('path', python_sources(), ids=lambda p: p.name)
def test_new_blender_galleries_use_callout_layer_only(path):
    source = path.read_text(encoding='utf-8')
    hits = [m.group(0) for m in DIRECT_TEXT.finditer(source)]
    assert not hits, f'{path.name} draws text directly: {hits}; use CalloutLayer'
    if 'class ' in source and 'Gallery' in source:
        assert 'CalloutLayer' in source, f'{path.name} must bind CalloutLayer'


@pytest.mark.parametrize('path', threejs_sources(), ids=lambda p: p.name)
def test_new_threejs_sequences_use_callout_layer_only(path):
    source = path.read_text(encoding='utf-8')
    hits = [m.group(0) for m in DIRECT_TEXT_TS.finditer(source)]
    assert not hits, f'{path.name} draws text directly: {hits}; use CalloutLayer'


def test_policy_catches_a_direct_text_call():
    sample = "class DemoGallery:\n    def build(self):\n        self.text('제목', 0, 0, 1.56)\n"
    assert DIRECT_TEXT.search(sample)
    assert not DIRECT_TEXT.search("from callout import CalloutLayer\nself.callouts=CalloutLayer(self)\n")
