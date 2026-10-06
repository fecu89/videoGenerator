import math
import pytest
from video_harness.blender_renderer.vorticity_story_math import (
    story_state, validate_job, westerly_point, westerly_state)
from video_harness.blender_backend import renderer_modules


def timeline():
    return [dict(beat_id=f'B{n:02d}',start_frame=(n-1)*300,end_frame=n*300,
                 controller='vorticity-story',controller_options={'scene_number':n})
            for n in range(1,23)]


def test_migrating_column_preserves_absolute_vorticity_and_stays_off_axis():
    states=[story_state(f,timeline(),30) for f in range(3600,5100)]
    assert states[0]['latitude']==70
    assert states[899]['latitude']==40
    assert states[-1]['latitude']==70
    assert all(40<=s['latitude']<=70 for s in states)
    assert all(s['planetary']+s['relative']==pytest.approx(2*math.sin(math.radians(70))) for s in states)
    assert states[899]['relative']>0
    assert states[-1]['relative']==pytest.approx(0)


def test_ground_observer_does_not_reset_physical_rotation():
    states=[story_state(f,timeline(),30) for f in range(2390,2420)]
    assert all(b['physical_angle']>a['physical_angle'] for a,b in zip(states,states[1:]))
    assert max(abs(b['observer_angle']-a['observer_angle']) for a,b in zip(states,states[1:]))<.01


def test_state_is_independent_of_evaluation_order():
    frames=[4000,2400,5000,1000]
    expected={f:story_state(f,timeline(),30) for f in frames}
    assert {f:story_state(f,timeline(),30) for f in reversed(frames)}==expected
    assert renderer_modules('vorticity-story-blender-v2')==('vorticity_story','VorticityStoryGallery')


def test_rejects_previous_nineteen_scene_order():
    job=dict(scene_graph='vorticity-story-blender-v2',frame_count=10,duration_frames=5700,
             canonical_fps=30,output=dict(width=384,height=216,fps=12),timeline=timeline()[:19])
    with pytest.raises(ValueError,match='22-part'):
        validate_job(job)


def test_westerly_wave_stays_at_mid_latitudes_and_moves_east():
    points=[westerly_point(math.tau*i/360,3) for i in range(360)]
    assert all(math.hypot(*p)==pytest.approx(3) for p in points)
    latitudes=[math.degrees(math.asin(p[1]/3)) for p in points]
    assert 32.9<min(latitudes)<33.1 and 56.9<max(latitudes)<57.1
    # Seen from above the north pole (+Y), later parcel positions turn counterclockwise.
    a,b=[westerly_point(westerly_state(t)['parcel_longitude']) for t in (0,1)]
    assert a[2]*b[0]-a[0]*b[2]>0
    assert westerly_state(1)['spin']>westerly_state(0)['spin']


def test_meridian_turn_never_spins_the_globe_backwards():
    angles=[story_state(f,timeline(),30)['angle'] for f in range(2400,3600)]
    assert all(b>=a-1e-9 for a,b in zip(angles,angles[1:]))
    end=story_state(3300,timeline(),30)['angle']
    assert math.cos(end)==pytest.approx(1)


def test_each_migration_finishes_within_its_question_scene():
    assert story_state(3600+300,timeline(),30)['latitude']==pytest.approx(40)
    assert story_state(4500+300,timeline(),30)['latitude']==pytest.approx(70)
    assert story_state(3600+150,timeline(),30)['latitude']<60
