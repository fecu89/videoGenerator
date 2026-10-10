import json
from pathlib import Path

import pytest

from video_harness.settings import HarnessSettings, load_project_settings, resolve_run_settings, settings_sha256
from video_harness.settings_catalog import settings_catalog, settings_sections

FIXTURE = Path(__file__).with_name('fixtures') / 'archived-v5-custom.json'


def test_preview_is_fixed_and_not_serialized_or_editable():
    settings = HarnessSettings()
    assert settings.schema_version == 7
    render = settings.render
    assert (render.draft_width, render.draft_height, render.draft_fps) == (384, 216, 9)
    assert (render.preview_interval_seconds, render.contact_sheet_columns) == (.5, 8)
    assert set(render.model_dump()) == {'final_width', 'final_height', 'final_fps', 'x264_preset', 'x264_crf'}
    with pytest.raises(ValueError):
        HarnessSettings(render={'draft_width': 100})


def test_project_v5_migrates_without_resetting_custom_values_or_writing(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_bytes(FIXTURE.read_bytes())
    before = path.read_bytes()
    settings = load_project_settings(path)
    assert settings.schema_version == 7
    assert settings.local_video.camera_transition_seconds == .4
    assert settings.local_video.target_beat_max_seconds == 6
    assert settings.music.gain_db == -8
    assert path.read_bytes() == before


def test_v5_run_retains_preview_values_hash_and_bytes(tmp_path):
    path = tmp_path / 'run-settings.json'
    path.write_bytes(FIXTURE.read_bytes())
    before = path.read_bytes()
    settings = resolve_run_settings(tmp_path)
    assert settings.schema_version == 5
    assert settings_sha256(settings) == 'f8805cfb15f43f342766693c11214a32dbf8897ddbfe9793e7f2a72416e7304a'
    assert 'draft_width' in settings.render.model_dump()
    assert path.read_bytes() == before
    # A historical run is not changed to the new preview constants.
    payload = json.loads(before)
    payload['render'].update(draft_width=960, draft_height=540, draft_fps=15)
    path.write_text(json.dumps(payload))
    restored = resolve_run_settings(tmp_path)
    assert (restored.render.draft_width, restored.render.draft_height, restored.render.draft_fps) == (960, 540, 15)


def test_details_are_advanced_but_preview_controls_stay_removed():
    assert [s.id for s in settings_sections()] == ['pace', 'basic', 'sound', 'output', 'advanced']
    items = {item.key: item for item in settings_catalog()}
    model = HarnessSettings().model_dump()
    expected = {f'{group}.{field}' for group, values in model.items()
                if isinstance(values, dict) and group != 'pacing' for field in values}
    assert set(items) == expected
    basic = {key for key, item in items.items() if not item.advanced}
    assert basic == {'voice.instructions_file', 'voice.emotion_mode', 'music.file', 'music.gain_db',
                     'local_video.text_policy', 'local_video.subtitle_languages', 'local_video.localized_delivery',
                     'promotion.base_url', 'promotion.locale_mode'}
    assert items['voice.max_tempo_factor'].section == 'advanced'
    assert items['qa.black_frame_threshold'].section == 'advanced'
    assert 'render.draft_width' not in items


def test_fixed_preview_budget_follows_output_aspect_without_new_controls():
    portrait = HarnessSettings(render={'final_width': 1080, 'final_height': 1920}).render
    square = HarnessSettings(render={'final_width': 1080, 'final_height': 1080}).render
    assert (portrait.draft_width, portrait.draft_height) == (216, 384)
    assert (square.draft_width, square.draft_height) == (384, 384)
    assert portrait.draft_fps == square.draft_fps == 9
