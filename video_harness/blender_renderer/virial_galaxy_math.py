"""Beat state, orbits and teaching quantities for the virial-galaxy story.

An elliptical galaxy of stars on randomly oriented orbits, a gravity well whose
depth stands for the enclosed mass, kinetic/potential energy bars in the virial
ratio 2K = -U, Doppler-shifted absorption lines that add up to a broadened line,
and a balance comparing light-based and dynamical mass. The quantities are
qualitative teaching values; the renderer only chooses how to draw them.
"""
import math

GRAPH = 'virial-galaxy-story-blender-v1'
CONTROLLER = 'virial-galaxy-story'

# Persist between beats unless a beat sets them.
PROGRESS_KEYS = ('well_depth', 'core_mass', 'sigma', 'lines', 'tilt', 'fling', 'escape', 'bars_level')
# Return to 0 unless a beat sets them.
BLEND_KEYS = ('elliptical', 'tracers', 'spiral', 'scale', 'fling_star', 'well', 'slow_star', 'fast_star',
              'held_star', 'bars', 'double_k', 'radius_ring', 'doppler', 'waves', 'spectrum', 'width_marks',
              'mass_glow', 'light_ball', 'dyn_ball', 'dark_shell', 'light_flow', 'halo', 'telescope', 'on_scale')
KEYS = PROGRESS_KEYS + BLEND_KEYS
DEFAULTS = dict(sigma=1.0)
RANGES = dict(well_depth=(0, 2), core_mass=(0, 2), sigma=(0.2, 2), lines=(0, 1), tilt=(-1, 1), fling=(0, 1),
              escape=(0, 1), bars_level=(0, 2))
SHOTS = ('hook_wide', 'galaxy_close', 'galaxy_front', 'two_galaxies', 'tracers', 'fling', 'well_high',
         'well_bars', 'bars_close', 'galaxy_measure', 'far_away', 'doppler_front', 'doppler_side', 'spectrum',
         'scale_compare', 'scale_dyn_close', 'halo_wide', 'closing', 'galaxy_ring')
BLEND_SECONDS = 1.0      # fades and appearances inside a beat
# Moves of the whole galaxy (onto the balance, into the well) take longer to read.
BLEND_SECONDS_BY_KEY = dict(on_scale=1.8, elliptical=1.8, well=1.8, scale=1.8)

