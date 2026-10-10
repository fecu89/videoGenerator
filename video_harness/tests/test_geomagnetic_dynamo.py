"""Catch reversed magnetic polarity, flow leaving the shell, and reset clocks."""
import importlib
import importlib.util
import math
import pytest


def model():
    name='video_harness.blender_renderer.geomagnetic_math'
    assert importlib.util.find_spec(name) is not None, 'geomagnetic model is missing'
    return importlib.import_module(name)


def timeline():
    return [dict(beat_id=f'B{i:02}',controller='geomagnetic-dynamo',start_frame=(i-1)*180,
                 end_frame=i*180,controller_options={'scene_id':i}) for i in range(1,26)]


def test_equatorial_field_points_towards_geographic_north_and_has_dipole_decay():
    m=model()
    assert m.dipole_field((0,-3,0))[2]>0
    assert m.dipole_field((0,0,3))[2]<0
    for a,b in zip(m.dipole_field((2,0,1)),m.dipole_field((4,0,2))):
        assert b==pytest.approx(a/8)


def test_external_field_paths_follow_field_and_never_enter_the_globe():
    m=model()
    for azimuth in (0,1,3):
        points=m.field_path(5.4,azimuth,3.05,96)
        assert points[0][2]<0<points[-1][2]
        assert min(math.sqrt(sum(v*v for v in p)) for p in points)>=3.05-1e-9
        for i in range(1,len(points)-1):
            delta=[points[i+1][k]-points[i-1][k] for k in range(3)]
            field=m.dipole_field(points[i])
            assert sum(a*b for a,b in zip(delta,field))>0


def test_bar_field_leaves_red_north_pole_instead_of_entering_it():
    m=model();points=m.bar_field_path(2.6,0)
    assert points[0][2]>0>points[-1][2]
    for i in range(1,len(points)-1):
        tangent=[points[i+1][k]-points[i-1][k] for k in range(3)]
        field=m.dipole_field(points[i])
        assert sum(a*b for a,b in zip(tangent,field))<0


def test_conceptual_flow_is_periodic_and_remains_in_liquid_shell():
    m=model()
    for lane in range(8):
        for t in (0,1,4,10):
            p=m.flow_point(lane,t)
            assert .62<math.sqrt(sum(v*v for v in p))<1.65
            assert p==pytest.approx(m.flow_point(lane,t+m.FLOW_PERIOD))


def test_columnar_flow_circulates_about_local_rotation_parallel_columns():
    m=model()
    for lane in range(8):
        points=[m.flow_point(lane,m.FLOW_PERIOD*i/96) for i in range(97)]
        # A fixed meridional ellipse cannot explain azimuthal circulation.
        assert max(p[1] for p in points)-min(p[1] for p in points)>.20
        assert max(p[0] for p in points)-min(p[0] for p in points)>.20
        assert min(math.sqrt(sum(v*v for v in p)) for p in points)>.98


def test_single_parcel_cools_as_it_moves_away_from_inner_core():
    m=model()
    near,hot=m.parcel_state(0)
    far,cold=m.parcel_state(.5)
    assert math.sqrt(sum(v*v for v in far))>math.sqrt(sum(v*v for v in near))
    assert hot>cold
    for i in range(97):
        p,temp=m.parcel_state(i/96)
        assert .98<math.sqrt(sum(v*v for v in p))<1.70
        assert 0<=temp<=1


def test_wire_field_direction_matches_upward_conventional_current():
    m=model()
    p=m.wire_field_point(0)
    later=m.wire_field_point(.01)
    tangent=tuple(b-a for a,b in zip(p,later))
    expected=(-p[1],p[0],0)
    assert sum(a*b for a,b in zip(tangent,expected))>0


def test_solar_wind_deformation_keeps_surface_anchors_and_extends_night_side():
    m=model()
    day=m.field_path(6.2,math.pi)
    night=m.field_path(6.2,0)
    assert m.magnetosphere_path(day,1)[0]==pytest.approx(day[0])
    assert m.magnetosphere_path(day,1)[-1]==pytest.approx(day[-1])
    assert max(p[0] for p in m.magnetosphere_path(night,1))>2*max(p[0] for p in night)
    assert abs(min(p[0] for p in m.magnetosphere_path(day,1)))<.8*abs(min(p[0] for p in day))
    for azimuth in (0,.7,math.pi,4.6):
        points=m.field_path(6.2,azimuth)
        for q in (0,.25,.5,1):
            assert min(math.sqrt(sum(v*v for v in p)) for p in m.magnetosphere_path(points,q))>=3.05-1e-8


