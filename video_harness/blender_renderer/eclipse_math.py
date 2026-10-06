"""Deterministic eclipse geometry in a documented, compressed teaching scale."""
import math

GRAPH = 'sun-earth-moon-blender-v1'
CONTROLLERS = {'eclipse-intro', 'eclipse-question', 'eclipse-angular-size',
    'solar-eclipse-alignment', 'eclipse-observers', 'eclipse-annular',
    'lunar-eclipse-alignment', 'eclipse-red-moon', 'eclipse-atmosphere',
    'eclipse-monthly', 'eclipse-inclination', 'eclipse-ending'}


def shadow_radii(source_radius, blocker_radius, separation, behind):
    """Paraxial tangent-cone radii; negative umbra denotes the antumbra."""
    if min(source_radius, blocker_radius, separation) <= 0 or behind < 0:
        raise ValueError('positive radii/separation and nonnegative shadow distance required')
    return (blocker_radius-behind*(source_radius-blocker_radius)/separation,
            blocker_radius+behind*(source_radius+blocker_radius)/separation)


def angular_diameter(radius, distance):
    if radius <= 0 or distance <= radius:
        raise ValueError('observer must be outside the sphere')
    return 2*math.asin(radius/distance)


def orbit_position(angle, radius=6, inclination=5, node=0):
    """Orbit in XY, inclined about its node, with world Z perpendicular to ecliptic."""
    if radius <= 0:
        raise ValueError('positive orbital radius required')
    inc=math.radians(inclination)
    x,y,z=radius*math.cos(angle),radius*math.sin(angle)*math.cos(inc),radius*math.sin(angle)*math.sin(inc)
    return (x*math.cos(node)-y*math.sin(node),x*math.sin(node)+y*math.cos(node),z)


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported eclipse scene_graph')
    for key in ('frame_count','duration_frames','canonical_fps'):
        if not isinstance(job.get(key),int) or job[key] <= 0:
            raise ValueError(f'invalid {key}')
    if any(not isinstance(job.get('output',{}).get(k),int) or job['output'][k]<=0 for k in ('width','height','fps')):
        raise ValueError('invalid output')
    timeline=job.get('timeline',[])
    if not timeline or any(b['controller'] not in CONTROLLERS for b in timeline):
        raise ValueError('unknown eclipse controller')
    cache=job.get('canonical_state_cache',[])
    if len(cache)!=job['duration_frames']:
        raise ValueError('canonical state cache length mismatch')
    ids={b['beat_id'] for b in timeline}; previous=-math.inf
    for i,state in enumerate(cache):
        if state['canonical_frame']!=i or not state['active_beat_ids'] or not set(state['active_beat_ids'])<=ids:
            raise ValueError('invalid canonical state cache')
        if state['simulation_time']<previous:
            raise ValueError('simulation time reversal')
        previous=state['simulation_time']


def northern_solar_offset(progress, initial_offset):
    """Moon's west-to-east drift: screen right to left, celestial north up."""
    if initial_offset < 0:
        raise ValueError('initial offset must be on the western/right limb')
    p=max(0.0,min(1.0,progress))
    return initial_offset*(1-p*p*(3-2*p))
