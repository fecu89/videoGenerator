"""Pure callout geometry shared by the Blender layer, the text gate and previews.

No bpy and no package imports: Blender's worker puts this directory on sys.path
and imports it by module name.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence

REFERENCE_WIDTH = 16.0
HUD_DEPTH = 2.0
SAFE_MARGIN = 0.04
LABEL_HEIGHT_PX = {'word': 210, 'formula': 210, 'unit': 105}
SMALL_LABEL_HEIGHT_PX = 105
XLARGE_LABEL_HEIGHT_PX = 315   # a formula the film leads with: three times a small label
CJK_GLYPH_WIDTH = 1.0   # Hangul/CJK advance a full em in AppleGothic
LATIN_GLYPH_WIDTH = 0.6
FADE_SECONDS = 0.4
REFERENCE_FRAME = (1920, 1080)


def hud_scale(projection: str, ortho_scale: float, sensor_width: float, lens: float) -> float:
    width = ortho_scale if projection == 'ORTHO' else HUD_DEPTH * sensor_width / lens
    return width / REFERENCE_WIDTH


def rotate_inverse(q: Sequence[float], v: Sequence[float]) -> list[float]:
    w, x, y, z = q
    cx, cy, cz = (-x, -y, -z)
    vx, vy, vz = v
    tx = 2 * (cy * vz - cz * vy); ty = 2 * (cz * vx - cx * vz); tz = 2 * (cx * vy - cy * vx)
    return [vx + w * tx + (cy * tz - cz * ty), vy + w * ty + (cz * tx - cx * tz), vz + w * tz + (cx * ty - cy * tx)]


def camera_local(camera: Mapping[str, object], world: Sequence[float]) -> list[float]:
    delta = [a - b for a, b in zip(world, camera['position'])]
    return rotate_inverse(camera['rotation'], delta)


def _half_extent(projection, ortho_scale, sensor_width, lens, depth, aspect):
    half_w = ortho_scale / 2 if projection == 'ORTHO' else depth * sensor_width / (2 * lens)
    return half_w, half_w / aspect


def project_to_ndc(local, projection, ortho_scale, sensor_width, lens, aspect):
    x, y, z = local
    depth = -z
    if projection != 'ORTHO' and depth <= 1e-6:
        raise ValueError('anchor behind camera')
    half_w, half_h = _half_extent(projection, ortho_scale, sensor_width, lens, depth, aspect)
    return (x / half_w, y / half_h)


def radius_in_unit(radius, local, projection, ortho_scale, sensor_width, lens, aspect):
    half_w, half_h = _half_extent(projection, ortho_scale, sensor_width, lens, -local[2], aspect)
    return (radius / (2 * half_w), radius / (2 * half_h))


def ndc_to_unit(nx: float, ny: float) -> tuple[float, float]:
    return ((nx + 1) / 2, (1 - ny) / 2)


def _is_wide(char: str) -> bool:
    code = ord(char)
    return 0x1100 <= code <= 0x11FF or 0x2E80 <= code <= 0x9FFF or 0xAC00 <= code <= 0xD7AF or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFF60


def text_width_em(text: str) -> float:
    return sum(CJK_GLYPH_WIDTH if _is_wide(c) else LATIN_GLYPH_WIDTH for c in text)


def text_box(text: str, kind: str, width: int, height: int, size: str = 'large') -> tuple[float, float]:
    if size == 'small':
        height_px = min(LABEL_HEIGHT_PX[kind], SMALL_LABEL_HEIGHT_PX)
    elif size == 'xlarge':
        height_px = XLARGE_LABEL_HEIGHT_PX
    else:
        height_px = LABEL_HEIGHT_PX[kind]
    return (text_width_em(text) * height_px / REFERENCE_FRAME[0], height_px / REFERENCE_FRAME[1])


def _clamp_rect(rect):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    x0 = min(max(x0, SAFE_MARGIN), 1 - SAFE_MARGIN - w)
    y0 = min(max(y0, SAFE_MARGIN), 1 - SAFE_MARGIN - h)
    return [x0, y0, x0 + w, y0 + h]


def label_rect(anchor, radius, side, box, gap=0.03):
    ax, ay = anchor; rx, ry = radius; w, h = box
    if side == 'right':
        rect = [ax + rx + gap, ay - h / 2, ax + rx + gap + w, ay + h / 2]
    elif side == 'left':
        rect = [ax - rx - gap - w, ay - h / 2, ax - rx - gap, ay + h / 2]
    elif side == 'top':
        rect = [ax - w / 2, ay - ry - gap - h, ax + w / 2, ay - ry - gap]
    elif side == 'bottom':
        rect = [ax - w / 2, ay + ry + gap, ax + w / 2, ay + ry + gap + h]
    else:
        raise ValueError(f'unknown side: {side}')
    return _clamp_rect(rect)


def leader_points(anchor, radius, rect, side):
    ax, ay = anchor; rx, ry = radius; x0, y0, x1, y1 = rect
    if side in ('left', 'right'):
        end = (x0 if side == 'right' else x1, (y0 + y1) / 2)
        start = (ax + rx if side == 'right' else ax - rx, ay)
        elbow = (end[0], start[1])
    else:
        end = ((x0 + x1) / 2, y1 if side == 'top' else y0)
        start = (ax, ay - ry if side == 'top' else ay + ry)
        elbow = (start[0], end[1])
    return [start, elbow, end]


def rects_overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def rect_clipped(rect, margin=SAFE_MARGIN) -> bool:
    return rect[0] < margin or rect[1] < margin or rect[2] > 1 - margin or rect[3] > 1 - margin


def point_in_rect(p, rect, eps: float = 1e-6) -> bool:
    # Leaders start exactly on the anchor edge; allow float round-off there.
    return rect[0] - eps <= p[0] <= rect[2] + eps and rect[1] - eps <= p[1] <= rect[3] + eps


def fade_amount(frame, start, end, fps, seconds=FADE_SECONDS):
    if frame < start or frame >= end:
        return 0.0
    ramp = max(1, round(fps * seconds))
    return max(0.0, min(1.0, (frame - start) / ramp, (end - frame) / ramp))


def anchor_amounts(pairs) -> dict:
    """Max emphasis per anchor when several labels (across beats) share one object."""
    result: dict = {}
    for name, amount in pairs:
        result[name] = max(result.get(name, 0.0), float(amount))
    return result


def select_sample_frames(job: Mapping[str, object]) -> list[int]:
    requested = job.get('sample_frames')
    if requested is None:
        return list(range(int(job['frame_count'])))
    return sorted({int(i) for i in requested})