# Virial teaching model: K = (1/2) M sigma^2 (per unit), U = -2K; well depth ~ sigma^2 at fixed size.
VIRIAL_ETA = 5.0         # M ~ eta R sigma^2 / G (Cappellari et al. 2006)


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def smoother(x):
    x = max(0.0, min(1.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def ease_ends(x, a=0.15):
    """Constant speed in the middle, gentle start and stop."""
    x = max(0.0, min(1.0, x))
    v = 1.0 / (1.0 - a)
    if x < a:
        return v * x * x / (2 * a)
    if x > 1 - a:
        return 1 - v * (1 - x) ** 2 / (2 * a)
    return v * (x - a / 2)


LINE_K = 1.55            # absorption-line Gaussian sigma (scene units) per unit velocity dispersion
LINE_S0 = 0.06           # a single star's own narrow line
LINE_DEPTH = 0.97


def line_profile(sigma, mixed):
    """(Gaussian sigma in scene units, peak depth) of the galaxy's absorption line.

    One star gives a narrow line; mixing many Doppler-shifted stars widens it in
    proportion to the velocity dispersion. The absorbed total stays similar, so a
    wider line is shallower.
    """
    s = LINE_S0 + (LINE_K * sigma - LINE_S0) * max(0.0, min(1.0, mixed))
    return s, LINE_DEPTH / (1 + 0.2 * (s - LINE_S0))


def spin_quaternion(angle):
    """(w, x, y, z) of a turn about local Z, continuous in angle.

    mathutils.Quaternion(axis, angle) folds the angle into (-pi, pi], so the
    result jumps to -q at every odd multiple of pi; interpolating keyframes
    across that jump whirls the object. Building the components directly does not fold.
    """
    return (math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2))


def golden(i):
    return (i * 0.6180339887) % 1.0


def virial_mass(radius, sigma, eta=VIRIAL_ETA, g=1.0):
    return eta * radius * sigma * sigma / g


def kinetic_potential(mass_level):
    """Bar heights for K and U in the virial ratio (U = -2K)."""
    k = 1.6 + 1.1 * mass_level
    return k, -2.0 * k


def well_depth_units(level):
    """Gravity-well depth in scene units; deeper means more enclosed mass."""
    return 3.2 + 4.2 * level


def well_profile(r, rim=16.0, a=2.6):
    """Normalised funnel shape: 1 at the centre, 0 at the rim."""
    f = 1 / math.sqrt(1 + (r / a) ** 2)
    f_rim = 1 / math.sqrt(1 + (rim / a) ** 2)
    return max(0.0, (f - f_rim) / (1 - f_rim))


def gaussian_quantiles(n):
    """Deterministic line-of-sight velocities (unit dispersion) for n stars."""
    out = []
    for i in range(n):
        p = (i + 0.5) / n
        # Acklam-style rational approximation is overkill; use erfinv via bisection.
        lo, hi = -4.0, 4.0
        for _ in range(48):
            mid = (lo + hi) / 2
            if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
                lo = mid
            else:
                hi = mid
        out.append((lo + hi) / 2)
    # Interleave so progressive reveals stay symmetric about the rest wavelength.
    order = sorted(range(n), key=lambda k: golden(k * 7 + 3))
    return [out[k] for k in order]


def state_at(job, frame):
    """Progress keys persist and ease over the beat; blend keys fade over BLEND_SECONDS."""
    fps = job['canonical_fps']
    timeline = job['timeline']
    first = timeline[0]['controller_options'].get('state', {})
    values = {k: float(first.get(k, DEFAULTS.get(k, 0.0))) for k in KEYS}
    beat_index = 0
    linear = 0.0
    for index, beat in enumerate(timeline):
        if frame < beat['start_frame']:
            break
        opts = beat['controller_options']
        state = opts.get('state', {})
        length = max(1, beat['end_frame'] - beat['start_frame'] - 1)
        linear = min(1.0, (frame - beat['start_frame']) / length)
        progress_span = opts.get('progress_seconds')
        if progress_span:
            paced = ease_ends(min(1.0, (frame - beat['start_frame']) / max(1.0, progress_span * fps)))
        else:
            paced = ease_ends(linear)
        blends = {k: smooth((frame - beat['start_frame']) / max(1.0, min(length, s * fps)))
                  for k, s in BLEND_SECONDS_BY_KEY.items()}
        blend = smooth((frame - beat['start_frame']) / max(1.0, min(length, BLEND_SECONDS * fps)))
        previous = values
        values = {}
        for k in KEYS:
            if k in PROGRESS_KEYS:
                target = float(state.get(k, previous[k]))
                values[k] = previous[k] + (target - previous[k]) * paced
            else:
                target = float(state.get(k, 0.0))
                values[k] = previous[k] + (target - previous[k]) * blends.get(k, blend)
        beat_index = index
        if frame < beat['end_frame']:
            break
    shot = timeline[beat_index]['controller_options']['camera_shot']
    run_start = beat_index
    while run_start > 0 and timeline[run_start - 1]['controller_options']['camera_shot'] == shot:
        run_start -= 1
    run_end = beat_index
    while run_end + 1 < len(timeline) and timeline[run_end + 1]['controller_options']['camera_shot'] == shot:
        run_end += 1
    first_frame, last_frame = timeline[run_start]['start_frame'], timeline[run_end]['end_frame']
    current = timeline[beat_index]
    values.update(
        shot=shot,
        prev_shot=timeline[run_start - 1]['controller_options']['camera_shot'] if run_start else shot,
        beat_u=linear,
        shot_u=min(1.0, max(0.0, (frame - first_frame) / max(1, last_frame - first_frame - 1))),
        shot_elapsed=(frame - first_frame) / fps,
        beat_elapsed=(frame - current['start_frame']) / fps,
        beat_index=beat_index,
        beat_seconds=(current['end_frame'] - current['start_frame'] - 1) / fps,
    )
    return values


def orbit_clock(job):
    """Cumulative orbital phase time per frame: stars run faster when sigma is larger."""
    fps = job['canonical_fps']
    clock = [0.0]
    for frame in range(1, job['duration_frames']):
        clock.append(clock[-1] + state_at(job, frame - 1)['sigma'] / fps)
    return clock


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported virial-galaxy story graph')
    try:
        from .spectra import validate_job as validate_cache
    except ImportError:
        from spectra import validate_job as validate_cache
    proxy = {**job, 'scene_graph': 'stellar-spectra-blender-v1',
             'timeline': [{**b, 'controller': 'spectra-intro'} for b in job['timeline']]}
    validate_cache(proxy)
    for beat in job['timeline']:
        if beat['controller'] != CONTROLLER:
            raise ValueError('unknown virial-galaxy story controller')
        opts = beat['controller_options']
        if opts.get('camera_shot') not in SHOTS:
            raise ValueError(f"unknown camera_shot {opts.get('camera_shot')!r}")
        state = opts.get('state', {})
        if set(state) - set(KEYS):
            raise ValueError(f'unknown state field {sorted(set(state) - set(KEYS))}')
        for key, value in state.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'nonfinite state {key}')
            lo, hi = RANGES.get(key, (0, 1))
            if not lo <= value <= hi:
                raise ValueError(f'state {key} out of range')
        span = opts.get('progress_seconds')
        if span is not None and (not isinstance(span, (int, float)) or not 0 < span <= 30):
            raise ValueError('invalid progress_seconds')
