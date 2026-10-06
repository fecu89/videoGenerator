"""Keyword label contract: the plan owns on-screen text; renderers only draw it."""
from __future__ import annotations
import re
from collections.abc import Mapping
from typing import Literal
from pydantic import Field, ValidationError
from .models import StrictModel
from .blender_renderer import callout_math as _cm

Side = Literal['top', 'bottom', 'left', 'right']
Emphasis = Literal['none', 'glow', 'scale']
Kind = Literal['word', 'formula', 'unit']
Size = Literal['large', 'small', 'xlarge']
MAX_WORD_CHARS = 8
MAX_COUNTED_LABELS = 2
MAX_UNIT_LABELS = 4
REVIEW_FIELDS = ('review_visual_description', 'review_framing', 'review_camera_movement')
_SENTENCE_MARKS = re.compile(r'[.。?？!！→←↔⇒·]')
_ENDINGS = ('다', '요', '까')
_PARTICLES = ('은', '는', '이', '가', '을', '를', '의', '에', '로', '와', '과')
_QUOTED = re.compile(r'([‘“"\'])([^‘’“”"\']{2,})([’”"\'])')


class Label(StrictModel):
    text: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    side: Side = 'right'
    emphasis: Emphasis = 'glow'
    kind: Kind = 'word'
    size: Size = 'large'


class ScientificGraph(StrictModel):
    """Explicitly requested scientific axes, separate from explanatory captions."""
    x_label: str = Field(min_length=1, max_length=20)
    y_label: str = Field(min_length=1, max_length=20)
    ticks: list[str] = Field(default_factory=list, max_length=16)


def graph_texts(options):
    raw = options.get('scientific_graph')
    if raw is None:
        return set()
    graph = ScientificGraph.model_validate(raw)
    if any(not re.fullmatch(r'[0-9.+−%-]{1,8}', tick) for tick in graph.ticks):
        raise ValueError('scientific graph ticks must be numeric')
    return {graph.x_label, graph.y_label, *graph.ticks}


