import json
from pathlib import Path
import pytest
from video_harness.creative_gates import require_story_chain, story_digest, check_story_chain, check_continuity_plan, continuity_state_issues


def write_story(root):
    s={'scenes':[{'scene_id':1,'narration':'왜 작아 보일까요? 멀리 있기 때문입니다. 그런데 왜 가려질까요? 같은 방향에 있기 때문입니다.'}]}
    (root/'script.json').write_text(json.dumps(s,ensure_ascii=False))
    review={'schema_version':1,'script_sha256':story_digest(s),'reviewer':'test reviewer','verdict':'passed','scene_coverage':[{'scene_id':1,'role':'chain','reason':'두 질문과 답을 포함한다.'}], 'pairs':[
        {'question':{'scene_id':1,'quote':'왜 작아 보일까요?'},'answer':{'scene_id':1,'quote':'멀리 있기 때문입니다.'},'resolves_question':True,'answer_reason':'거리가 겉보기 크기를 결정한다.','causes_next_question':True,'next_question_reason':'작아 보이는 천체가 다른 천체를 가리는 조건을 묻는다.'},
        {'question':{'scene_id':1,'quote':'그런데 왜 가려질까요?'},'answer':{'scene_id':1,'quote':'같은 방향에 있기 때문입니다.'},'resolves_question':True,'answer_reason':'시선 방향이 같아 가림이 발생한다.','causes_next_question':None,'next_question_reason':None}]}
    (root/'story-chain.json').write_text(json.dumps(review,ensure_ascii=False));return s,review


def test_missing_failed_and_stale_story_are_blocked(tmp_path):
    s,review=write_story(tmp_path);require_story_chain(tmp_path)
    review['pairs'][0]['causes_next_question']=False
    (tmp_path/'story-chain.json').write_text(json.dumps(review))
    with pytest.raises(ValueError,match='story_chain'):require_story_chain(tmp_path)
    s,review=write_story(tmp_path);s['scenes'][0]['narration']+=' 바뀐 문장.'
    (tmp_path/'script.json').write_text(json.dumps(s))
    with pytest.raises(ValueError,match='stale'):require_story_chain(tmp_path)
    (tmp_path/'story-chain.json').unlink()
    with pytest.raises(ValueError,match='missing'):require_story_chain(tmp_path)


def test_fabricated_quote_and_reversed_answer_fail(tmp_path):
    s,r=write_story(tmp_path);r['pairs'][0]['answer']['quote']='없는 답변'
    assert check_story_chain(s,r)
    s,r=write_story(tmp_path);r['pairs'][0]['answer']=r['pairs'][0]['question']
    assert check_story_chain(s,r)


def test_voice_metadata_does_not_stale_content_review(tmp_path):
    s,r=write_story(tmp_path);s['scenes'][0].update(duration_seconds=8,audio_file='audioFiles/a.mp3')
    assert story_digest(s)==r['script_sha256']


def state(x=0,angle=0):
    import math
    return {'camera':{'position':[0,0,20],'rotation':[math.cos(angle/2),0,0,math.sin(angle/2)],'scale':[1,1,1],'projection':'ORTHO','ortho_scale':20,'lens':50},'actors':{'Moon':{'position':[x,0,0],'rotation':[1,0,0,0],'scale':[1,1,1],'radius':1,'visible':True}},'paths':{}}


def test_actual_pose_jump_and_missing_capture_fail():
    boundary={'mode':'continuous_3d','actors':[{'from':'Moon','to':'Moon'}]}
    before=[{'simulation_time':0,'continuity':state(0)},{'simulation_time':.1,'continuity':state(.1)}]
    after=[{'simulation_time':.2,'continuity':state(.2)},{'simulation_time':.3,'continuity':state(.3)}]
    assert not continuity_state_issues(boundary,before,after)
    after[0]['continuity']=state(5)
    assert continuity_state_issues(boundary,before,after)
    after[0].pop('continuity')
    assert continuity_state_issues(boundary,before,after)


def test_camera_roll_jump_fails_even_when_position_is_equal():
    import math
    boundary={'mode':'continuous_3d','actors':[{'from':'Moon','to':'Moon'}]}
    before=[{'simulation_time':0,'continuity':state()},{'simulation_time':.1,'continuity':state()}]
    after=[{'simulation_time':.2,'continuity':state(angle=math.pi/2)}]
    assert continuity_state_issues(boundary,before,after)


def write_plan(root, mode='continuous_3d'):
    from video_harness.creative_gates import digest
    local={'sequences':[{'sequence_id':'SEQ01','duration_frames':8,'timeline':[{'beat_id':'B01','start_frame':0,'end_frame':4},{'beat_id':'B02','start_frame':4,'end_frame':8}]}]}
    (root/'local-sequence-plan.json').write_text(json.dumps(local))
    plan={'schema_version':1,'local_sequence_plan_sha256':digest(root/'local-sequence-plan.json'),'reviewer':'Test reviewer','verdict':'passed','transitions':[{'from_beat':'B01','to_beat':'B02','mode':mode,'reviewed':True,'reason':'동일한 달의 접근에서 그림자 진입을 연속해서 보여준다.','actors':[{'from':'Moon','to':'Moon'}]}],'direction_checks':[]}
    (root/'continuity-plan.json').write_text(json.dumps(plan));return local,plan


