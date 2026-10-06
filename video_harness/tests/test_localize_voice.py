import json
import pytest
from video_harness.localize_voice import generate_language_audio, generate_all_languages, engine_order
from video_harness.language_voices import load_language_voices
from video_harness.settings import HarnessSettings
from video_harness.translations import scaffold_translations, write_translations
from video_harness.tests.test_translations import make_run
from video_harness.voice_audio import AudioResult, SceneGeneration, SentenceGeneration, SceneFitError


def filled_run(tmp_path, languages='en,ja,zh,es'):
    script = make_run(tmp_path, languages=languages)
    for scene in script.scenes:
        (tmp_path / scene.audio_file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / scene.audio_file).write_bytes(b'ko')
    t = scaffold_translations(tmp_path, languages.split(','))
    for scene in t.scenes:
        scene.text = {lang: f'Scene {scene.scene_id} in {lang}.' for lang in languages.split(',')}
    write_translations(tmp_path, t, force=True)
    (tmp_path / 'voice-generation-report.json').write_text('{"schema_version": 1, "scenes": []}')
    return script


class FakeLanguageSynthesizer:
    def __init__(self, *, fail_scene=None):
        self.closed = False; self.fail_scene = fail_scene; self.seen_targets = None; self.seen_texts = []

    def bind(self, scene_targets):
        self.seen_targets = dict(scene_targets)

    def synthesize(self, scenes, destinations):
        results = []
        for scene in scenes:
            self.seen_texts.append(scene.narration)
            if scene.scene_id == self.fail_scene:
                raise SceneFitError(scene.scene_id, 1.4)
            destinations[scene.scene_id].parent.mkdir(parents=True, exist_ok=True)
            destinations[scene.scene_id].write_bytes(b'mp3')
            sentence = SentenceGeneration(text=scene.narration, seed=0, instruction_sha256='0' * 64, sample_count=24000,
                                          token_count=None, processing_time_seconds=None, peak_memory_usage=None, tempo_factor=1.1)
            gen = SceneGeneration(narrative_role=scene.narrative_role, sample_rate=24000, sample_count=24000,
                                  sentence_leading_margin_ms=100, sentence_trailing_margin_ms=950, sentences=(sentence,), tempo_factor=1.1)
            results.append(AudioResult(scene.scene_id, destinations[scene.scene_id], 7.5, gen, {'engine': 'fake'}))
        return results

    def close(self):
        self.closed = True


def factory_with(record):
    def factory(lang, voice_cfg, settings, scene_targets):
        synth = FakeLanguageSynthesizer(); synth.bind(scene_targets); record[lang] = synth; return synth
    return factory


def test_generate_language_audio_writes_files_report_and_gate(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    script = filled_run(tmp_path)
    record = {}
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en,ja,zh,es'})
    before_script = (tmp_path / 'script.json').read_bytes(); before_report = (tmp_path / 'voice-generation-report.json').read_bytes()

    report = generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=factory_with(record))

    assert record['en'].seen_targets == {s.scene_id: s.duration_seconds for s in script.scenes}
    assert record['en'].seen_texts == [f'Scene {s.scene_id} in en.' for s in script.scenes]
    assert record['en'].closed
    assert list((tmp_path / 'audioFiles' / 'en').glob('*.mp3'))
    payload = json.loads((tmp_path / 'voice-generation-report-en.json').read_text())
    assert payload['language'] == 'en' and payload['engine'] == 'kokoro' and payload['voice'] == 'af_heart'
    assert payload['scenes'][0]['target_seconds'] == 8.0 and payload['scenes'][0]['tempo_factor'] == 1.1
    assert payload['scenes'][0]['sentences'][0]['sample_count'] == 24000
    assert len(payload['language_voices_sha256']) == 64
    assert json.loads((tmp_path / 'translation-fit-gate-en.json').read_text())['status'] == 'passed'
    assert (tmp_path / 'script.json').read_bytes() == before_script
    assert (tmp_path / 'voice-generation-report.json').read_bytes() == before_report
    assert report.language == 'en'


def test_scene_fit_error_fails_the_fit_gate(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    filled_run(tmp_path)
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'})
    def factory(lang, voice_cfg, settings, scene_targets):
        return FakeLanguageSynthesizer(fail_scene=1)
    with pytest.raises(ValueError, match='scene_too_long: 1'):
        generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=factory)
    assert json.loads((tmp_path / 'translation-fit-gate-en.json').read_text())['status'] == 'failed'


def test_engine_order_groups_qwen_first_then_kokoro(tmp_path):
    voices = load_language_voices(tmp_path)
    assert engine_order(['en', 'ja', 'zh', 'es'], voices) == ['zh', 'en', 'ja', 'es']


