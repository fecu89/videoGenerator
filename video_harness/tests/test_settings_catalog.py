import json

from video_harness.settings import HarnessSettings
from video_harness.settings_catalog import (
    editable_setting_keys, settings_catalog, settings_catalog_payload,
    settings_sections, settings_sections_payload,
)


def test_catalog_contains_only_supported_operator_choices():
    settings = HarnessSettings().model_dump(mode='json')
    keys = [item.key for item in settings_catalog()]
    assert len(keys) == len(set(keys)) == 59
    assert editable_setting_keys() == frozenset(keys)
    for key in keys:
        group, field = key.split('.')
        assert field in settings[group]
    assert len([item for item in settings_catalog() if not item.advanced]) == 9
    assert all(item.advanced for item in settings_catalog() if item.key.startswith(('render.', 'qa.')))
    assert 'render.draft_width' not in keys
    assert 'voxcpm' not in json.dumps(settings_catalog_payload()).lower()


def test_catalog_sections_have_stable_order_and_korean_copy():
    sections = settings_sections()
    assert [section.id for section in sections] == ['pace', 'basic', 'sound', 'output', 'advanced']
    assert sections[0].label == '영상 템포'
    assert all(section.description for section in sections)


def test_all_controls_have_copy_and_valid_metadata():
    section_ids = {section.id for section in settings_sections()}
    for item in settings_catalog():
        assert item.section in section_ids
        assert item.label.strip() and item.description.strip()
        if item.control == 'select':
            assert item.options
        else:
            assert not item.options
        if item.control == 'range':
            assert item.ui_min < item.ui_max
            assert item.step > 0
    gain = next(item for item in settings_catalog() if item.key == 'music.gain_db')
    assert (gain.ui_min, gain.ui_max, gain.step, gain.unit) == (-40, 0, .5, 'dB')
    pause = next(item for item in settings_catalog() if item.key == 'voice.max_internal_pause_ms')
    assert (pause.ui_min, pause.ui_max, pause.step, pause.unit) == (50, 800, 10, 'ms')


def test_catalog_payloads_are_plain_json_values():
    payload = {'sections': settings_sections_payload(), 'catalog': settings_catalog_payload()}
    assert '음악 크기' in json.dumps(payload, ensure_ascii=False)
    assert isinstance(payload['catalog'][0]['options'], list)