def test_unreviewed_question_and_open_chain_fail(tmp_path):
    s,r=write_story(tmp_path);s['scenes'][0]['narration']+=' 그러면 다음은 뭘까요?';r['script_sha256']=story_digest(s)
    assert any('unreviewed_question' in e for e in check_story_chain(s,r))
    s,r=write_story(tmp_path);r['pairs'][-1]['causes_next_question']=True
    assert any('open_end' in e for e in check_story_chain(s,r))


@pytest.mark.parametrize('change', ['missing_boundary','unreviewed','pending','stale','missing_actors'])
def test_transition_contract_is_fail_closed(tmp_path,change):
    local,p=write_plan(tmp_path)
    if change=='missing_boundary':p['transitions']=[]
    elif change=='unreviewed':p['transitions'][0]['reviewed']=False
    elif change=='pending':p['verdict']='pending'
    elif change=='stale':p['local_sequence_plan_sha256']='0'*64
    else:p['transitions'][0]['actors']=[]
    from video_harness.creative_gates import digest
    assert check_continuity_plan(local,p,digest(tmp_path/'local-sequence-plan.json'))


def test_reviewed_cut_is_allowed_without_continuous_capture(tmp_path):
    local,p=write_plan(tmp_path,'cut');p['transitions'][0]['actors']=[]
    from video_harness.creative_gates import digest,check_render_continuity
    assert not check_continuity_plan(local,p,digest(tmp_path/'local-sequence-plan.json'))
    assert not check_render_continuity(tmp_path,local,{})


@pytest.mark.parametrize('fault', ['nan','zero_quaternion','missing_actor','time_jump','scale_jump','projection_jump'])
def test_invalid_actual_capture_fails(fault):
    b={'mode':'continuous_3d','actors':[{'from':'Moon','to':'Moon'}]}
    before=[{'simulation_time':0,'continuity':state()},{'simulation_time':.1,'continuity':state()}]
    next_state=state();after=[{'simulation_time':.2,'continuity':next_state}]
    if fault=='nan':next_state['camera']['position'][0]=float('nan')
    elif fault=='zero_quaternion':next_state['camera']['rotation']=[0,0,0,0]
    elif fault=='missing_actor':next_state['actors']={}
    elif fault=='time_jump':after[0]['simulation_time']=8
    elif fault=='scale_jump':next_state['actors']['Moon']['scale']=[3,3,3]
    else:next_state['camera']['projection']='PERSP'
    assert continuity_state_issues(b,before,after)


def test_smooth_acceleration_and_camera_roll_pass():
    b={'mode':'continuous_3d','actors':[{'from':'Moon','to':'Moon'}]}
    rows=[{'simulation_time':i*.1,'continuity':state(i*i*.1,i*.1)} for i in range(4)]
    assert not continuity_state_issues(b,rows[:3],rows[3:])


def test_reversed_refraction_and_observer_rotation_fail(tmp_path):
    import math
    from video_harness.creative_gates import check_render_continuity
    local,p=write_plan(tmp_path,'cut')
    p['direction_checks']=[{'sequence_id':'SEQ01','frame':7,'kind':'path_direction','reason':'위 대기의 굴절은 아래로 향해야 한다.','expected':'down','path':'beam'}, {'sequence_id':'SEQ01','start_frame':0,'frame':7,'kind':'screen_rotation','reason':'관측자 화면으로 반시계 회전해야 한다.','vector':[1,0,0],'expected':'counterclockwise'}]
    (tmp_path/'continuity-plan.json').write_text(json.dumps(p))
    def samples(sign):
        rows=[]
        for i in range(8):
            s=state(angle=sign*i*math.pi/14);s['paths']['beam']=[[0,0,0],[1,sign,0],[2,sign*2,0]]
            rows.append({'canonical_frame':i,'simulation_time':i/30,'continuity':s})
        return {'SEQ01':rows}
    assert not check_render_continuity(tmp_path,local,samples(-1))
    issues=check_render_continuity(tmp_path,local,samples(1))
    assert any('refraction_direction' in e for e in issues)
    assert any('screen_rotation' in e for e in issues)


def test_voice_force_cannot_start_synthesis_without_story_review(tmp_path):
    from video_harness.tests.test_voice import make_script,FakeSynthesizer
    from video_harness.voice import generate_audio
    from video_harness.settings import HarnessSettings
    path=tmp_path/'script.json';path.write_text(make_script(1).model_dump_json())
    synth=FakeSynthesizer({1:6})
    with pytest.raises(ValueError,match='story_chain'):
        generate_audio(path,force=True,synthesizer=synth,settings=HarnessSettings())
    assert synth.requested_ids==[]
    assert json.loads((tmp_path/'story-gate.json').read_text())['status']=='failed'


