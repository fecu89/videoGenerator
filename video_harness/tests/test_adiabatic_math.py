import math
import pytest
from video_harness.blender_renderer.adiabatic_math import adiabatic_state, elastic_velocities, particle_position


def test_expansion_cools_and_work_equals_internal_energy_loss():
    initial = adiabatic_state(1)
    expanded = adiabatic_state(2)
    assert expanded['temperature'] < initial['temperature']
    assert expanded['pressure'] < initial['pressure']
    assert expanded['pressure'] * 2 ** 1.4 == pytest.approx(initial['pressure'])
    assert expanded['work'] == pytest.approx(initial['internal_energy'] - expanded['internal_energy'])
    assert expanded['speed'] ** 2 / initial['speed'] ** 2 == pytest.approx(expanded['temperature'] / initial['temperature'])


def test_elastic_ball_panel_collision_conserves_energy_and_momentum():
    ball, panel = elastic_velocities(1, 4, 2, 0)
    assert -2 < ball < 0 < panel
    assert ball + 4 * panel == pytest.approx(2)
    assert .5 * ball ** 2 + 2 * panel ** 2 == pytest.approx(2)


def test_particles_stay_inside_fixed_box_and_are_order_independent():
    before = particle_position(5, .6, 2)
    particle_position(5, 80, 2)
    assert particle_position(5, .6, 2) == before
    for i in range(30):
        for time in (0, .8, 3, 300):
            assert all(abs(x) <= 2 for x in particle_position(i, time, 2))


@pytest.mark.parametrize('volume', [0, -1, math.inf, math.nan])
def test_invalid_volume_rejected(volume):
    with pytest.raises(ValueError):
        adiabatic_state(volume)


def test_spherical_particle_reflects_without_crossing_wall():
    from video_harness.blender_renderer.adiabatic_math import sphere_particle
    for i in range(12):
        for t in (0, 1, 7.8, 60):
            assert sum(x*x for x in sphere_particle(i, t)) <= 1 + 1e-10
    before=sphere_particle(3, 5)
    sphere_particle(3, 30)
    assert sphere_particle(3, 5)==before
    # Between impacts speed is one normalized radius per phase unit.
    a=sphere_particle(0,0);b=sphere_particle(0,.001)
    assert math.dist(a,b)==pytest.approx(.001)


def test_external_balloon_particle_hits_surface_and_rebounds_outward():
    from video_harness.blender_renderer.adiabatic_math import boundary_collision
    before=boundary_collision(0, .9, 1.5)
    hit=boundary_collision(0, 1., 1.5)
    after=boundary_collision(0, 1.1, 1.5)
    assert math.sqrt(sum(x*x for x in hit))==pytest.approx(1.605)
    assert math.dist(before,(0,0,0))>math.dist(hit,(0,0,0))
    assert math.dist(after,(0,0,0))>math.dist(hit,(0,0,0))


def test_authored_camera_path_moves_over_full_beat_without_teleport():
    from video_harness.blender_renderer.adiabatic_math import state_at
    job={'canonical_fps':30,'timeline':[{'start_frame':0,'end_frame':301,'controller_options':{'initial':{'camera_z':2},'state':{'camera_z':12},'camera_move_seconds':10}}]}
    assert state_at(job,0)['camera_z']==2
    assert state_at(job,150)['camera_z']==pytest.approx(7)
    assert state_at(job,300)['camera_z']==12
    assert state_at(job,150)==state_at(job,150)
