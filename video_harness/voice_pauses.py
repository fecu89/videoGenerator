"""Planned phrase boundaries, kept separate from spoken/subtitle text."""
from dataclasses import dataclass, replace
import re


PAUSE_FIELDS = ('pause_mode', 'comma_pause_ms', 'semantic_pause_ms', 'emphasis_pause_ms', 'sentence_pause_ms')


@dataclass(frozen=True)
class Phrase:
    text: str
    kind: str
    pause_ms: int


def cue_offset(sentence, cue):
    anchor = cue.after.strip()
    matches = list(re.finditer(re.escape(anchor), sentence)) if anchor else []
    if len(matches) != 1:
        raise ValueError('sentence_pauses after must match exactly once in its sentence')
    end = matches[0].end()
    if (re.search(r'[가-힣A-Za-z0-9]$', anchor)
            and re.match(r'[가-힣A-Za-z0-9]', sentence[end:])):
        raise ValueError('sentence_pauses must not split a word')
    if sentence[end:end+1] in (',', '，', '、'):
        end += 1
    if not re.search(r'\w', sentence[end:]):
        raise ValueError('sentence_pauses must be inside a sentence, not at its end')
    return end


def sentence_phrases(sentence, cues, settings):
    boundaries = {}
    for match in re.finditer(r'[,，、]', sentence):
        i = match.start()
        if i > 0 and i + 1 < len(sentence) and sentence[i-1].isdigit() and sentence[i+1].isdigit():
            continue
        if re.search(r'\w', sentence[:i]) and re.search(r'\w', sentence[i+1:]):
            boundaries[match.end()] = 'comma'
    seen = set()
    for cue in cues:
        end = cue_offset(sentence, cue)
        if end in seen:
            raise ValueError('sentence_pauses cannot repeat the same boundary')
        seen.add(end)
        boundaries[end] = cue.kind
    parts = []; start = 0
    for end, kind in sorted(boundaries.items()):
        text = sentence[start:end].strip().rstrip(',，、').strip()
        if not re.search(r'\w', text):
            raise ValueError('sentence_pauses must leave spoken text between boundaries')
        parts.append(Phrase(text, kind, getattr(settings, kind + '_pause_ms')))
        start = end
    parts.append(Phrase(sentence[start:].strip(), 'sentence', settings.sentence_pause_ms))
    return parts


def aggregate_sentence_reports(sentences, reports, sentence_ids, kinds, trailing_ms):
    aggregated = []
    for index, sentence in enumerate(sentences):
        selected = [i for i, owner in enumerate(sentence_ids) if owner == index]
        group = [reports[i] for i in selected]
        events = []; cursor = 0.0
        for i in selected:
            report = reports[i]
            if kinds[i] != 'sentence':
                events.append({'kind': kinds[i], 'duration_ms': trailing_ms[i],
                               'start_seconds': cursor + report.output_seconds - trailing_ms[i] / 1000})
            cursor += report.output_seconds
        aggregated.append(replace(group[0], text=sentence,
            token_count=sum(r.token_count for r in group) if all(r.token_count is not None for r in group) else None,
            processing_time_seconds=sum(r.processing_time_seconds for r in group) if all(r.processing_time_seconds is not None for r in group) else None,
            peak_memory_usage=max((r.peak_memory_usage for r in group if r.peak_memory_usage is not None), default=None),
            attempt_count=sum(r.attempt_count for r in group),
            sample_count=sum(r.sample_count for r in group),
            spoken_units=sum(r.spoken_units for r in group),
            raw_speech_seconds=sum(r.raw_speech_seconds for r in group),
            adjusted_speech_seconds=sum(r.adjusted_speech_seconds for r in group),
            target_output_seconds=sum(r.target_output_seconds for r in group),
            output_seconds=cursor, tempo_factor=max(r.tempo_factor for r in group),
            target_reached=all(r.target_reached for r in group),
            original_longest_internal_pause_ms=max(r.original_longest_internal_pause_ms for r in group),
            longest_internal_pause_ms=max([r.longest_internal_pause_ms for r in group] +
                                          [e['duration_ms'] for e in events]),
            pause_events=tuple(events)))
    return aggregated
