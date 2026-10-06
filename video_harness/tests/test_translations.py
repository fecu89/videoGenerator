import json
from pathlib import Path
import pytest
from video_harness.language_voices import LanguageVoices, load_language_voices, PROJECT_LANGUAGE_VOICES
from video_harness.translations import (scaffold_translations, write_translations, load_translations,
    translation_issues, speech_estimate_seconds, Translations, TranslatedScene)
from video_harness.tests.test_video_plan_approval import _write_reviewable_run
from video_harness.production import script_sha256
from video_harness.models import ScriptArtifact


def make_run(tmp_path, policy='subtitles', languages='en,ja,zh,es'):
    _write_reviewable_run(tmp_path)
    script = ScriptArtifact.model_validate_json((tmp_path / 'script.json').read_text())
    for scene in script.scenes:
        scene.duration_seconds = 8.0
    (tmp_path / 'script.json').write_text(script.model_dump_json(indent=2) + '\n')
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': policy, 'subtitle_languages': languages}}))
    return script


def test_project_language_voices_cover_all_five_languages():
    voices = LanguageVoices.model_validate_json(PROJECT_LANGUAGE_VOICES.read_text())
    assert set(voices.voices) == {'ko', 'en', 'ja', 'zh', 'es'}
    assert voices.voices['en'].engine == 'kokoro' and voices.voices['zh'].engine == 'qwen3'
    assert voices.voices['ko'].engine is None and voices.voices['ko'].chars_per_line == 22


def test_load_language_voices_copies_project_defaults_into_run(tmp_path):
    voices = load_language_voices(tmp_path)
    assert (tmp_path / 'language-voices.json').is_file()
    assert voices.voices['es'].voice == 'ef_dora'


def test_scaffold_creates_budgeted_empty_scenes_and_protects_existing(tmp_path):
    script = make_run(tmp_path)
    t = scaffold_translations(tmp_path, ['en', 'ja'])
    assert [s.scene_id for s in t.scenes] == [s.scene_id for s in script.scenes]
    assert t.scenes[0].budget_seconds == 8.0 and t.scenes[0].text == {'en': '', 'ja': ''}
    assert t.script_sha256 == script_sha256(tmp_path / 'script.json')
    write_translations(tmp_path, t)
    with pytest.raises(FileExistsError):
        write_translations(tmp_path, t)
    write_translations(tmp_path, t, force=True)
    assert load_translations(tmp_path).languages == ['en', 'ja']


def test_speech_estimate_uses_language_units():
    voices = load_language_voices_default()
    assert speech_estimate_seconds('Hello world.', 'en', voices) == pytest.approx(10 / 11.5)
    assert speech_estimate_seconds('这里有风。', 'zh', voices) == pytest.approx(4 / 4.2)


def load_language_voices_default():
    return LanguageVoices.model_validate_json(PROJECT_LANGUAGE_VOICES.read_text())


def test_translation_issues_cover_stale_missing_unterminated_and_too_long(tmp_path):
    script = make_run(tmp_path)
    voices = load_language_voices_default()
    t = scaffold_translations(tmp_path, ['en', 'zh'])
    for scene in t.scenes:
        scene.text = {'en': 'A short line.', 'zh': '一句话。'}
    sha = script_sha256(tmp_path / 'script.json')
    assert translation_issues(t, script, sha, voices, ['en', 'zh']) == []
    t.scenes[0].text['en'] = ''
    t.scenes[0].text['zh'] = '没有句号'
    issues = translation_issues(t, script, sha, voices, ['en', 'zh'])
    assert any(i.startswith('translation_missing: 1/en') for i in issues)
    assert any(i.startswith('translation_unterminated: 1/zh') for i in issues)
    t.scenes[0].text = {'en': 'x' * 400 + '.', 'zh': '字' * 60 + '。'}
    issues = translation_issues(t, script, sha, voices, ['en', 'zh'])
    assert any(i.startswith('translation_too_long: 1/en') for i in issues)
    assert any(i.startswith('translation_stale') for i in translation_issues(t, script, 'f' * 64, voices, ['en', 'zh']))
    assert any(i.startswith('translation_missing: 1/ja') for i in translation_issues(t, script, sha, voices, ['en', 'zh', 'ja']))


def test_require_translations_gate(tmp_path):
    from video_harness.creative_gates import require_translations
    make_run(tmp_path, policy='legacy')
    require_translations(tmp_path)
    assert json.loads((tmp_path / 'translation-gate.json').read_text())['status'] == 'skipped'
    make_run(tmp_path)
    with pytest.raises(ValueError, match='translations_missing'):
        require_translations(tmp_path)
    t = scaffold_translations(tmp_path, ['en', 'ja', 'zh', 'es'])
    for scene in t.scenes:
        scene.text = {'en': 'A line.', 'ja': '一文。', 'zh': '一句。', 'es': 'Una frase.'}
    write_translations(tmp_path, t)
    require_translations(tmp_path)
    assert json.loads((tmp_path / 'translation-gate.json').read_text())['status'] == 'passed'


def test_require_translations_fails_when_run_settings_is_unreadable(tmp_path):
    from video_harness.creative_gates import require_translations
    make_run(tmp_path)
    (tmp_path / 'run-settings.json').write_text('{not json')
    with pytest.raises(ValueError, match='translations_settings_unreadable'):
        require_translations(tmp_path)


def test_estimates_count_accented_letters_and_accept_quoted_or_ellipsis_endings():
    from video_harness.voice_audio import spoken_unit_count
    assert spoken_unit_count('áéñü') == 4
    voices = load_language_voices_default()
    assert voices.voices['en'].units_per_second == 11.5 and voices.voices['es'].units_per_second == 12.5
    script = None
    t = Translations(script_sha256='a' * 64, languages=['en'], scenes=[TranslatedScene(scene_id=1, budget_seconds=8.0, text={'en': 'He said "wind."'})])
    from video_harness.models import ScriptArtifact
    from video_harness.tests.test_video_plan_approval import _write_reviewable_run
    issues_for = lambda text: [i for i in translation_issues(
        Translations(script_sha256='a' * 64, languages=['en'], scenes=[TranslatedScene(scene_id=1, budget_seconds=8.0, text={'en': text})]),
        _one_scene_script(), 'a' * 64, voices, ['en']) if i.startswith('translation_unterminated')]
    assert issues_for('He said "wind."') == []
    assert issues_for('Wait for it…') == []
    assert issues_for('(And more.)') == []
    assert issues_for('No mark') != []


def _one_scene_script():
    from video_harness.models import ScriptArtifact
    from video_harness.tests.test_sequence_plans import _script
    script = _script()
    script.scenes = script.scenes[:1]
    script.scenes[0].scene_id = 1
    return script