def test_generate_all_languages_runs_every_target(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    filled_run(tmp_path)
    record = {}
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en,ja,zh,es'})
    reports = generate_all_languages(tmp_path, settings=settings, synthesizer_factory=factory_with(record))
    assert [r.language for r in reports] == ['zh', 'en', 'ja', 'es']
    assert all(s.closed for s in record.values())


def test_fit_error_keeps_other_scenes_and_lists_every_failure(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    script = filled_run(tmp_path)
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'})
    def factory(lang, voice_cfg, settings, scene_targets):
        return FakeLanguageSynthesizer(fail_scene=script.scenes[0].scene_id)
    with pytest.raises(ValueError, match='scene_too_long'):
        generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=factory)
    produced = sorted(p.name for p in (tmp_path / 'audioFiles' / 'en').glob('*.mp3'))
    assert len(produced) == len(script.scenes) - 1


def test_language_report_carries_provenance_and_rejects_overlong_audio(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    filled_run(tmp_path)
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'})
    record = {}
    generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=factory_with(record))
    payload = json.loads((tmp_path / 'voice-generation-report-en.json').read_text())
    assert len(payload['translations_sha256']) == 64 and len(payload['script_sha256']) == 64
    assert module.language_audio_issues(tmp_path, 'en') == []
    # Formatting-only edits and other languages do not stale this language's audio.
    path = tmp_path / 'translations.json'
    path.write_text(path.read_text() + '\n')
    data = json.loads(path.read_text()); data['scenes'][0]['text']['ja'] = '別の文です。'
    path.write_text(json.dumps(data, ensure_ascii=False))
    assert module.language_audio_issues(tmp_path, 'en') == []
    data['scenes'][1]['text']['en'] = 'A changed sentence.'
    path.write_text(json.dumps(data, ensure_ascii=False))
    stale = module.language_audio_issues(tmp_path, 'en')
    assert stale == [f"language_audio_stale: en translations changed for scenes [{data['scenes'][1]['scene_id']}] since the audio was made"]

    class LongSynth(FakeLanguageSynthesizer):
        def synthesize(self, scenes, destinations):
            results = super().synthesize(scenes, destinations)
            return [AudioResult(r.scene_id, r.path, 9.5, r.generation, r.provenance) for r in results]
    def factory(lang, voice_cfg, settings, scene_targets):
        return LongSynth()
    with pytest.raises(ValueError, match='duration_over_target'):
        generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=factory, force=True)


def test_all_languages_reuse_one_synthesizer_per_engine(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    filled_run(tmp_path)
    created = []
    class Reusable(FakeLanguageSynthesizer):
        def configure(self, *, voice, lang_code, scene_target_seconds):
            self.bind(scene_target_seconds)
    def factory(lang, voice_cfg, settings, scene_targets):
        synth = Reusable(); synth.bind(scene_targets); created.append((lang, voice_cfg.engine)); return synth
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en,ja,zh,es'})
    generate_all_languages(tmp_path, settings=settings, synthesizer_factory=factory)
    assert [c[1] for c in created] == ['qwen3', 'kokoro']


def test_model_errors_write_a_failed_fit_gate(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    filled_run(tmp_path)
    (tmp_path / 'translation-fit-gate-en.json').write_text('{"status": "passed", "issues": []}')
    class Broken(FakeLanguageSynthesizer):
        def synthesize(self, scenes, destinations):
            raise RuntimeError('model exploded')
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'})
    with pytest.raises(RuntimeError, match='model exploded'):
        generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=lambda *a: Broken())
    gate = json.loads((tmp_path / 'translation-fit-gate-en.json').read_text())
    assert gate['status'] == 'failed' and gate['issues'][0].startswith('synthesis_error')


def test_reports_without_text_hashes_compare_the_sentences_actually_spoken(tmp_path, monkeypatch):
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])
    filled_run(tmp_path)
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'})
    generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=factory_with({}))
    report_path = tmp_path / 'voice-generation-report-en.json'
    report = json.loads(report_path.read_text())
    for scene in report['scenes']:
        scene.pop('text_sha256')
    report_path.write_text(json.dumps(report))
    path = tmp_path / 'translations.json'
    data = json.loads(path.read_text()); data['scenes'][0]['text']['es'] = 'Otra frase.'
    path.write_text(json.dumps(data, ensure_ascii=False))
    assert module.language_audio_issues(tmp_path, 'en') == []
    data['scenes'][0]['text']['en'] = 'Edited after synthesis.'
    path.write_text(json.dumps(data, ensure_ascii=False))
    assert module.language_audio_issues(tmp_path, 'en')[0].startswith('language_audio_stale: en translations changed for scenes')


def test_language_report_keeps_encoded_sentence_lengths_for_subtitles(tmp_path, monkeypatch):
    import dataclasses
    import video_harness.localize_voice as module
    monkeypatch.setattr(module, 'audio_health_issues', lambda path: [])

    class Measured(FakeLanguageSynthesizer):
        def synthesize(self, scenes, destinations):
            results = []
            for r in super().synthesize(scenes, destinations):
                sentences = tuple(dataclasses.replace(s, output_seconds=2.345, adjusted_speech_seconds=1.295)
                                  for s in r.generation.sentences)
                results.append(dataclasses.replace(r, generation=dataclasses.replace(r.generation, sentences=sentences)))
            return results

    filled_run(tmp_path)
    settings = HarnessSettings(local_video={'text_policy': 'subtitles', 'subtitle_languages': 'en'})
    generate_language_audio(tmp_path, 'en', settings=settings, synthesizer_factory=lambda *a: Measured())
    sentence = json.loads((tmp_path / 'voice-generation-report-en.json').read_text())['scenes'][0]['sentences'][0]
    assert sentence['output_seconds'] == 2.345 and sentence['adjusted_speech_seconds'] == 1.295