def test_approval_and_force_production_block_without_review(tmp_path):
    from video_harness.tests.test_video_plan_approval import _write_reviewable_run
    from video_harness.video_plan_approval import approve_video_plan
    from video_harness.produce_local import produce_local
    from video_harness.settings import HarnessSettings
    _write_reviewable_run(tmp_path)
    with pytest.raises(ValueError,match='story_chain'):approve_video_plan(tmp_path)
    assert not (tmp_path/'video-plan-approval.json').exists()
    with pytest.raises(ValueError,match='승인'):produce_local(tmp_path,force=True,settings=HarnessSettings())
    assert not (tmp_path/'final.mp4').exists()


def test_publication_failure_keeps_existing_final(tmp_path):
    from video_harness.produce_local import publish_staged_outputs
    (tmp_path/'final.mp4').write_bytes(b'previous approved video')
    staging=tmp_path/'.local-final-test';staging.mkdir();(staging/'final.mp4').write_bytes(b'unreviewed replacement')
    with pytest.raises(ValueError,match='승인'):publish_staged_outputs(tmp_path,staging)
    assert (tmp_path/'final.mp4').read_bytes()==b'previous approved video'


def test_legacy_final_route_cannot_bypass_continuity(tmp_path):
    from video_harness.creative_gates import require_legacy_render_gate
    write_story(tmp_path)
    with pytest.raises(ValueError,match='Final publication requires produce'):require_legacy_render_gate(tmp_path,'final')


def test_cli_missing_review_returns_failure_and_diagnostic(tmp_path):
    import subprocess,sys
    result=subprocess.run([sys.executable,'-m','video_harness','check-creative','story',str(tmp_path)],capture_output=True,text=True)
    assert result.returncode!=0
    assert json.loads((tmp_path/'story-gate.json').read_text())['status']=='failed'


def test_prompt_staging_preserves_continuity_appendix(tmp_path):
    from video_harness.tests.test_video_plan_approval import _write_reviewable_run
    from video_harness.pipeline import load_pipeline_context,_write_staged_prompts
    from video_harness.creative_gates import render_continuity_review
    from video_harness.prompt_compiler import write_compiled_artifacts
    _write_reviewable_run(tmp_path)
    p={'transitions':[{'from_beat':'B01','to_beat':'B02','mode':'continuous_3d','reason':'같은 대상의 세계 좌표를 유지해 이어간다.'}],'direction_checks':[]}
    (tmp_path/'continuity-plan.json').write_text(json.dumps(p))
    context=load_pipeline_context(tmp_path)
    write_compiled_artifacts(tmp_path,context.production,context.script,local_plan=context.local,online_plan=context.online)
    expected=(tmp_path/'video-plan.md').read_bytes()
    _write_staged_prompts(context)
    assert (tmp_path/'video-plan.md').read_bytes()==expected
    assert render_continuity_review(tmp_path).encode() in expected


def test_current_approval_still_cannot_publish_a_rendered_jump(tmp_path):
    from datetime import datetime,timezone
    from video_harness.video_plan_approval import VideoPlanApproval,_current_hashes
    from video_harness.produce_local import publish_staged_outputs
    write_story(tmp_path);write_plan(tmp_path)
    for name in ('production-plan.json','online-plan.json','variant-plan.json','video-plan.md'):
        (tmp_path/name).write_text('{}')
    record=VideoPlanApproval(approved_at=datetime.now(timezone.utc),**_current_hashes(tmp_path))
    (tmp_path/'video-plan-approval.json').write_text(record.model_dump_json())
    (tmp_path/'final.mp4').write_bytes(b'previous approved video')
    stage=tmp_path/'.local-final-check';stage.mkdir();(stage/'final.mp4').write_bytes(b'jumping video')
    report=stage/'videoFiles/sequences/final/SEQ01-frame-report.json';report.parent.mkdir(parents=True)
    rows=[{'canonical_frame':i,'simulation_time':i/30,'continuity':state(10 if i>=4 else 0)} for i in range(8)]
    report.write_text(json.dumps({'state_samples':rows}))
    with pytest.raises(ValueError,match='continuity_position'):publish_staged_outputs(tmp_path,stage)
    assert (tmp_path/'final.mp4').read_bytes()==b'previous approved video'
    assert json.loads((tmp_path/'continuity-final-gate.json').read_text())['status']=='failed'


def test_nonfinite_light_path_cannot_pass_direction_check(tmp_path):
    from video_harness.creative_gates import check_render_continuity
    local,p=write_plan(tmp_path,'cut')
    p['direction_checks']=[{'sequence_id':'SEQ01','frame':7,'kind':'path_direction','reason':'굴절 경로는 아래로 향해야 한다.','expected':'down','path':'beam'}]
    (tmp_path/'continuity-plan.json').write_text(json.dumps(p))
    s=state();s['paths']['beam']=[[0,0,0],[1,float('nan'),0],[2,-2,0]]
    assert check_render_continuity(tmp_path,local,{'SEQ01':[{'canonical_frame':7,'continuity':s}]})
