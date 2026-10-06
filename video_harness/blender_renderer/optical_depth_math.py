"""Deterministic schematic extinction of a collimated, monochromatic beam.

Equal-energy packets sample the exponential free-path distribution. This is
an illustration of direct (unscattered) transmission, not multiple-scattering
radiative transfer or a quantitative solar-atmosphere model.
"""
import math

GRAPH = 'optical-depth-blender-v1'
CONTROLLER = 'optical-depth'
DEFAULTS = dict(tau=1., length=8., camera_width=24., camera_x=0.,
                camera_y=0., opening=0., layers=0.)


def smooth(t):
    t = max(0., min(1., t))
    return t*t*(3-2*t)


def transmission(tau):
    if not math.isfinite(tau) or tau < 0:
        raise ValueError('optical depth must be finite and nonnegative')
    return math.exp(-tau)


def free_depth(index, count=100):
    return -math.log((index+.5)/count)


def direct_count(tau, count=100):
    transmission(tau)
    return sum(free_depth(i, count) >= tau for i in range(count))


def state_at(job, frame):
    """Evaluate every frame independently, retaining the preceding end state."""
    values = dict(DEFAULTS)
    for beat in job['timeline']:
        if frame < beat['start_frame']:
            break
        target = {**values, **beat['controller_options'].get('state', {})}
        duration = max(1, beat['end_frame']-beat['start_frame']-1)
        p = smooth((frame-beat['start_frame'])/duration)
        camera_frames = max(1, job.get('camera_transition_seconds', .4)*job['canonical_fps'])
        cp = smooth((frame-beat['start_frame'])/camera_frames)
        values = {k: values[k]+(target[k]-values[k])*(cp if k.startswith('camera_') else p)
                  for k in DEFAULTS}
        if frame < beat['end_frame']:
            break
    values['direct_fraction'] = transmission(values['tau'])
    values['direct_packets'] = direct_count(values['tau'])
    return values


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported optical-depth graph')
    # Reuse the generic cache contract without changing the caller's job.
    try:
        from .spectra import validate_job as validate_cache
    except ImportError:
        from spectra import validate_job as validate_cache
    proxy = {**job, 'scene_graph': 'stellar-spectra-blender-v1',
             'timeline': [{**b, 'controller': 'spectra-intro'} for b in job['timeline']]}
    validate_cache(proxy)
    for beat in job['timeline']:
        if beat['controller'] != CONTROLLER:
            raise ValueError('unknown optical-depth controller')
        state = beat['controller_options'].get('state', {})
        if set(state)-set(DEFAULTS):
            raise ValueError('unknown optical-depth state option')
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in state.values()):
            raise ValueError('optical-depth state must be finite')
        transmission(state.get('tau', 1))
        if state.get('length', 8) <= 0 or state.get('camera_width', 24) <= 0:
            raise ValueError('length and camera width must be positive')
        if not 0 <= state.get('opening', 0) <= 1 or not 0 <= state.get('layers', 0) <= 3:
            raise ValueError('invalid opening or layer count')
