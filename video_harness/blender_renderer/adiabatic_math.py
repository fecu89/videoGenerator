"""Dry ideal-gas work model and elastic collision, in normalized teaching units.

Particle paths illustrate random thermal motion, not a molecular dynamics solver.
After saturation the cloud animation is qualitative: dry Poisson cooling is not
continued into the latent-heat regime. Colours and spatial scale are illustrative.
"""
import math
import random

GRAPH = 'adiabatic-expansion-blender-v1'
CONTROLLER = 'adiabatic-expansion'


def adiabatic_state(volume, gamma=1.4):
    if not math.isfinite(volume) or volume <= 0 or gamma <= 1:
        raise ValueError('positive finite volume and gamma > 1 required')
    temperature = volume ** (1 - gamma)
    energy = temperature / (gamma - 1)
    return dict(temperature=temperature, pressure=volume ** -gamma,
                internal_energy=energy, work=1 / (gamma - 1) - energy,
                speed=math.sqrt(temperature))


def elastic_velocities(m1, m2, u1, u2):
    if m1 <= 0 or m2 <= 0:
        raise ValueError('positive masses required')
    return (((m1-m2)*u1+2*m2*u2)/(m1+m2),
            (2*m1*u1+(m2-m1)*u2)/(m1+m2))


def particle_position(index, phase, radius):
    rng = random.Random(829 + index)
    offsets = [rng.uniform(-1, 1) for _ in range(3)]
    velocity = [rng.uniform(-1, 1) for _ in range(3)]
    norm = math.sqrt(sum(v*v for v in velocity))
    return tuple(radius * (1-abs((offset+phase*v/norm+1)%4-2))
                 for offset, v in zip(offsets, velocity))


def smooth(t):
    t = min(1., max(0., t))
    return t*t*(3-2*t)


def state_at(job, frame):
    first = job['timeline'][0]['controller_options']
    state = dict(volume=1., altitude=0., camera_scale=12., focus_x=0., focus_z=0.,
                 detail=0., cloud=0., inflate=0., piston=0.,
                 camera_x=0.,camera_y=-12.,camera_z=3.,focus_y=0.,lens=42.,
                 reveal=0.,column=0.,arrow=0.,air_above=1.,outside=0.)
    state.update(first.get('initial', {}))
    for beat in job['timeline']:
        if frame < beat['start_frame']:
            break
        target = {**state, **beat['controller_options'].get('state', {})}
        p = smooth((frame-beat['start_frame']) / max(1, beat['end_frame']-beat['start_frame']-1))
        cp = smooth((frame-beat['start_frame']) / max(1, beat['controller_options'].get('camera_move_seconds',job.get('camera_transition_seconds', .4))*job['canonical_fps']))
        state = {k: v+(target[k]-v)*(cp if k in ('camera_scale','focus_x','focus_y','focus_z','camera_x','camera_y','camera_z','lens') else p) for k,v in state.items()}
        if frame < beat['end_frame']:
            break
    state.update(adiabatic_state(state['volume']))
    return state


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported adiabatic graph')
    try:
        from .spectra import validate_job as validate_cache
    except ImportError:
        from spectra import validate_job as validate_cache
    validate_cache({**job, 'scene_graph': 'stellar-spectra-blender-v1',
                    'timeline': [{**b, 'controller':'spectra-intro'} for b in job['timeline']]})
    environments = {'sky','balloon','atmosphere','molecules','collision','piston','parcel','cloud'}
    env = job['timeline'][0]['controller_options'].get('environment')
    if env not in environments:
        raise ValueError('unknown environment')
    for beat in job['timeline']:
        if beat['controller'] != CONTROLLER or beat['controller_options'].get('environment') != env:
            raise ValueError('sequence must preserve environment and controller')
        for key in ('initial','state'):
            values = beat['controller_options'].get(key, {})
            for k,v in values.items():
                if k not in {'volume','altitude','camera_scale','focus_x','focus_z','detail','cloud','inflate','piston','camera_x','camera_y','camera_z','focus_y','lens','reveal','column','arrow','air_above','outside'} or not isinstance(v,(int,float)) or not math.isfinite(v):
                    raise ValueError('invalid teaching state')
            adiabatic_state(values.get('volume',1))
            if values.get('camera_scale',12) <= 0:
                raise ValueError('positive camera scale required')


def sphere_particle(index, phase):
    """Unit-speed specular billiard in a unit sphere, evaluated without history."""
    rng=random.Random(829+index)
    p=[rng.uniform(-.35,.35) for _ in range(3)]
    v=[rng.uniform(-1,1) for _ in range(3)]
    norm=math.sqrt(sum(x*x for x in v));v=[x/norm for x in v]
    remaining=max(0,phase)
    while remaining>1e-12:
        pv=sum(a*b for a,b in zip(p,v))
        distance=-pv+math.sqrt(max(0,pv*pv+1-sum(x*x for x in p)))
        if distance>=remaining:
            return tuple(a+b*remaining for a,b in zip(p,v))
        p=[a+b*distance for a,b in zip(p,v)];remaining-=distance
        norm=math.sqrt(sum(x*x for x in p));p=[x/norm for x in p]
        projection=sum(a*b for a,b in zip(p,v))
        v=[b-2*projection*a for a,b in zip(p,v)]
        norm=math.sqrt(sum(x*x for x in v));v=[x/norm for x in v]
    return tuple(p)


def boundary_collision(index, time, radius):
    """External molecule approaches a rubber surface then elastically rebounds.

    The wall is locally stationary; direction points away from balloon centre.
    Parallel trajectories are separated along the spherical boundary.
    """
    angle=(index%7-3)*.14
    latitude=(index//7-1)*.18
    direction=(math.cos(angle)*math.cos(latitude),math.sin(angle)*math.cos(latitude),math.sin(latitude))
    travel=abs((time+index*.17)%2-1)*1.35
    distance=radius+.105+travel
    return tuple(distance*x for x in direction)
