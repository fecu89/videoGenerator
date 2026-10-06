"""Deterministic teaching geometry; lengths are illustrative, not molecular dynamics."""
import math

GRAPH = 'bonding-blender-v1'
CONTROLLERS = {'bonding-minerals', 'bonding-carbon', 'bonding-protein', 'bonding-dna'}
COMPLEMENT = {'A': 'T', 'T': 'A', 'G': 'C', 'C': 'G'}


def complementary(sequence):
    return ''.join(COMPLEMENT[base] for base in sequence)


def tetrahedron(radius=1.0):
    s = radius / math.sqrt(3)
    return [(s*x, s*y, s*z) for x, y, z in [(1,1,1), (1,-1,-1), (-1,1,-1), (-1,-1,1)]]


def dna_point(index, strand, twist=1.0, radius=2.0, rise=.52):
    """Right-handed helix around +Y; strand 1 runs antiparallel chemically."""
    angle = index * math.tau / 10.5 * twist + strand * math.pi
    return radius*math.cos(angle), (index-7.5)*rise, -radius*math.sin(angle)


def carbon_bonds_valid(atom_count, edges):
    degree = [0]*atom_count
    seen = set()
    for a, b in edges:
        edge = tuple(sorted((a,b)))
        if a == b or not 0 <= a < atom_count or not 0 <= b < atom_count or edge in seen:
            return False
        seen.add(edge); degree[a] += 1; degree[b] += 1
    return all(n <= 4 for n in degree)


def validate_job(job):
    if job.get('scene_graph') not in {GRAPH, 'bonding-flow-blender-v2'}:
        raise ValueError('unsupported bonding graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid '+key)
    if any(not isinstance(job.get('output', {}).get(k), int) or job['output'][k] <= 0 for k in ('width','height','fps')):
        raise ValueError('invalid output')
    timeline = job.get('timeline', [])
    if not timeline or any(b['controller'] not in CONTROLLERS for b in timeline):
        raise ValueError('unknown bonding controller')
    if job['scene_graph'] == 'bonding-flow-blender-v2':
        if [b.get('controller_options', {}).get('scene_number') for b in timeline] != list(range(1, 11)):
            raise ValueError('continuous bonding flow requires all ten scenes in order')
        if (timeline[0]['start_frame'] != 0 or timeline[-1]['end_frame'] != job['duration_frames']
                or any(a['end_frame'] != b['start_frame'] for a,b in zip(timeline,timeline[1:]))):
            raise ValueError('continuous bonding flow requires a contiguous timeline')
    for beat in timeline:
        if beat.get('controller_options', {}).get('scene_number') not in range(1,11):
            raise ValueError('scene_number must be 1..10')
    cache = job.get('canonical_state_cache', [])
    if len(cache) != job['duration_frames']:
        raise ValueError('canonical cache length mismatch')
    ids = {b['beat_id'] for b in timeline}; previous = -math.inf
    for i, state in enumerate(cache):
        if state['canonical_frame'] != i or not state['active_beat_ids'] or not set(state['active_beat_ids']) <= ids:
            raise ValueError('invalid canonical cache')
        if not math.isfinite(state['simulation_time']) or state['simulation_time'] < previous:
            raise ValueError('invalid simulation time')
        previous = state['simulation_time']
