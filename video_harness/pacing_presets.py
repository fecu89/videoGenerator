"""Versioned video pacing recipes shared by the settings UI and CLI.

Resolved fields, not the recipe name, remain authoritative for each run.
"""
from copy import deepcopy

from .settings import HarnessSettings

PRESET_VERSION = 2


def _values(target, cap, pause, leading, trailing, gap, transition, beat_min, beat_max, scene_min, voice_max, local_max, fade):
    return dict(zip((
        'voice.target_syllables_per_second', 'voice.max_tempo_factor',
        'voice.max_internal_pause_ms', 'voice.sentence_leading_margin_ms',
        'voice.sentence_trailing_margin_ms', 'local_video.scene_gap_seconds',
        'local_video.camera_transition_seconds', 'local_video.target_beat_min_seconds',
        'local_video.target_beat_max_seconds', 'voice.min_scene_seconds',
        'voice.max_scene_seconds', 'local_video.max_scene_seconds', 'music.fade_seconds',
        'local_video.min_scene_seconds', 'voice.speaking_rate',
    ), (target, cap, pause, leading, trailing, gap, transition, beat_min, beat_max,
        scene_min, voice_max, local_max, fade, scene_min, 1.0), strict=True))


PACING_PRESETS = (
    {'id': 'calm', 'label': '차분한 설명', 'values': _values(5.2, 1.25, 300, 100, 800, .3, .7, 5, 8, 5, 16, 17, .8)},
    {'id': 'standard', 'label': '일반 영상', 'values': _values(5.8, 1.3, 200, 80, 420, .15, .5, 3, 5, 4, 14, 15, .5)},
    {'id': 'shorts', 'label': '쇼츠 템포', 'values': _values(6.5, 1.4, 150, 50, 250, 0, .35, 2, 4, 3, 12, 13, .3)},
)
for _preset in PACING_PRESETS:
    _preset['values'].update({
        'voice.pause_mode': 'typed', 'voice.comma_pause_ms': 120,
        'voice.semantic_pause_ms': 200, 'voice.emphasis_pause_ms': 350,
        'voice.sentence_pause_ms': 500,
    })
PACING_KEYS = tuple(PACING_PRESETS[0]['values'])


def pacing_payload():
    return {'version': PRESET_VERSION, 'presets': deepcopy(PACING_PRESETS), 'keys': list(PACING_KEYS)}


def apply_pacing_preset(settings: HarnessSettings, preset_id: str) -> HarnessSettings:
    if settings.schema_version != 7:
        raise ValueError('Apply presets to project settings; existing runs require explicit refresh.')
    preset = next((item for item in PACING_PRESETS if item['id'] == preset_id), None)
    if preset is None:
        raise ValueError(f'Unknown pacing preset: {preset_id}')
    payload = settings.model_dump(mode='json')
    for path, value in preset['values'].items():
        group, field = path.split('.')
        payload[group][field] = value
    payload['pacing'] = {'preset': preset_id, 'version': PRESET_VERSION}
    return HarnessSettings.model_validate(payload)


def pacing_status(settings):
    metadata = getattr(settings, 'pacing', None)
    preset_id = metadata.preset if metadata else 'custom'
    version = metadata.version if metadata else PRESET_VERSION
    preset = next((item for item in PACING_PRESETS if item['id'] == preset_id), None)
    values = settings.model_dump(mode='json')
    customized = preset is None or version != PRESET_VERSION or any(
        values[group][field] != value
        for path, value in (preset['values'].items() if preset else [])
        for group, field in [path.split('.')]
    )
    return {'preset': preset_id, 'version': version,
            'label': preset['label'] if preset else '사용자 지정', 'customized': customized}


def pacing_warnings(local, settings):
    timing = getattr(settings, 'local_video', None)
    lower = getattr(timing, 'target_beat_min_seconds', 0)
    upper = getattr(timing, 'target_beat_max_seconds', 0)
    if not upper:
        return []
    warnings = []
    for sequence in local.sequences:
        for beat in sequence.timeline:
            duration = (beat.end_frame - beat.start_frame) / local.defaults.fps
            if duration < lower or duration > upper:
                reason = str(getattr(beat, 'controller_options', {}).get('pacing_exception_reason', '')).strip()
                warnings.append(
                    f'{sequence.sequence_id}/{beat.beat_id}: {duration:.1f}s; '
                    f'target {lower:g}–{upper:g}s. Review camera/visual changes within the beat; '
                    + (f'Exception: {reason}' if reason else 'Long physical processes need pacing_exception_reason in controller_options.')
                )
    return warnings


def render_pacing_review(run_dir, local):
    """Human review advice; never retime approved frames or simulation clocks."""
    from .settings import resolve_run_settings
    settings = resolve_run_settings(run_dir)
    timing = getattr(settings, 'local_video', None)
    if not getattr(timing, 'target_beat_max_seconds', 0):
        return ''
    status = pacing_status(settings)
    label = status['label'] + (' · 사용자 조정' if status['customized'] else '')
    voice = settings.voice
    gap = (voice.sentence_pause_ms if getattr(voice, 'pause_mode', 'legacy') == 'typed'
           else voice.sentence_leading_margin_ms + voice.sentence_trailing_margin_ms) / 1000
    lines = [f'\n## 영상 템포: {label} (v{status["version"]})', '',
             f'- 말하기 목표 {voice.target_syllables_per_second:g}음절/초 · 문장 간격 {gap:g}초 · 씬 간격 {timing.scene_gap_seconds:g}초',
             f'- 구도 유지 목표 {timing.target_beat_min_seconds:g}–{timing.target_beat_max_seconds:g}초 · 카메라 전환 {timing.camera_transition_seconds:g}초 · 음악 페이드 {settings.music.fade_seconds:g}초',
             '- 나레이션 장면 안에서 구도·강조를 나누며, 물리 시간과 음성·자막의 동기는 유지합니다.',
             '- 범위 밖 비트는 controller_options.pacing_exception_reason에 연속 관찰이 필요한 이유를 기록합니다.',
             '- 카메라 전환은 렌더러의 구현을 확인합니다. 개별 장면은 전달된 camera_transition_seconds를 사용하고 프리뷰에서 검토합니다.', '']
    warnings = pacing_warnings(local, settings)
    lines += ['### 구도 길이 검토', '', *(f'- {item}' for item in warnings)] if warnings else ['구도 길이가 목표 범위 안에 있습니다.']
    return '\n'.join(lines) + '\n'


def render_pacing_values(settings):
    timing = getattr(settings, 'local_video', None)
    metadata = getattr(settings, 'pacing', None)
    if not getattr(timing, 'target_beat_max_seconds', 0) and getattr(metadata, 'preset', 'custom') == 'custom':
        return None
    return {**pacing_status(settings),
            'target_beat_min_seconds': timing.target_beat_min_seconds,
            'target_beat_max_seconds': timing.target_beat_max_seconds,
            'camera_transition_seconds': timing.camera_transition_seconds}
