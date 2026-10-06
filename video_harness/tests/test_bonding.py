import math
import pytest
from video_harness.blender_renderer.bonding_math import complementary, tetrahedron, dna_point, carbon_bonds_valid
from video_harness.blender_backend import renderer_modules


def test_tetrahedron_has_equal_edges_and_centered_vertices():
    points = tetrahedron(2)
    edges = [math.dist(a,b) for i,a in enumerate(points) for b in points[i+1:]]
    assert max(edges)-min(edges) < 1e-12
    assert all(abs(sum(p[k] for p in points)) < 1e-12 for k in range(3))


def test_pairing_preserves_antiparallel_complement_order():
    sequence = 'ATGCCGTA'
    assert complementary(sequence) == 'TACGGCAT'
    assert complementary(complementary(sequence)) == sequence
    with pytest.raises(KeyError): complementary('AU')


def test_helix_strands_are_opposite_and_right_handed():
    a = dna_point(0,0); b = dna_point(0,1); next_a = dna_point(1,0)
    assert a[1] == b[1]
    assert math.dist(a,b) == pytest.approx(4)
    assert next_a[1] > a[1] and next_a[2] < a[2]
    assert dna_point(3,0,twist=0)[0] == 2


def test_carbon_topology_rejects_five_bonds_and_duplicates():
    assert carbon_bonds_valid(6,[(0,1),(1,2),(1,3),(3,4),(3,5)])
    assert not carbon_bonds_valid(6,[(0,i) for i in range(1,6)])
    assert not carbon_bonds_valid(2,[(0,1),(1,0)])


def test_existing_renderer_routes_are_preserved():
    assert renderer_modules('bonding-blender-v1') == ('bonding','BondingGallery')
    assert renderer_modules('vorticity-blender-v1') == ('vorticity','VorticityGallery')


def test_flow_requires_all_ten_scenes_on_one_contiguous_clock():
    from video_harness.blender_renderer.bonding_math import validate_job

    beats=[{'beat_id':f'B{i+1:02d}','controller':'bonding-minerals','start_frame':i,'end_frame':i+1,'controller_options':{'scene_number':i+1}} for i in range(10)]
    job={'scene_graph':'bonding-flow-blender-v2','frame_count':10,'duration_frames':10,'canonical_fps':30,'output':{'width':384,'height':216,'fps':12},'timeline':beats,'canonical_state_cache':[{'canonical_frame':i,'active_beat_ids':[f'B{i+1:02d}'],'simulation_time':i/30} for i in range(10)]}
    validate_job(job)
    beats[5]['start_frame']=4
    with pytest.raises(ValueError,match='contiguous'):validate_job(job)
    beats[5]['start_frame']=5
    beats[5]['controller_options']['scene_number']=4
    with pytest.raises(ValueError,match='ten scenes'):validate_job(job)
