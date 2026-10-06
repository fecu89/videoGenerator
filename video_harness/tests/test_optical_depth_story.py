import pytest
from video_harness.blender_renderer.optical_depth_story_math import state_at,transmission
from video_harness.text_labels import plan_text_issues,render_text_issues


def test_compressing_path_at_fixed_tau_preserves_fraction_doubles_extinction():
    job=dict(canonical_fps=30,timeline=[dict(start_frame=0,end_frame=100,controller_options={'state':{'distance':16,'tau':1}}),dict(start_frame=100,end_frame=200,controller_options={'state':{'distance':8,'tau':1}})])
    a,b=state_at(job,99),state_at(job,199)
    assert b['transmission']==a['transmission']==pytest.approx(.367879441)
    assert b['extinction_per_length']==2*a['extinction_per_length']
    assert state_at(job,100)==a
    assert state_at(job,170)==state_at(job,170)


def test_camera_travel_stays_continuous_and_reaches_observer():
    j=dict(canonical_fps=30,timeline=[dict(start_frame=0,end_frame=90,controller_options=dict(state={'camera':[7.2,-1.2,1.9],'target':[13,0,1.7]},camera_move_seconds=1.5))])
    assert state_at(j,0)['camera']==[10,-18,7]
    assert state_at(j,45)['camera']==pytest.approx([7.2,-1.2,1.9])
    assert state_at(j,22)['camera'][1] < -1.2
    assert transmission(5)<.01


def graph_plan():
    return dict(renderer='blender',sequences=[dict(sequence_id='SEQ01',timeline=[dict(beat_id='B01',start_frame=0,end_frame=100,controller_options={'scientific_graph':dict(x_label='광학적 깊이',y_label='광량',ticks=['0','1'])})])])


def graph_sample():
    return dict(canonical_frame=50,continuity={'actors':{'GraphText:'+x:{'kind':'FONT','visible':True} for x in ['광학적 깊이','광량','0','1']}},graph_text=[dict(text=x,rect=[.1+i*.2,.2,.22+i*.2,.25]) for i,x in enumerate(['광학적 깊이','광량','0','1'])])


def test_explicit_graph_axes_pass_without_allowing_other_screen_text():
    p=graph_plan();row=graph_sample();assert plan_text_issues(p,policy='subtitles')==[]
    assert render_text_issues(p,{'SEQ01':[row]},width=384,height=216,policy='subtitles')==[]
    row['continuity']['actors']['Unapproved title']={'kind':'FONT','visible':True}
    assert any('on_screen_text_found' in e for e in render_text_issues(p,{'SEQ01':[row]},width=384,height=216,policy='subtitles'))


def test_graph_missing_clipped_and_caption_as_tick_fail():
    p=graph_plan();row=graph_sample();row['graph_text'][0]['rect']=[.1,.2,1.01,.3]
    issues=render_text_issues(p,{'SEQ01':[row]},width=384,height=216,policy='subtitles')
    assert any('graph_text_clipped' in e for e in issues)
    row['graph_text']=[]
    assert any('graph_text_missing' in e for e in render_text_issues(p,{'SEQ01':[row]},width=384,height=216,policy='subtitles'))
    p['sequences'][0]['timeline'][0]['controller_options']['scientific_graph']['ticks']=['An extra caption']
    assert any('graph_text_invalid' in e for e in plan_text_issues(p,policy='subtitles'))
