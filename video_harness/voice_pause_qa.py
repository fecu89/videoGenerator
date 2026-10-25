"""Acoustic pause gate. Uses known synthesis boundaries, not guessed word alignment.

An unsplit phrase must not contain a long unplanned quiet interval. This catches
prosodic breaks even when an ASR transcript would reproduce the input exactly.
It does not claim to recognize words, judge pitch, or replace listening.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pydantic import Field

from .models import ScriptArtifact, StrictModel
from .narration import split_narration_sentences
from .storage import atomic_write

ALGORITHM = 'phrase-rms-settings-v1'
POLICY_NAME = 'voice-pause-policy.json'
DECODE_RATE = 24000
FRAME_MS = 10


class PausePolicy(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    voice: dict[str, object]
    qa: dict[str, float]

    @classmethod
    def from_settings(cls, settings):
        if not hasattr(settings.voice, 'max_internal_pause_ms'):
            raise ValueError('pause QA requires local Qwen/Kokoro voice settings')
        return cls(voice=settings.voice.model_dump(mode='json'), qa={
            'duration_tolerance_seconds': settings.qa.duration_tolerance_seconds,
            'audio_packet_tolerance_seconds': settings.qa.audio_packet_tolerance_seconds})

    @property
    def max_unplanned_pause_ms(self):
        return float(self.voice['max_internal_pause_ms'])

    @property
    def boundary_tolerance_ms(self):
        return self.qa['duration_tolerance_seconds'] * 1000

    @property
    def timing_tolerance_seconds(self):
        return self.qa['duration_tolerance_seconds'] + self.qa['audio_packet_tolerance_seconds']


def gate_name(lang='ko'):
    return 'voice-pause-gate.json' if lang == 'ko' else f'voice-pause-gate-{lang}.json'


def generation_name(lang='ko'):
    return 'voice-generation-report.json' if lang == 'ko' else f'voice-generation-report-{lang}.json'


def load_policy(run: Path, *, create=False, settings=None, refresh=False) -> PausePolicy | None:
    path = Path(run) / POLICY_NAME
    if path.is_file():
        saved = PausePolicy.model_validate_json(path.read_text(encoding='utf-8'))
        if not refresh:
            return saved
    elif not create:
        return None
    if settings is None:
        from .settings import resolve_run_settings
        settings = resolve_run_settings(Path(run), persist=False)
    policy = PausePolicy.from_settings(settings)
    atomic_write(path, policy.model_dump_json(indent=2) + '\n')
    return policy


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_audio(audio, sample_rate, *, policy: PausePolicy, planned=(), speech_spans=()):
    """10 ms RMS windows avoid counting waveform zero crossings as silence.

    Quiet is below -35 dB relative to the 95th percentile window RMS (absolute
    floor 1e-5). Outer silence is ignored for unplanned pauses; declared pauses,
    including the last sentence's tail, are checked against their actual window.
    """
    report = {'status': 'failed', 'issues': [], 'quiet_intervals': []}
    values = np.asarray(audio, dtype=np.float64)
    if (sample_rate <= 0 or values.ndim != 1 or not values.size
            or not np.isfinite(values).all()):
        report['issues'].append({'code': 'invalid_audio'})
        return report
    width = max(1, round(sample_rate * FRAME_MS / 1000))
    starts = np.arange(0, len(values), width)
    counts = np.minimum(width, len(values) - starts)
    rms = np.sqrt(np.add.reduceat(values * values, starts) / counts)
    reference = float(np.percentile(rms, 95))
    if reference <= 1e-4:
        report['issues'].append({'code': 'inaudible_audio'})
        return report
    threshold = max(1e-5, reference * 10 ** (-35 / 20))
    quiet = rms < threshold
    edges = np.diff(np.r_[False, quiet, False].astype(np.int8))
    intervals = [(a * width / sample_rate, min(b * width, len(values)) / sample_rate)
                 for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True)]
    report['quiet_intervals'] = [{'start_seconds': round(a, 4), 'end_seconds': round(b, 4),
                                  'duration_ms': round((b-a)*1000, 1)} for a, b in intervals
                                 if (b-a)*1000 >= 40]
    report['threshold_dbfs'] = round(20 * math.log10(threshold), 2)
    tolerance = policy.boundary_tolerance_ms / 1000
    matched = set()
    previous_end = 0.0
    for pause in planned:
        start = float(pause['start_seconds'])
        end = start + float(pause['duration_ms']) / 1000
        if (not math.isfinite(start + end) or start < previous_end - 1e-6
                or end <= start or end > len(values) / sample_rate + tolerance):
            report['issues'].append({'code': 'invalid_pause_timing', 'start_seconds': start})
            continue
        previous_end = end
        overlaps = [(i, a, b) for i, (a, b) in enumerate(intervals) if a < end and b > start]
        valid = (len(overlaps) == 1 and abs(overlaps[0][1] - start) <= tolerance
                 and abs(overlaps[0][2] - end) <= tolerance
                 and abs((overlaps[0][2] - overlaps[0][1]) - (end-start)) <= tolerance)
        if not valid:
            report['issues'].append({'code': 'planned_pause_mismatch', 'kind': pause['kind'],
                                     'start_seconds': round(start, 4),
                                     'expected_duration_ms': pause['duration_ms']})
        matched.update(i for i, _, _ in overlaps)
    active = np.flatnonzero(~quiet)
    first = active[0] * width / sample_rate
    last = min((active[-1] + 1) * width, len(values)) / sample_rate
    for i, (start, end) in enumerate(intervals):
        tempo = 1.0
        for span in speech_spans:
            if span['start_seconds'] <= (start+end)/2 <= span['end_seconds']:
                tempo = float(span['tempo_factor'])
                break
        if not math.isfinite(tempo) or tempo <= 0:
            report['issues'].append({'code': 'invalid_tempo', 'start_seconds': start})
            continue
        limit = policy.max_unplanned_pause_ms / tempo
        if (i not in matched and start >= first and end <= last
                and (end-start)*1000 > limit + FRAME_MS + 1e-6):
            report['issues'].append({'code': 'unexpected_pause', 'start_seconds': round(start, 4),
                                     'end_seconds': round(end, 4), 'duration_ms': round((end-start)*1000, 1),
                                     'limit_ms': round(limit, 2), 'tempo_factor': tempo})
    report['status'] = 'failed' if report['issues'] else 'passed'
    return report


def raw_pause_rejection(audio, sample_rate, policy):
    if policy is None:
        return None
    result = inspect_audio(audio, sample_rate, policy=policy)
    return json.dumps(result['issues'], ensure_ascii=False) if result['issues'] else None


def _audio_path(run, relative):
    path = (run / relative).resolve()
    if not path.is_relative_to(run.resolve()) or not path.is_file():
        raise ValueError(f'missing or unsafe audio path: {relative}')
    return path


def _scene_text(scene, lang, translations):
    return scene.narration if lang == 'ko' else translations[scene.scene_id]


def _scene_contract(scene, text):
    return {'text': text, 'sentence_pauses': [p.model_dump() for p in scene.sentence_pauses],
            'duration_seconds': scene.duration_seconds, 'audio_file': scene.audio_file}


def check_scene(path, generation, text, policy, *, sentence_pauses=()):
    """Decode the actual encoded file; never certify from generation metadata alone."""
    completed = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'f32le',
                                '-ac', '1', '-ar', str(DECODE_RATE), '-'], capture_output=True)
    if completed.returncode:
        raise ValueError(f'audio_decode_failed: {path.name}')
    audio = np.frombuffer(completed.stdout, dtype='<f4')
    sentences = generation['sentences']
    if [s['text'] for s in sentences] != split_narration_sentences(text):
        raise ValueError('generation_text_mismatch: synthesis timings do not match narration')
    planned = []
    speech_spans = []
    ranges = []
    cursor = 0.0
    leading = float(generation['sentence_leading_margin_ms']) / 1000
    trailing = float(generation['sentence_trailing_margin_ms']) / 1000
    if leading < 0 or trailing < 0:
        raise ValueError('invalid sentence margins')
    typed = policy.voice.get('pause_mode', 'legacy') == 'typed'
    expected_leading = 0 if typed else policy.voice['sentence_leading_margin_ms']
    expected_trailing = policy.voice['sentence_pause_ms'] if typed else policy.voice['sentence_trailing_margin_ms']
    if abs(leading*1000 - expected_leading) > 1e-6 or abs(trailing*1000 - expected_trailing) > 1e-6:
        raise ValueError('pause_settings_mismatch: generation margins differ from effective voice settings')
    for index, sentence in enumerate(sentences, 1):
        duration = float(sentence.get('output_seconds', 0))
        if not math.isfinite(duration) or duration <= leading + trailing:
            raise ValueError('timing_unavailable: encoded sentence output_seconds required')
        if typed:
            from .voice_pauses import sentence_phrases
            parts = sentence_phrases(sentence['text'],
                [c for c in sentence_pauses if c.sentence_index == index], SimpleNamespace(**policy.voice))
            if [p.kind for p in parts[:-1]] != [e['kind'] for e in sentence.get('pause_events', [])]:
                raise ValueError('planned_pause_metadata_mismatch: expected script pause missing or extra')
            if len(parts) > 1 and not sentence.get('phrase_spans'):
                raise ValueError('phrase_timing_unavailable: per-phrase tempo required for split sentences')
        if leading:
            planned.append({'start_seconds': cursor, 'duration_ms': leading*1000, 'kind': 'leading'})
        for event in sentence.get('pause_events', []):
            start = float(event['start_seconds'])
            length = float(event['duration_ms']) / 1000
            if not math.isfinite(start + length) or start < leading or length <= 0 or start + length > duration - trailing + 1e-6:
                raise ValueError('invalid phrase pause timing')
            expected = policy.voice.get(event['kind'] + '_pause_ms')
            if expected is None or abs(length*1000 - expected) > 1e-6:
                raise ValueError('pause_settings_mismatch: planned pause differs from effective voice settings')
            planned.append({**event, 'start_seconds': cursor + start})
        if trailing:
            planned.append({'start_seconds': cursor + duration - trailing,
                            'duration_ms': trailing*1000, 'kind': 'sentence'})
        ranges.append((cursor, cursor + duration, index, sentence['text']))
        for span in sentence.get('phrase_spans') or [
            {'start_seconds': leading, 'end_seconds': duration-trailing,
             'tempo_factor': sentence.get('tempo_factor', 1.0)}]:
            tempo = float(span['tempo_factor'])
            if (not math.isfinite(tempo) or tempo <= 0
                    or tempo > float(policy.voice.get('max_tempo_factor', 1.25)) + 1e-6
                    or not 0 <= span['start_seconds'] < span['end_seconds'] <= duration):
                raise ValueError('invalid phrase tempo or timing')
            speech_spans.append({**span, 'start_seconds': cursor + span['start_seconds'],
                                 'end_seconds': cursor + span['end_seconds']})
        cursor += duration
    if abs(cursor - len(audio) / DECODE_RATE) > policy.timing_tolerance_seconds:
        raise ValueError('timing_duration_mismatch: sentence timings do not cover encoded audio')
    # Legacy margins on adjacent sentences form one audible quiet interval.
    merged = []
    for pause in planned:
        if merged and abs(merged[-1]['start_seconds'] + merged[-1]['duration_ms']/1000 - pause['start_seconds']) < 1e-6:
            merged[-1]['duration_ms'] += pause['duration_ms']
        else:
            merged.append(dict(pause))
    result = inspect_audio(audio, DECODE_RATE, policy=policy, planned=merged, speech_spans=speech_spans)
    for issue in result['issues']:
        position = issue.get('start_seconds', 0)
        for start, end, index, sentence_text in ranges:
            if start <= position <= end:
                issue.update(sentence_index=index, text=sentence_text)
                break
    return result


def _inputs(run, lang):
    script = ScriptArtifact.model_validate_json((run / 'script.json').read_text(encoding='utf-8'))
    generations = json.loads((run / generation_name(lang)).read_text(encoding='utf-8'))
    entries = generations['scenes']
    by_id = {s['scene_id']: s for s in entries}
    if len(by_id) != len(entries):
        raise ValueError('duplicate generation scenes')
    translations = {}
    if lang != 'ko':
        from .translations import load_translations
        translations = {s.scene_id: s.text[lang] for s in load_translations(run).scenes}
    return script, by_id, translations


def build_gate(run, script, generations, translations, policy, *, lang='ko', scene_ids=None, audio_overrides=None):
    """Also used on staging files before a voice publication transaction."""
    result = {'schema_version': 1, 'algorithm': ALGORITHM, 'language': lang, 'status': 'failed',
              'policy_sha256': _digest(policy.model_dump()), 'scenes': [], 'issues': []}
    try:
        previous = run / gate_name(lang)
        try:
            old = json.loads(previous.read_text(encoding='utf-8')) if previous.is_file() else {}
            if not isinstance(old, dict):
                old = {}
        except (OSError, ValueError):
            old = {}
        old_entries = {s['scene_id']: s for s in old.get('scenes', [])}
        for scene in script.scenes:
            text = _scene_text(scene, lang, translations)
            entry = {'scene_id': scene.scene_id, 'status': 'failed', 'issues': []}
            try:
                generation = generations[scene.scene_id]
                relative = scene.audio_file if lang == 'ko' else generation['audio_file']
                path = (audio_overrides or {}).get(scene.scene_id) or _audio_path(run, relative)
                hashes = {'audio_sha256': _sha(path), 'generation_sha256': _digest(generation),
                          'scene_sha256': _digest(_scene_contract(scene, text))}
                prior = old_entries.get(scene.scene_id, {})
                if (scene_ids is not None and scene.scene_id not in scene_ids and old.get('algorithm') == ALGORITHM
                        and old.get('policy_sha256') == result['policy_sha256']
                        and prior.get('status') == 'passed' and all(prior.get(k) == v for k, v in hashes.items())):
                    entry = prior
                else:
                    entry.update(check_scene(path, generation, text, policy,
                        sentence_pauses=scene.sentence_pauses if lang == 'ko' else ()), **hashes)
            except (OSError, ValueError, KeyError, TypeError) as error:
                entry['issues'].append({'code': 'pause_check_unavailable', 'detail': str(error)})
            result['scenes'].append(entry)
        result['status'] = 'passed' if result['scenes'] and all(s['status'] == 'passed' for s in result['scenes']) else 'failed'
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['issues'].append(str(error))
    return result


def invalidate_gate(run, *, lang='ko', reason='generation_in_progress'):
    path = Path(run) / gate_name(lang)
    try:
        previous = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    previous.update(status='failed', issues=[reason])
    atomic_write(path, json.dumps(previous, ensure_ascii=False, indent=2) + '\n')


def check_run(run: Path, *, lang='ko', scene_ids=None):
    run = Path(run).resolve()
    policy = load_policy(run, create=True, refresh=True)
    try:
        script, generations, translations = _inputs(run, lang)
        result = build_gate(run, script, generations, translations, policy, lang=lang, scene_ids=scene_ids)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'status': 'failed', 'scenes': [], 'issues': [str(error)]}
    atomic_write(run / gate_name(lang), json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return result


def gate_issues(run: Path, script=None, *, lang='ko'):
    """Cheap preflight: actual bytes and current narration/timings must match the pass."""
    run = Path(run).resolve()
    if not (run / POLICY_NAME).exists():
        if (run / gate_name(lang)).exists():
            return [f'voice_pause_policy_missing: {lang}; restore {POLICY_NAME} and run check-voice']
        return []  # Historical runs are never opted in merely by rendering them.
    try:
        policy = load_policy(run)
        from .settings import resolve_run_settings
        current_policy = PausePolicy.from_settings(resolve_run_settings(run, persist=False))
        if policy != current_policy:
            return [f'voice_pause_settings_stale: {lang}; run check-voice with current run-settings.json']
        report = json.loads((run / gate_name(lang)).read_text(encoding='utf-8'))
        if (report.get('status') != 'passed' or report.get('algorithm') != ALGORITHM
                or report.get('language') != lang or report.get('policy_sha256') != _digest(policy.model_dump())):
            return [f'voice_pause_gate_failed: {lang}; run check-voice']
        current_script, generations, translations = _inputs(run, lang)
        script = script or current_script
        entries = {s['scene_id']: s for s in report['scenes']}
        if len(entries) != len(report['scenes']) or set(entries) != {s.scene_id for s in script.scenes}:
            return [f'voice_pause_gate_incomplete: {lang}']
        for scene in script.scenes:
            entry = entries[scene.scene_id]
            generation = generations[scene.scene_id]
            relative = scene.audio_file if lang == 'ko' else generation['audio_file']
            hashes = {'audio_sha256': _sha(_audio_path(run, relative)), 'generation_sha256': _digest(generation),
                      'scene_sha256': _digest(_scene_contract(scene, _scene_text(scene, lang, translations)))}
            if entry.get('status') != 'passed' or any(entry.get(k) != v for k, v in hashes.items()):
                return [f'voice_pause_gate_stale: {lang} scene {scene.scene_id}; run check-voice']
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f'voice_pause_gate_unavailable: {lang}: {error}']
    return []


def require_pause_gate(run):
    issues = gate_issues(run)
    if issues:
        raise ValueError('; '.join(issues))


def main(argv=None):
    parser = argparse.ArgumentParser(description='실제 MP3의 의도하지 않은 쉼과 계획된 쉼의 길이를 검사합니다. 음성은 수정하지 않습니다.')
    parser.add_argument('run', type=Path)
    parser.add_argument('--language', choices=['ko', 'en', 'ja', 'zh', 'es'], default='ko')
    args = parser.parse_args(argv)
    try:
        result = check_run(args.run, lang=args.language)
    except (OSError, ValueError) as error:
        print(f'음성 쉼 검사 실패: {error}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'passed' else 1
