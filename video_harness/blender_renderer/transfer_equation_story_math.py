"""Coin-classroom bookkeeping and beat state for the transfer-equation story.

Each desk keeps half of the coins it receives and adds four, so any start
value approaches the source function 4 / 0.5 = 8. The same rule sets the
light-beam intensity after each gas slab. Values are exact; the renderer only
chooses how to draw them.
"""
import math

GRAPH = 'transfer-equation-story-blender-v1'
CONTROLLER = 'transfer-equation-story'
EXTINCTION = 0.5      # fraction taken at each desk / slab
EMISSION = 4.0        # coins (intensity) added at each desk / slab
SOURCE = EMISSION / EXTINCTION
DESKS = 8             # desk 0 only passes; desks 1..7 apply the rule
STEPS = DESKS - 1

PROGRESS_KEYS = ('a_start', 'a_progress', 'b_progress', 'm_progress')
BLEND_KEYS = ('classroom', 'tray_glow', 'trail', 'balance', 'b_visible', 'compare', 'level_ring',
              'marked', 'atmosphere', 'beam', 'exchange', 'ratio_demo', 'hoop', 'slice', 'ticks',
              'student_ghost', 'dual_beam', 'star', 'wedge', 'deep_light', 'deep_marked',
              'tau_shell', 'escape', 'final_run')
