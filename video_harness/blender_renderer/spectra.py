"""Qualitative teaching model, not a synthetic stellar atmosphere solver.

Line positions stay fixed; strengths are illustrative smooth envelopes based
on the supplied textbook's Figure 15. They must not be read as measured data.
"""
import math

CONTROLLERS = {'spectra-compare', 'spectra-absorption', 'spectra-hydrogen',
    'spectra-intro', 'spectra-distance', 'spectra-dispersion',
    'spectra-temperature-question', 'spectra-atmosphere', 'spectra-elements',
    'spectra-atom', 'spectra-hot', 'spectra-cool', 'spectra-disambiguate',
    'spectra-classify', 'spectra-subtype', 'spectra-sun'}
HYDROGEN_POSITIONS = (0.08, 0.17, 0.35, 0.91)


def line_strengths(temperature):
    if temperature <= 0:
        raise ValueError('temperature must be positive')
    logt = math.log(temperature)
    bell = lambda center, width: math.exp(-0.5*((logt-math.log(center))/width)**2)
    return {'hydrogen': 0.08+0.78*bell(9000,0.34),
            'helium_ionized': 0.8*bell(36000,0.35),
            'metals': 0.7*bell(4700,0.32),
            'molecules': 0.75/(1+math.exp((temperature-3900)/220))}


def canonical_frame(output_frame, output_fps, canonical_fps, duration_frames):
    if output_fps <= 0 or canonical_fps <= 0 or duration_frames <= 0 or output_frame < 0:
        raise ValueError('invalid frame mapping')
    return min(duration_frames-1, output_frame*canonical_fps//output_fps)


def smooth(value):
    value = max(0.0,min(1.0,value))
    return value*value*(3-2*value)


def validate_job(job):
    if job.get('scene_graph') != 'stellar-spectra-blender-v1':
        raise ValueError('unsupported scene_graph')
    for key in ('frame_count','duration_frames','canonical_fps'):
        if not isinstance(job.get(key),int) or job[key] <= 0:
            raise ValueError(f'invalid {key}')
    output=job.get('output',{})
    if any(not isinstance(output.get(k),int) or output[k]<=0 for k in ('width','height','fps')):
        raise ValueError('invalid output')
    if len(job.get('canonical_state_cache',[])) != job['duration_frames']:
        raise ValueError('canonical state cache length mismatch')
    timeline=job.get('timeline',[])
    if not timeline or any(t['controller'] not in CONTROLLERS for t in timeline):
        raise ValueError('unknown Blender controller')
    ids={t['beat_id'] for t in timeline}
    previous=-float('inf')
    for frame,entry in enumerate(job['canonical_state_cache']):
        if entry['canonical_frame']!=frame or not entry['active_beat_ids'] or not set(entry['active_beat_ids'])<=ids:
            raise ValueError('invalid canonical state cache')
        if entry['simulation_time']<previous:
            raise ValueError('simulation time reversal')
        previous=entry['simulation_time']


def camera_transition_progress(job, elapsed):
    """Preset jobs opt in; historical jobs retain the original 0.75-second move."""
    seconds = job.get('camera_transition_seconds', .75) if job.get('pacing') else .75
    return smooth(elapsed / seconds) if seconds > 0 else 1.0
