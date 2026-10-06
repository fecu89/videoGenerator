"""Ideal constant-depth northern-hemisphere vorticity teaching model.

Lengths and animation times are illustrative, not a weather forecast.
"""
import math

GRAPH = 'vorticity-blender-v1'
CONTROLLERS = {'vorticity-flow', 'vorticity-wheel', 'vorticity-earth', 'vorticity-wave'}
POLAR_LATITUDE = 70.0


def earth_pose(frame, timeline, fps):
    """Continuous observer transform; the physical globe never stops spinning.

    Scene 8 accelerates the observer into the rotating ground frame. Scene 9
    returns to the inertial frame. Scene 10 brings that same view around to
    the meridian used for the latitude comparison, without resetting objects.
    """
    beats = {b['controller_options']['scene_number']: b for b in timeline}
    beat = next(b for b in timeline if b['start_frame'] <= frame < b['end_frame'])
    n = beat['controller_options']['scene_number']
    p = (frame-beat['start_frame']) / max(1,beat['end_frame']-beat['start_frame']-1)
    q = p*p*(3-2*p)
    def integral_ramp(seconds):
        if seconds <= 0: return 0.
        if seconds >= 1: return seconds-.5
        return seconds**3-.5*seconds**4
    def apparent(f):
        t = f/fps
        observer = .18*(integral_ramp(t-beats[8]['start_frame']/fps)
                        - integral_ramp(t-beats[9]['start_frame']/fps))
        return .18*t-observer
    angle = apparent(frame)
    tilt = math.radians(80)
    latitude = math.radians(POLAR_LATITUDE)
    if n >= 10:
        start = apparent(beats[10]['start_frame'])
        meridian = round(start/math.tau)*math.tau
        angle = start+(meridian-start)*q if n == 10 else meridian
        tilt = math.radians(80-50*q if n == 10 else 30)
        latitude = math.radians(POLAR_LATITUDE+(90-POLAR_LATITUDE)*q if n == 10
                                else 90*(1-q) if n == 11 else 90*q)
    return dict(angle=angle,tilt=tilt,latitude=latitude,
                physical_angle=.18*frame/fps,observer_angle=.18*frame/fps-angle)


def planetary(latitude_degrees, omega=1.0):
    if not -90 <= latitude_degrees <= 90:
        raise ValueError('latitude outside the globe')
    return 2 * omega * math.sin(math.radians(latitude_degrees))


def relative(latitude_degrees, initial_latitude=40.0):
    return planetary(initial_latitude) - planetary(latitude_degrees)


def contributions(scene_number, progress):
    """Keep stationary-pole and migrating-parcel examples distinct."""
    if scene_number == 9:
        return planetary(POLAR_LATITUDE), 0.0
    if scene_number == 12:
        return planetary(90*progress), 0.0
    latitude = 40 + (20*progress if scene_number == 14 else -20*progress if scene_number == 15 else 0)
    return planetary(latitude), relative(latitude)


def vortex_velocity(x, y, cx, cy, circulation, core=.35):
    dx, dy = x-cx, y-cy
    factor = circulation / (2*math.pi*(dx*dx+dy*dy+core*core))
    return -factor*dy, factor*dx


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported vorticity graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid '+key)
    if any(not isinstance(job.get('output', {}).get(k), int) or job['output'][k] <= 0
           for k in ('width', 'height', 'fps')):
        raise ValueError('invalid output')
    timeline = job.get('timeline', [])
    if not timeline or any(b['controller'] not in CONTROLLERS for b in timeline):
        raise ValueError('unknown vorticity controller')
    for b in timeline:
        if b.get('controller_options', {}).get('scene_number') not in range(1, 20):
            raise ValueError('scene_number must be 1..19')
    cache = job.get('canonical_state_cache', [])
    ids = {b['beat_id'] for b in timeline}
    previous = -math.inf
    if len(cache) != job['duration_frames']:
        raise ValueError('canonical cache length mismatch')
    for i, state in enumerate(cache):
        if state['canonical_frame'] != i or not state['active_beat_ids'] or not set(state['active_beat_ids']) <= ids:
            raise ValueError('invalid canonical cache')
        if not math.isfinite(state['simulation_time']) or state['simulation_time'] < previous:
            raise ValueError('invalid simulation time')
        previous = state['simulation_time']
