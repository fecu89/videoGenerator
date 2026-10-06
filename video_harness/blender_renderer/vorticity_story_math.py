"""Frame-independent state for the approved 22-part vorticity story."""
import math

GRAPH = 'vorticity-story-blender-v2'
CONTROLLER = 'vorticity-story'
# The opening globe sits left of the flat flow, at this gallery x.
WESTERLY_PANEL = -17.0
WESTERLY_LATITUDE = 45.0
WESTERLY_AMPLITUDE = 12.0
WESTERLY_LOBES = 5
WESTERLY_TILT = math.radians(70)
MIGRATION_SECONDS = 10.0


def smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def phase(frame, start, end):
    return smooth((frame - start) / max(1, end - start - 1))


def story_state(frame, timeline, fps):
    beats = {b['controller_options']['scene_number']: b for b in timeline}
    b = next(b for b in timeline if b['start_frame'] <= frame < b['end_frame'])
    n = b['controller_options']['scene_number']
    p = phase(frame, b['start_frame'], b['end_frame'])
    # Each migration finishes within its own narrated question (about 10 s).
    migration = round(MIGRATION_SECONDS * fps)
    south = phase(frame, beats[13]['start_frame'], beats[13]['start_frame'] + migration)
    north = phase(frame, beats[16]['start_frame'], beats[16]['start_frame'] + migration)
    latitude = 70.0 - 30 * south + 30 * north
    # Geometric rotation never resets when the observer changes reference frames.
    physical_angle = .18 * frame / fps
    ground_start = beats[9]['start_frame'] / fps
    def ramp(elapsed):
        elapsed = max(0.0, elapsed)
        return elapsed**3 - .5*elapsed**4 if elapsed < 1 else elapsed-.5
    observer_angle = .18 * ramp(frame / fps - ground_start)
    # Bring the meridian into view by turning the apparent globe onward in the
    # sense of Earth's rotation (counterclockwise from the north), never by
    # unwinding the accumulated angle backwards.
    view = phase(frame, beats[11]['start_frame'], beats[11]['end_frame'])
    start = beats[11]['start_frame'] / fps
    apparent_start = .18 * start - .18 * ramp(start - ground_start)
    observer_angle -= ((-apparent_start) % math.tau) * view
    # Before Scene 18 the view returns to the opening's pole-toward-camera tilt.
    back = phase(frame, beats[17]['end_frame'] - round(1.4 * fps), beats[17]['end_frame'] + round(.6 * fps))
    tilt = math.radians(80 - 55 * view + 45 * back)
    f = 2 * math.sin(math.radians(latitude))
    absolute = 2 * math.sin(math.radians(70))
    return dict(scene_number=n, progress=p, latitude=latitude,
                physical_angle=physical_angle, observer_angle=observer_angle,
                angle=physical_angle-observer_angle, tilt=tilt,
                planetary=f, relative=absolute-f, absolute=absolute)


def westerly_latitude(longitude):
    """Illustrative five-lobe mid-latitude meander in the ground frame."""
    return WESTERLY_LATITUDE + WESTERLY_AMPLITUDE * math.cos(WESTERLY_LOBES * longitude)


def westerly_point(longitude, radius=1.0):
    """Globe-local point; +Y is north and increasing longitude is eastward."""
    phi = math.radians(westerly_latitude(longitude))
    return (radius * math.cos(phi) * math.cos(longitude), radius * math.sin(phi),
            -radius * math.cos(phi) * math.sin(longitude))


def westerly_state(t):
    """The globe turns eastward slowly; parcels move eastward along the wave."""
    return dict(spin=.05 * t, parcel_longitude=.3 * t)


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported vorticity story graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid ' + key)
    for key in ('width', 'height', 'fps'):
        if not isinstance(job.get('output', {}).get(key), int) or job['output'][key] <= 0:
            raise ValueError('invalid output ' + key)
    timeline = job.get('timeline', [])
    if [b.get('controller_options', {}).get('scene_number') for b in timeline] != list(range(1, 23)):
        raise ValueError('vorticity story requires the approved 22-part order')
    cursor = 0
    for beat in timeline:
        if beat['controller'] != CONTROLLER or beat['start_frame'] != cursor or beat['end_frame'] <= cursor:
            raise ValueError('vorticity timeline must have contiguous registered beats')
        cursor = beat['end_frame']
    if cursor != job['duration_frames']:
        raise ValueError('timeline duration mismatch')
    cache = job.get('canonical_state_cache', [])
    if len(cache) != job['duration_frames']:
        raise ValueError('canonical cache length mismatch')
    previous = -math.inf
    ids = {b['beat_id'] for b in timeline}
    for i, item in enumerate(cache):
        if item['canonical_frame'] != i or not item['active_beat_ids'] or not set(item['active_beat_ids']) <= ids:
            raise ValueError('invalid canonical frame')
        if not math.isfinite(item['simulation_time']) or item['simulation_time'] < previous:
            raise ValueError('simulation time must be monotone')
        previous = item['simulation_time']
