import json

import pytest

from video_harness.settings import (
    HarnessSettings, PromotionSettings, load_project_settings, resolve_run_settings,
    settings_sha256, write_project_settings,
)
from video_harness.tests.test_shorts import titled_run
from video_harness.upload_text import upload_sheet, write_upload_text


def test_personal_promotion_is_saved_separately_and_snapshotted(tmp_path):
    project = tmp_path / 'settings.json'
    settings = HarnessSettings(promotion={'base_url': 'https://example.org/', 'locale_mode': 'language_path'})
    write_project_settings(settings, project)
    assert json.loads(project.read_text())['promotion']['base_url'] == ''
    assert json.loads((tmp_path / 'settings.local.json').read_text())['promotion']['base_url'] == 'https://example.org'
    assert load_project_settings(project) == settings
    run = tmp_path / 'run'
    run.mkdir()
    snapshot = resolve_run_settings(run, settings_file=project, persist=True)
    write_project_settings(HarnessSettings(), project)
    assert load_project_settings(project).promotion.base_url == ''
    assert resolve_run_settings(run, settings_file=project).promotion == snapshot.promotion
    assert resolve_run_settings(run, settings_file=project).promotion.url_for('ja') == 'https://example.org/ja'


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'ftp://example.org', 'not a URL',
                               'https://user:password@example.org', 'https://example.org?x=1', 'https://example.org/#x'])
def test_promotion_rejects_non_web_addresses_and_non_base_urls(url):
    with pytest.raises(ValueError):
        PromotionSettings(base_url=url)


def test_empty_promotion_keeps_old_v6_hash_and_personal_changes_are_detected():
    from video_harness.settings import ArchivedV6HarnessSettings
    settings = ArchivedV6HarnessSettings()
    old = settings.model_dump()
    old.pop('promotion')
    assert settings_sha256(ArchivedV6HarnessSettings.model_validate(old)) == settings_sha256(settings)
    assert settings_sha256(settings) == '1a83ee8dc1f349f8ab1896a10544c3899267397a7e12bd5a2bb6c5ad49753dfc'
    promoted = settings.model_copy(update={'promotion': PromotionSettings(base_url='https://example.org')})
    assert settings_sha256(promoted) != settings_sha256(settings)


@pytest.mark.parametrize('mode', ['shared', 'language_path'])
def test_upload_descriptions_include_each_language_link_before_credits(tmp_path, mode):
    titled_run(tmp_path, languages='en,ja,zh,es')
    snapshot = json.loads((tmp_path / 'run-settings.json').read_text())
    # Test the current settings schema without changing the approved script/translations.
    snapshot['schema_version'] = 6
    snapshot['render'] = HarnessSettings().render.model_dump()
    snapshot['promotion'] = {'base_url': 'https://example.org/site', 'locale_mode': mode}
    snapshot['music'] = {'file': 'Theme.mp3'}
    (tmp_path / 'run-settings.json').write_text(json.dumps(snapshot))
    before = (tmp_path / 'script.json').read_bytes()
    (tmp_path / 'shorts').mkdir()
    for lang in ('ko', 'en', 'ja', 'zh', 'es'):
        (tmp_path / 'shorts' / f'shorts-{lang}.mp4').write_bytes(b'short')
    sheet = upload_sheet(tmp_path)
    markdown = write_upload_text(tmp_path).read_text()
    for entry in sheet['languages']:
        suffix = '/' + entry['lang'] if mode == 'language_path' and entry['lang'] != 'ko' else ''
        url = 'https://example.org' + suffix + '/site'
        for field in ('description', 'shorts_description'):
            assert url in entry[field]
            assert entry[field].count('https://example.org') == 1
            assert entry[field].endswith(': Theme')
        assert url in markdown
    assert (tmp_path / 'script.json').read_bytes() == before
    snapshot['promotion']['base_url'] = ''
    (tmp_path / 'run-settings.json').write_text(json.dumps(snapshot))
    assert 'https://example.org' not in write_upload_text(tmp_path).read_text()


def test_older_runs_do_not_inherit_personal_promotion(tmp_path):
    titled_run(tmp_path, languages='en')
    assert all('웹사이트:' not in entry['description'] and 'Website:' not in entry['description']
               for entry in upload_sheet(tmp_path)['languages'])


def test_korean_only_promotion_does_not_add_foreign_links(tmp_path):
    settings = PromotionSettings(base_url='https://example.org/post/article', locale_mode='ko_only')
    assert settings.url_for('ko') == 'https://example.org/post/article'
    assert all(settings.url_for(lang) == '' for lang in ('en', 'ja', 'zh', 'es'))


def test_run_promotion_override_changes_uploads_without_changing_approved_inputs(tmp_path):
    titled_run(tmp_path, languages='en,ja,zh,es')
    (tmp_path / 'shorts').mkdir()
    for lang in ('ko', 'en', 'ja', 'zh', 'es'):
        (tmp_path / 'shorts' / f'shorts-{lang}.mp4').write_bytes(b'short')
    before = {name: (tmp_path / name).read_bytes() for name in ('script.json', 'translations.json', 'run-settings.json')}
    (tmp_path / 'upload-overrides.json').write_text(json.dumps({
        'promotion': {'base_url': 'https://example.org/post/article', 'locale_mode': 'ko_only'},
        'description': {'en': 'English explanation.'},
    }))
    for entry in upload_sheet(tmp_path)['languages']:
        for field in ('description', 'shorts_description'):
            assert ('https://example.org/post/article' in entry[field]) == (entry['lang'] == 'ko')
        if entry['lang'] == 'en':
            assert entry['description'].startswith('English explanation.')
    assert before == {name: (tmp_path / name).read_bytes() for name in before}


def test_korean_only_mode_removes_web_addresses_from_foreign_copy_and_keeps_credit_names(tmp_path):
    from video_harness.tests.test_shorts import write_glb
    titled_run(tmp_path, languages='en,ja,zh,es')
    write_glb(tmp_path / 'assets' / 'earth.glb', {
        'author': 'Akshat (https://sketchfab.com/author)', 'title': 'Earth',
        'license': 'CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)',
        'source': 'https://sketchfab.com/3d-models/earth',
    })
    (tmp_path / 'shorts').mkdir()
    languages = ('ko', 'en', 'ja', 'zh', 'es')
    for lang in languages:
        (tmp_path / 'shorts' / f'shorts-{lang}.mp4').write_bytes(b'short')
    copy = 'Learn science. [Article](https://example.org/post) www.example.net example.com/path'
    (tmp_path / 'upload-overrides.json').write_text(json.dumps({
        'promotion': {'base_url': 'https://example.org', 'locale_mode': 'ko_only'},
        'description': {lang: copy for lang in languages},
    }))
    sheet = upload_sheet(tmp_path)
    for entry in sheet['languages']:
        for field in ('description', 'shorts_description'):
            text = entry[field]
            assert 'Earth' in text and 'Akshat' in text and 'CC BY 4.0' in text
            if entry['lang'] == 'ko':
                assert 'https://sketchfab.com/' in text and 'http://creativecommons.org/' in text
            else:
                assert 'Learn science.' in text and 'Article' in text
                assert not any(marker in text for marker in ('http', 'www.', 'example.', 'sketchfab.', 'creativecommons.'))