def sentence_like(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _SENTENCE_MARKS.search(stripped):
        return True
    # Morphology is only checked on multi-token phrases so single nouns such as
    # 와도, 바다, 높이 are never mistaken for particles or verb endings.
    if ' ' not in stripped:
        return False
    return stripped.endswith(_ENDINGS) or stripped.endswith(_PARTICLES)


def parse_labels(options: Mapping[str, object]) -> list[Label]:
    raw = options.get('labels', [])
    if not isinstance(raw, list):
        raise ValueError('labels must be a list')
    try:
        return [Label.model_validate(item) for item in raw]
    except ValidationError as error:
        raise ValueError(str(error).splitlines()[0] + ' …') from error


def beat_label_issues(beat_id: str, options: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    try:
        labels = parse_labels(options)
    except ValueError as error:
        return [f'label_field_invalid: {beat_id} {error}']
    counted = [l for l in labels if l.kind != 'unit']
    units = [l for l in labels if l.kind == 'unit']
    if len(counted) > MAX_COUNTED_LABELS:
        issues.append(f'label_count_exceeded: {beat_id} {len(counted)} word/formula labels > {MAX_COUNTED_LABELS}')
    if len(units) > MAX_UNIT_LABELS:
        issues.append(f'label_count_exceeded: {beat_id} {len(units)} unit labels > {MAX_UNIT_LABELS}')
    for label in labels:
        if label.kind != 'formula' and len(label.text) > MAX_WORD_CHARS:
            issues.append(f'label_text_too_long: {beat_id} {label.text!r} > {MAX_WORD_CHARS} chars')
        if label.kind == 'word' and (sentence_like(label.text) or label.text.count(' ') > 1):
            issues.append(f'label_text_sentence: {beat_id} {label.text!r}')
    for field in REVIEW_FIELDS:
        value = options.get(field)
        if isinstance(value, str):
            for match in _QUOTED.finditer(value):
                issues.append(f'label_hidden_in_prose: {beat_id} {field} {match.group(0)}')
    return issues


def plan_text_issues(local: Mapping[str, object], *, policy: str = 'keywords') -> list[str]:
    issues: list[str] = []
    for sequence in local.get('sequences', []):
        for beat in sequence.get('timeline', []):
            prefix = f"{sequence['sequence_id']}/{beat['beat_id']}"
            try:
                graph_texts(beat.get('controller_options', {}))
            except ValueError as error:
                issues.append(f'graph_text_invalid: {prefix} {error}')
            if policy == 'subtitles':
                # Subtitle runs carry no on-screen words; only formula labels may
                # stay, because notation reads the same in every subtitle language.
                options = beat.get('controller_options', {})
                if options.get('labels'):
                    try:
                        labels = parse_labels(options)
                    except ValueError as error:
                        issues.append(f'label_field_invalid: {prefix} {error}')
                        labels = []
                    if any(label.kind != 'formula' for label in labels):
                        issues.append(f'labels_forbidden: {prefix} subtitles policy allows only formula labels')
                    elif len(labels) > MAX_COUNTED_LABELS:
                        issues.append(f'label_count_exceeded: {prefix} {len(labels)} formula labels > {MAX_COUNTED_LABELS}')
                for field in REVIEW_FIELDS:
                    value = beat.get('controller_options', {}).get(field)
                    if isinstance(value, str):
                        for match in _QUOTED.finditer(value):
                            issues.append(f'label_hidden_in_prose: {prefix} {field} {match.group(0)}')
                continue
            for issue in beat_label_issues(beat['beat_id'], beat.get('controller_options', {})):
                code, _, rest = issue.partition(': ')
                issues.append(f'{code}: {prefix}{rest[len(beat["beat_id"]):]}')
    return issues


def format_labels_line(options: Mapping[str, object]) -> str:
    labels = parse_labels(options)
    if not labels:
        return '없음'
    parts = []
    for label in labels:
        tags = [label.side, label.emphasis] + ([label.kind] if label.kind != 'word' else [])
        parts.append(f'{label.text} → {label.anchor} ({", ".join(tags)})')
    return '; '.join(parts)


VISIBLE_AMOUNT = 0.002
RENDERED_AMOUNT = 0.5


def _actor_rect(actor, cam, aspect):
    local = _cm.camera_local(cam, actor['position'])
    nx, ny = _cm.project_to_ndc(local, cam['projection'], cam['ortho_scale'], cam['sensor_width'], cam['lens'], aspect)
    cx, cy = _cm.ndc_to_unit(nx, ny)
    rx, ry = _cm.radius_in_unit(actor.get('radius', 0), local, cam['projection'], cam['ortho_scale'], cam['sensor_width'], cam['lens'], aspect)
    return [cx - rx, cy - ry, cx + rx, cy + ry]


def render_text_issues(local, samples_by_sequence, *, width, height, policy='keywords'):
    issues = []
    aspect = width / height
    if policy == 'subtitles':
        return _subtitles_render_issues(local, samples_by_sequence, width=width, height=height)
    for sequence in local.get('sequences', []):
        sid = sequence['sequence_id']
        samples = samples_by_sequence.get(sid, [])
        for beat in sequence.get('timeline', []):
            labels = parse_labels(beat.get('controller_options', {}))
            if not labels:
                continue
            centre = (beat['start_frame'] + beat['end_frame']) // 2
            row = min(samples, key=lambda s: abs(s['canonical_frame'] - centre), default=None)
            if row is None or abs(row['canonical_frame'] - centre) > 3:
                issues.append(f"label_not_rendered: {sid}/{beat['beat_id']} no state sample near centre frame {centre}")
                continue
            shown = {c['text'] for c in row.get('callouts', []) if c.get('amount', 0) >= RENDERED_AMOUNT}
            for label in labels:
                if label.text not in shown:
                    issues.append(f"label_not_rendered: {sid}/{beat['beat_id']} {label.text!r} amount < {RENDERED_AMOUNT} at frame {centre}")
        if any('callouts' not in row for row in samples):
            issues.append(f'callouts_missing: {sid} renderer never bound CalloutLayer (state samples lack callouts)')
        for row in samples:
            visible = [c for c in row.get('callouts', []) if c.get('amount', 0) >= VISIBLE_AMOUNT]
            if not visible:
                continue
            frame = row['canonical_frame']
            cam = row['continuity']['camera']; actors = row['continuity'].get('actors', {})
            # Only the renderer's tracked objects count as coverable; backdrops and the
            # layer's own text/leader curves are captured as actors but are not subjects.
            tracked = set(row.get('entity_scales', actors).keys())
            own = {c['text'] for c in row.get('callouts', [])} | {c['text'] + ' leader' for c in row.get('callouts', [])}
            for index, c in enumerate(visible):
                where = f"{sid} frame {frame} {c['text']!r}"
                if _cm.rect_clipped(c['rect']):
                    issues.append(f'label_clipped: {where} rect {c["rect"]}')
                for other in visible[index + 1:]:
                    if _cm.rects_overlap(c['rect'], other['rect']):
                        issues.append(f'label_overlap: {where} with {other["text"]!r}')
                anchor = actors.get(c['anchor'])
                if anchor is None:
                    issues.append(f'leader_detached: {where} anchor {c["anchor"]!r} not captured')
                    continue
                try:
                    anchor_rect = _actor_rect(anchor, cam, aspect)
                except ValueError:
                    issues.append(f'label_anchor_behind_camera: {where}')
                    continue
                # Blender's float32 camera matrices put an edge point ~1e-6 off in far perspective shots.
                if not _cm.point_in_rect(c['leader'][0], anchor_rect, eps=1e-5):
                    issues.append(f'leader_detached: {where} start {c["leader"][0]} outside anchor {anchor_rect}')
                for name, actor in actors.items():
                    if name == c['anchor'] or name in own or name not in tracked or not actor.get('visible', True):
                        continue
                    try:
                        if _cm.rects_overlap(c['rect'], _actor_rect(actor, cam, aspect)):
                            issues.append(f'label_covers_object: {where} covers {name!r}')
                    except ValueError:
                        continue
    return issues


_DUPLICATE_SUFFIX = re.compile(r'\.\d{3}$')


def _font_source(name: str) -> str:
    """Blender object name → the label text it draws (duplicates and outlines included)."""
    base = _DUPLICATE_SUFFIX.sub('', name)
    if base.endswith(' outline'):
        base = _DUPLICATE_SUFFIX.sub('', base[:-len(' outline')])
    return base


def _declared_formulas(sequence) -> set[str]:
    texts = set()
    for beat in sequence.get('timeline', []):
        for label in parse_labels(beat.get('controller_options', {})):
            if label.kind == 'formula':
                texts.add(label.text)
    return texts


def _subtitles_render_issues(local, samples_by_sequence, *, width, height):
    """No words anywhere; only the plan's formula callouts may be drawn."""
    issues = []
    with_formulas = []
    for sequence in local.get('sequences', []):
        sid = sequence['sequence_id']
        formulas = _declared_formulas(sequence)
        if formulas:
            with_formulas.append(sequence)
        renderer = sequence.get('renderer') or local.get('renderer') or 'threejs'
        if renderer == 'threejs' and any(row.get('canvas_text_calls') != 0 for row in samples_by_sequence.get(sid, [])):
            # Blender attests text-free frames through FONT capture; Three.js must report
            # canvas_text_calls == 0 per sample or the run cannot prove it drew no text.
            issues.append(f"on_screen_text_unverifiable: {sid} threejs renderer did not attest canvas_text_calls == 0")
        for row in samples_by_sequence.get(sid, []):
            frame = row.get('canonical_frame')
            graph_allowed = set()
            for beat in sequence.get('timeline', []):
                if beat['start_frame'] <= frame < beat['end_frame']:
                    graph_allowed |= graph_texts(beat.get('controller_options', {}))
            graph_rows = row.get('graph_text', [])
            shown = {g['text'] for g in graph_rows}
            for graph in graph_rows:
                if graph['text'] not in graph_allowed:
                    issues.append(f'graph_text_undeclared: {sid} frame {frame} {graph["text"]!r}')
                rect = graph['rect']
                if len(rect) != 4 or not all(isinstance(v, (int, float)) and 0.02 <= v <= .98 for v in rect):
                    issues.append(f'graph_text_clipped: {sid} frame {frame} {graph["text"]!r}')
            for index, graph in enumerate(graph_rows):
                for other in graph_rows[index+1:]:
                    if _cm.rects_overlap(graph['rect'], other['rect']):
                        issues.append(f'graph_text_overlap: {sid} {graph["text"]!r} / {other["text"]!r}')
            # At the beat midpoint all declared axis labels and ticks must be
            # present. Transition edges may still be fading the graph in.
            for beat in sequence.get('timeline', []):
                if abs(frame-(beat['start_frame']+beat['end_frame'])//2) <= 3:
                    missing = graph_texts(beat.get('controller_options', {}))-shown
                    if missing:
                        issues.append(f'graph_text_missing: {sid}/{beat["beat_id"]} {sorted(missing)}')
            visible = [c for c in row.get('callouts', []) if c.get('amount', 0) >= VISIBLE_AMOUNT
                       and not (c.get('kind') == 'formula' and c.get('text') in formulas)]
            if visible:
                issues.append(f"callouts_forbidden: {sid} frame {frame} {[c['text'] for c in visible]}")
            for name, actor in row.get('continuity', {}).get('actors', {}).items():
                if name.startswith('GraphText:') and name[len('GraphText:'):] in graph_allowed and name[len('GraphText:'):] in shown:
                    continue
                if actor.get('kind') == 'FONT' and actor.get('visible', True) and _font_source(name) not in formulas:
                    issues.append(f"on_screen_text_found: {sid} frame {frame} {name!r}")
    if with_formulas:
        # Declared formulas get the keyword placement checks except object
        # covering: a formula is attached to the shapes it describes (bars),
        # whose coarse square bounds it always meets; that is reviewed on frames.
        subset = {**local, 'sequences': with_formulas}
        issues += [issue for issue in render_text_issues(subset, samples_by_sequence, width=width, height=height, policy='keywords')
                   if not issue.startswith('label_covers_object')]
    return issues