def test_solar_wind_particles_move_from_sun_and_divert_around_earth():
    m=model()
    for lane in range(6):
        points=[m.solar_wind_point(i/100,lane) for i in range(101)]
        assert all(a[0]<b[0] for a,b in zip(points,points[1:]))
        assert points[0][0]<-7 and points[-1][0]>15
        assert min(math.sqrt(sum(v*v for v in p)) for p in points)>3.1


def test_space_reveal_returns_inside_and_ending_removes_explanatory_marks():
    m=model();s=m.Story(timeline(),30)
    assert s.state(s.at(20,.65))['sun']>.9
    assert s.state(s.at(20,.65))['cutaway']<.01
    assert s.state(s.at(21,.65))['cutaway']>.9
    assert s.state(s.at(22,.5))['compare']>.9
    assert s.state(s.at(23,.8))['magnetosphere']>.9
    assert s.state(s.at(25,.9))['field']==0
    assert s.state(s.at(25,.9))['compass']==0


def test_revised_story_hides_compass_inside_and_shows_whole_field_after_induction():
    m=model();s=m.Story(timeline(),30)
    assert s.state(s.at(6,.5))['compass']==0
    assert s.state(s.at(24,.8))['compass']>0
    assert s.state(s.at(8,.5))['compare']>0
    assert s.state(s.at(10,.5))['single']>0
    assert s.state(s.at(16,.9))['camera'][2]>=13
    assert s.state(s.at(17,.5))['wire']>0


def test_seekable_story_keeps_camera_and_reveal_continuous_at_scene_boundaries():
    m=model();story=m.Story(timeline(),30)
    expected=story.state(701)
    story.state(4200);story.state(4)
    assert story.state(701)==expected
    for f in range(180,4500,180):
        a,b=story.state(f-1),story.state(f)
        assert math.dist(a['camera'][0],b['camera'][0])<.12
        assert abs(a['cutaway']-b['cutaway'])<.04
    assert story.state(0)['current']==0
    assert story.state(2800)['current']>0


def test_job_contract_rejects_gaps_and_missing_scene_before_native_render():
    from video_harness.blender_backend import validate_blender_job
    job=dict(scene_graph='geomagnetic-dynamo-blender-v1',duration_frames=4500,
             canonical_fps=30,frame_count=1350,timeline=timeline(),
             canonical_state_cache=[dict(canonical_frame=f,simulation_time=f/30) for f in range(4500)])
    validate_blender_job(job)
    job['timeline'][4]['start_frame']+=1
    with pytest.raises(ValueError,match='contiguous'):
        validate_blender_job(job)


def test_simulation_loads_run_assets_and_preserves_conceptual_physics(tmp_path):
    import json
    from video_harness.simulation import load_simulation
    from video_harness.sequence_render import _physics_payload,_style_payload
    from video_harness.models import ScriptArtifact
    from video_harness.tests.test_shorts import titled_run
    titled_run(tmp_path,languages='en')
    script=ScriptArtifact.model_validate_json((tmp_path/'script.json').read_text())
    config=dict(schema_version=1,preset='geomagnetic-dynamo-blender',
                output=dict(width=1920,height=1080,fps=30,video_codec='h264',audio_codec='aac'),
                physics={'model':'conceptual-geodynamo-dipole'},style={'asset_root':str(tmp_path/'assets')},
                scenes=[{'scene_id':s.scene_id} for s in script.scenes])
    (tmp_path/'simulation.json').write_text(json.dumps(config))
    loaded=load_simulation(tmp_path,script)
    assert _physics_payload(loaded)=={'model':'conceptual-geodynamo-dipole'}
    assert _style_payload(loaded)['asset_root']==str(tmp_path/'assets')
    config['physics']['model']='exact-observed-core-flow'
    (tmp_path/'simulation.json').write_text(json.dumps(config))
    with pytest.raises(ValueError):load_simulation(tmp_path,script)
