"""Catch disappearing coins and a transport curve that peaks at the wrong balance."""
import importlib
import importlib.util
import math
import pytest


def module():
    name = 'video_harness.blender_renderer.energy_transport_math'
    assert importlib.util.find_spec(name) is not None, 'energy transport model is not implemented'
    return importlib.import_module(name)


def test_surplus_adds_and_deficit_spends_without_changing_coin_identity():
    m = module()
    ledgers = m.coin_ledger([3, 2, 1, -2])
    assert [x['outgoing'] for x in ledgers] == [[0, 1, 2], [0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5], [2, 3, 4, 5]]
    assert ledgers[-1]['spent'] == [0, 1]
    for x in ledgers:
        assert set(x['incoming'] + x['added']) == set(x['outgoing'] + x['spent'])
        assert len(x['outgoing'] + x['spent']) == len(set(x['outgoing'] + x['spent']))


def test_deficit_cannot_spend_coins_that_never_arrived():
    with pytest.raises(ValueError, match='deficit'):
        module().coin_ledger([1, -2])


def test_transport_maximum_matches_zero_radiation_budget_and_poleward_symmetry():
    m = module()
    peak = math.degrees(math.asin(1 / math.sqrt(3)))
    assert m.transport(0) == pytest.approx(0)
    assert m.transport(90) == pytest.approx(0, abs=1e-12)
    assert m.radiation_budget(peak) == pytest.approx(0, abs=1e-12)
    assert m.transport(peak) > m.transport(peak - 1)
    assert m.transport(peak) > m.transport(peak + 1)
    for latitude in (5, 15, 45, 70):
        h = 1e-4
        derivative = (m.transport(latitude+h)-m.transport(latitude-h))/math.radians(2*h)
        assert derivative == pytest.approx(m.radiation_budget(latitude)*math.cos(math.radians(latitude)), rel=1e-6)
        assert m.transport(-latitude) == pytest.approx(-m.transport(latitude))


def fixture_job():
    return dict(scene_graph='energy-transport-blender-v1', sequence_id='SEQ01', canonical_fps=30,
                duration_frames=4800, frame_count=1440, output={'width':384,'height':216,'fps':9},
                style={'asset_root':str(__import__('pathlib').Path('assets').resolve())},
                timeline=[dict(beat_id=f'B{i:02d}',controller='energy-transport',start_frame=(i-1)*300,end_frame=i*300,
                               controller_options={'scene_id':i}) for i in range(1,17)],
                canonical_state_cache=[dict(canonical_frame=f,active_beat_ids=[f'B{f//300+1:02d}'],simulation_time=f/30) for f in range(4800)])


def test_story_state_is_seekable_and_preserves_all_coins_through_each_transfer():
    m = module()
    assert hasattr(m, 'Story'), 'continuous transport story is not implemented'
    story=m.Story(fixture_job()['timeline'],30)
    # Every same ID crosses consecutive desks; after the deficit 0,1 stay spent.
    a=story.state(6*300-1)
    b=story.state(8*300-1)
    end=story.state(10*300-1)
    assert len(a['coins'])==9
    assert a['coin_desks'][:3]==[1,1,1]
    assert b['coin_desks'][:6]==[3]*6
    assert end['coin_desks'][:6]==[3,3,4,4,4,4]
    assert end['spent'][:6]==[True,True,False,False,False,False]
    for f in [4799, 3, 2000, 1500, 3]:
        assert story.state(f)==m.Story(fixture_job()['timeline'],30).state(f)


def test_native_renderer_registration_and_rejects_broken_timeline():
    from video_harness.blender_backend import renderer_modules,validate_blender_job
    assert renderer_modules('energy-transport-blender-v1')==('energy_transport','EnergyTransportGallery')
    job=fixture_job()
    validate_blender_job(job)
    job['timeline'][2]['start_frame']+=1
    with pytest.raises(ValueError,match='contiguous'):
        validate_blender_job(job)


