import math
import pytest
from video_harness.blender_renderer.vorticity_math import planetary, relative, vortex_velocity, contributions
from video_harness.blender_backend import renderer_modules, validate_blender_job


def test_projection_and_conserved_absolute_vorticity():
    assert planetary(0) == 0
    assert planetary(90) == pytest.approx(2)
    assert planetary(-90) == pytest.approx(-2)
    for latitude in range(0, 91):
        assert planetary(latitude)+relative(latitude) == pytest.approx(planetary(40))
    assert relative(60) < 0 < relative(20)
    with pytest.raises(ValueError): planetary(91)


def test_eastern_flanks_have_opposite_meridional_velocity():
    for circulation, sign in [(-1,-1),(1,1)]:
        u,v=vortex_velocity(1,0,0,0,circulation)
        assert u == 0 and math.copysign(1,v)==sign
        assert vortex_velocity(-1,0,0,0,circulation)[1] == -v


def test_stationary_polar_air_is_not_a_parcel_displaced_from_40_degrees():
    for progress in (0, .5, 1):
        assert contributions(9, progress) == pytest.approx((1.8793852415718166, 0))
        assert contributions(12, progress)[1] == 0
        for scene in (14,15):
            assert sum(contributions(scene, progress)) == pytest.approx(planetary(40))


def test_vorticity_dispatch_rejects_unsupported_controller():
    assert renderer_modules('vorticity-blender-v1') == ('vorticity','VorticityGallery')
    job=dict(scene_graph='vorticity-blender-v1',frame_count=1,duration_frames=1,
             canonical_fps=30,output=dict(width=16,height=9,fps=30),
             timeline=[dict(beat_id='B01',controller='fake',controller_options={'scene_number':1})],
             canonical_state_cache=[dict(canonical_frame=0,simulation_time=0,active_beat_ids=['B01'])])
    with pytest.raises(ValueError,match='controller'): validate_blender_job(job)
    job['timeline'][0]['controller']='vorticity-flow'
    validate_blender_job(job)
    job['canonical_state_cache'][0]['simulation_time']=float('nan')
    with pytest.raises(ValueError,match='time'): validate_blender_job(job)


def test_earth_observer_change_never_resets_the_globe():
    from video_harness.blender_renderer.vorticity_math import earth_pose
    timeline=[dict(start_frame=a,end_frame=b,controller_options={'scene_number':n})
              for n,a,b in [(7,0,309),(8,309,574),(9,574,880),(10,880,1160),
                            (11,1160,1443),(12,1443,1740)]]
    poses=[earth_pose(f,timeline,30) for f in range(1740)]
    for f in (309,574,880,1160,1443):
        assert abs(poses[f]['angle']-poses[f-1]['angle']) < .02
        assert abs(poses[f]['tilt']-poses[f-1]['tilt']) < .02
        assert abs(poses[f]['latitude']-poses[f-1]['latitude']) < .02
    # A co-rotating observer sees no relative motion, without losing orientation.
    assert poses[500]['angle'] == pytest.approx(poses[400]['angle'])
    assert poses[500]['angle'] > 1.8
    # An inertial observer before/after the comparison sees eastward rotation.
    assert poses[200]['angle'] > poses[100]['angle']
    assert poses[800]['angle'] > poses[700]['angle']
    # Look down on the northern hemisphere and keep the air off the pole.
    assert math.sin(poses[100]['tilt']) > .96
    assert 65 < math.degrees(poses[100]['latitude']) < 80


def test_camera_framing_connects_explanations_and_returns_to_the_opening():
    from video_harness.blender_renderer.vorticity_direction_math import framing
    for left,right in [(1,2),(2,3),(3,4),(5,6),(7,8),(8,9),(13,14),
                       (14,15),(15,16),(16,17),(17,18),(18,19)]:
        assert framing(left,1)['zoom'] == pytest.approx(framing(right,0)['zoom'])
    assert framing(19,1)['zoom'] == pytest.approx(framing(1,0)['zoom'])
    # A stationary slide cannot satisfy the intended change in viewing scale.
    assert framing(4,1)['zoom'] < framing(4,0)['zoom']/2
    assert framing(19,1)['zoom'] > framing(19,0)['zoom']


def test_round_handoffs_keep_their_projected_sizes():
    from video_harness.blender_renderer.vorticity_direction_math import framing
    # Radius / orthographic width is independent of output resolution.
    assert .85/(24*framing(4,1)['zoom']) == pytest.approx(3.3/24)
    assert .55/(24*framing(12,1)['zoom']) == pytest.approx(1/24)