KEYS = PROGRESS_KEYS + BLEND_KEYS
SHOTS = ('star_whole', 'star_wedge', 'row_wide', 'row_track_to_teacher', 'desk_close', 'row_medium',
         'balance_close', 'two_lane', 'two_lane_high', 'compare_close', 'slab_wide', 'slab_close',
         'slice_close', 'two_beam', 'star_surface')


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def smoother(x):
    x = max(0.0, min(1.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def ease_ends(x, a=0.15):
    """Constant speed in the middle, gentle start and stop (trapezoidal velocity)."""
    x = max(0.0, min(1.0, x))
    v = 1.0 / (1.0 - a)
    if x < a:
        return v * x * x / (2 * a)
    if x > 1 - a:
        return 1 - v * (1 - x) ** 2 / (2 * a)
    return v * (x - a / 2)


def apply_rule(value):
    return value * (1 - EXTINCTION) + EMISSION


def sequence_values(start, steps=STEPS):
    values = [float(start)]
    for _ in range(steps):
        values.append(apply_rule(values[-1]))
    return values


def lane_plan(start, steps=STEPS, *, blue=False):
    """Coin identities through the rule: every other coin leaves, four are added.

    Returns the initial stack and, per step, the removed ids, the added ids,
    the resulting stack (bottom→top) and the exact value after the step.
    Removing alternate slots halves each colour in the stack evenly.
    """
    start_count = int(round(start))
    colours = ['blue' if blue else 'bronze'] * start_count
    stack = list(range(start_count))
    next_id = start_count
    exact = float(start)
    steps_out = []
    for _ in range(steps):
        removed = [cid for slot, cid in enumerate(stack) if slot % 2 == 1]
        kept = [cid for slot, cid in enumerate(stack) if slot % 2 == 0]
        added = list(range(next_id, next_id + int(EMISSION)))
        next_id += int(EMISSION)
        colours += ['bronze'] * int(EMISSION)
        stack = kept + added
        exact = apply_rule(exact)
        steps_out.append(dict(removed=removed, kept=kept, added=added, stack=list(stack), value=exact))
    return dict(initial=list(range(start_count)), steps=steps_out, colours=colours, count=next_id,
                start=float(start))


# Within one rule step: slide to the next desk, remove half, add four.
PHASES = dict(slide=(0.0, 0.28), remove=(0.28, 0.58), add=(0.58, 0.86))
TRAY_SLIDE = (0.86, 1.0)  # only after the final step


def step_phase(t, phase):
    a, b = PHASES[phase] if phase in PHASES else TRAY_SLIDE
    return smooth((t - a) / (b - a))


def blue_fraction_after(steps):
    return EXTINCTION ** steps


def beam_intensities(start, slabs=DESKS):
    """Intensity entering, halfway (after loss) and leaving each slab."""
    rows = []
    value = float(start)
    for _ in range(slabs):
        lost = value * (1 - EXTINCTION)
        out = lost + EMISSION
        rows.append((value, lost, out))
        value = out
    return rows


def beam_radius(intensity, scale=0.055):
    """Beam cross-section area is proportional to intensity."""
    return scale * math.sqrt(max(0.0, intensity))


def state_at(job, frame):
    """Target states persist for progress keys; other keys ease to the beat value or 0."""
    first = job['timeline'][0]['controller_options'].get('state', {})
    values = {k: float(first.get(k, 0.0)) for k in KEYS}  # a sequence opens in its first beat's state
    shot = prev_shot = job['timeline'][0]['controller_options']['camera_shot']
    beat_u = 0.0; beat_start = 0; beat_index = 0
    retired_a = 0.0
    for index, beat in enumerate(job['timeline']):
        if frame < beat['start_frame']:
            break
        opts = beat['controller_options']
        state = opts.get('state', {})
        length = max(1, beat['end_frame'] - beat['start_frame'] - 1)
        linear = min(1.0, (frame - beat['start_frame']) / length)
        eased = smooth(linear)
        previous = values
        target = {k: (state.get(k, previous[k]) if k in PROGRESS_KEYS else state.get(k, 0.0)) for k in KEYS}
        paced = ease_ends(linear)
        values = {k: previous[k] + (target[k] - previous[k]) * (paced if k in PROGRESS_KEYS else eased)
                  for k in KEYS}
        if previous['marked'] > 0 or target['marked'] > 0:
            retired_a = max(retired_a, eased if previous['marked'] == 0 else 1.0)
        prev_shot, shot = shot, opts['camera_shot']
        beat_u, beat_start, beat_index = linear, beat['start_frame'], index
        if frame < beat['end_frame']:
            break
    # Consecutive beats that share a camera shot form one continuous camera move.
    timeline = job['timeline']
    run_start = beat_index
    while run_start > 0 and timeline[run_start - 1]['controller_options']['camera_shot'] == shot:
        run_start -= 1
    run_end = beat_index
    while run_end + 1 < len(timeline) and timeline[run_end + 1]['controller_options']['camera_shot'] == shot:
        run_end += 1
    first, last = timeline[run_start]['start_frame'], timeline[run_end]['end_frame']
    values['retired_a'] = retired_a
    values['shot'] = shot
    values['prev_shot'] = timeline[run_start - 1]['controller_options']['camera_shot'] if run_start else shot
    values['beat_u'] = beat_u
    values['shot_u'] = min(1.0, max(0.0, (frame - first) / max(1, last - first - 1)))
    values['shot_elapsed'] = (frame - first) / job['canonical_fps']
    values['beat_elapsed'] = (frame - beat_start) / job['canonical_fps']
    values['beat_index'] = beat_index
    current = timeline[beat_index]
    values['light_transition'] = current['controller_options'].get('light_transition', '')
    values['beat_seconds'] = (current['end_frame'] - current['start_frame'] - 1) / job['canonical_fps']
    return values


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported transfer-equation story graph')
    try:
        from .spectra import validate_job as validate_cache
    except ImportError:
        from spectra import validate_job as validate_cache
    proxy = {**job, 'scene_graph': 'stellar-spectra-blender-v1',
             'timeline': [{**b, 'controller': 'spectra-intro'} for b in job['timeline']]}
    validate_cache(proxy)
    for beat in job['timeline']:
        if beat['controller'] != CONTROLLER:
            raise ValueError('unknown transfer-equation story controller')
        opts = beat['controller_options']
        if opts.get('camera_shot') not in SHOTS:
            raise ValueError(f"unknown camera_shot {opts.get('camera_shot')!r}")
        state = opts.get('state', {})
        if set(state) - set(KEYS):
            raise ValueError(f'unknown state field {sorted(set(state) - set(KEYS))}')
        for key, value in state.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'nonfinite state {key}')
            limit = STEPS if key in ('a_progress', 'b_progress', 'm_progress') else 72 if key == 'a_start' else 2
            if not 0 <= value <= limit:
                raise ValueError(f'state {key} out of range')