def test_energy_simulation_preserves_run_assets_and_rejects_wrong_physics(tmp_path):
    import json
    from video_harness.simulation import load_simulation
    from video_harness.sequence_render import _physics_payload, _style_payload
    from video_harness.models import ScriptArtifact
    from pathlib import Path
    # Existing minimal script fixture, independent of local run/voice outputs.
    from video_harness.tests.test_shorts import titled_run
    titled_run(tmp_path,languages='en')
    script=ScriptArtifact.model_validate_json((tmp_path/'script.json').read_text())
    config={'schema_version':1,'preset':'energy-transport-blender',
            'output':{'width':1920,'height':1080,'fps':30,'video_codec':'h264','audio_codec':'aac'},
            'physics':{'model':'zonal-energy-budget-teaching-model'},
            'style':{'asset_root':str(tmp_path/'assets'),'seed':1},
            'scenes':[{'scene_id':s.scene_id} for s in script.scenes]}
    (tmp_path/'simulation.json').write_text(json.dumps(config))
    parsed=load_simulation(tmp_path,script)
    assert _style_payload(parsed)['asset_root']==str(tmp_path/'assets')
    assert _physics_payload(parsed)['model']=='zonal-energy-budget-teaching-model'
    config['physics']['model']='unrelated-model'
    (tmp_path/'simulation.json').write_text(json.dumps(config))
    with pytest.raises(ValueError):load_simulation(tmp_path,script)


def test_incoming_coins_do_not_overlap_students_own_surplus():
    m=module();story=m.Story(fixture_job()['timeline'],30)
    state=story.state(1800)
    # Incoming three plus this student's two must occupy five separate slots.
    positions=state['coins'][:5]
    for i,a in enumerate(positions):
        for b in positions[i+1:]:
            assert math.dist(a,b)>.21, 'coins overlap at the handoff'


def test_passes_go_behind_students_and_around_their_bodies():
    m=module();story=m.Story(fixture_job()['timeline'],30)
    # Seated figures face -Y towards the teacher, so passing behind is +Y.
    before=story.state(1500)['coins'][0]
    after=story.state(1799)['coins'][0]
    midway=story.state(1710)['coins'][0]
    assert after[1]>before[1]
    assert midway[0]<-.5, 'coins must go through the aisle, not the seated torso'


def test_transfer_clears_the_seated_students_arm_envelope():
    story=module().Story(fixture_job()['timeline'],30)
    # The left forearm extends to x=-.53. Keep the disc's near edge beyond it
    # while passing the student's y range behind the first desk.
    for frame in range(1500,1800):
        x,y,z=story.state(frame)['coins'][2]
        if -1.75<y<-1.1:
            assert x+.105<-.53, 'right edge of the packet intersects a seated arm'


def test_four_remaining_coins_keep_their_spacing_in_transit():
    story=module().Story(fixture_job()['timeline'],30)
    for frame in range(2700,3000):
        positions=story.state(frame)['coins'][2:6]
        for i,a in enumerate(positions):
            for b in positions[i+1:]:
                assert math.dist(a,b)>.21, 'repacking the remaining coins causes them to intersect'


def test_radiation_arrows_decrease_poleward_and_match_transport_budget():
    m = module()
    low_in, low_out = m.radiation_fluxes(12)
    high_in, high_out = m.radiation_fluxes(60)
    assert low_in > high_in > 0
    assert low_out > high_out > 0
    assert low_in > low_out and high_in < high_out
    assert low_in - high_in > low_out - high_out
    for latitude in range(-90, 91, 5):
        absorbed, emitted = m.radiation_fluxes(latitude)
        assert absorbed > 0 and emitted > 0
        assert absorbed - emitted == pytest.approx(.4 * m.radiation_budget(latitude), abs=1e-12)


def test_authored_camera_approach_begins_before_narration_boundary():
    m=module();job=fixture_job()
    job['timeline'][2]['controller_options'].update(camera_move_seconds=3.2,camera_lead_seconds=1.6)
    story=m.Story(job['timeline'],30)
    # Scene 2 already moves towards the same globe, arriving during scene 3.
    far=story.state(540)['camera'][0]
    approaching=story.state(580)['camera'][0]
    boundary=story.state(600)['camera'][0]
    close=story.state(660)['camera'][0]
    assert far[1] < approaching[1] < boundary[1] < close[1]
    # Draft-rate neighbouring poses must not cover the entire move in one step.
    assert max(math.dist(story.state(f)['camera'][0],story.state(f+3)['camera'][0])
               for f in range(550,650)) < .3
