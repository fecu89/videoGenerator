"""Fail-closed narrative and rendered 3D continuity gates.

A semantic review is a required, content-bound editorial judgment. Python checks
its evidence and coverage; it does not pretend substring matching understands
causality. Render continuity is checked separately using evaluated transforms.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Literal
from pydantic import Field
from .models import StrictModel
from .storage import atomic_write


class Quote(StrictModel):
    scene_id: int = Field(ge=1)
    quote: str = Field(min_length=2)


class ChainPair(StrictModel):
    question: Quote
    answer: Quote
    resolves_question: bool
    answer_reason: str = Field(min_length=12)
    causes_next_question: bool | None
    next_question_reason: str | None


class SceneCoverage(StrictModel):
    scene_id: int = Field(ge=1)
    role: Literal['intro','chain','mechanism','closing']
    reason: str = Field(min_length=8)


class StoryChain(StrictModel):
    schema_version: Literal[1]
    script_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewer: str = Field(min_length=3)
    verdict: Literal['passed','failed','pending']
    scene_coverage: list[SceneCoverage]
    pairs: list[ChainPair] = Field(min_length=2)


class ActorMapping(StrictModel):
    source: str = Field(alias='from',min_length=1)
    target: str = Field(alias='to',min_length=1)


class Transition(StrictModel):
    from_beat: str
    to_beat: str
    mode: Literal['continuous_3d','match_cut','cut']
    reason: str = Field(min_length=15)
    reviewed: bool
    actors: list[ActorMapping] = Field(default_factory=list)


class DirectionCheck(StrictModel):
    sequence_id: str
    frame: int = Field(ge=0)
    kind: Literal['screen_direction','path_direction','screen_rotation']
    reason: str = Field(min_length=10)
    vector: tuple[float,float,float] | None = None
    start_frame: int | None = Field(default=None,ge=0)
    actor: str | None = None
    expected: Literal['left','right','up','down','counterclockwise','clockwise']
    path: str | None = None


class ContinuityPlan(StrictModel):
    schema_version: Literal[1]
    local_sequence_plan_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewer: str = Field(min_length=3)
    verdict: Literal['passed','failed','pending']
    transitions: list[Transition]
    direction_checks: list[DirectionCheck] = Field(default_factory=list)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def story_digest(script):
    # TTS measures duration and writes paths without changing editorial content.
    source=json.loads(json.dumps(script))
    source.pop('response_id',None)
    for scene in source['scenes']:
        for key in ('duration_seconds','audio_file','video_prompt_file'):scene.pop(key,None)
    return hashlib.sha256(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def stage_creative_reviews(source, destination):
    """Preserve content-bound review inputs when compiling in an artifact stage.

    run-settings.json feeds the pacing and text-policy sections of video-plan.md;
    without it the staged review falls back to the project settings and differs
    from the approved review whenever the project defaults have since changed.
    """
    import shutil
    for name in ('story-chain.json', 'continuity-plan.json', 'run-settings.json'):
        path = Path(source) / name
        if path.is_file():
            shutil.copy2(path, Path(destination) / name)


def check_story_chain(script, review):
    errors=[]
    try:r=StoryChain.model_validate(review)
    except ValueError as e:return [f'story_chain_invalid: {e}']
    if r.script_sha256!=story_digest(script):errors.append('story_chain_stale: narration or editorial content changed')
    if r.verdict!='passed':errors.append('story_chain_failed: semantic review is not passed')
    scenes={s['scene_id']:s['narration'] for s in script['scenes']}
    if [c.scene_id for c in r.scene_coverage]!=list(scenes):errors.append('story_chain_coverage: every scene must be reviewed in order')
    anchors=[]
    def anchor(q):
        text=scenes.get(q.scene_id,'');offset=text.find(q.quote)
        if offset<0:errors.append(f'story_chain_quote: scene {q.scene_id} does not contain {q.quote!r}')
        return q.scene_id,offset
    for i,pair in enumerate(r.pairs):
        q,a=anchor(pair.question),anchor(pair.answer);anchors.append((q,a))
        if q>=a or (q[0]==a[0] and q[1]+len(pair.question.quote)>a[1]):errors.append(f'story_chain_order: pair {i+1} answer must follow its question')
        if not pair.resolves_question:errors.append(f'story_chain_answer: pair {i+1} does not resolve its question')
        if i<len(r.pairs)-1:
            if pair.causes_next_question is not True or len((pair.next_question_reason or '').strip())<15:
                errors.append(f'story_chain_causality: pair {i+1} needs a reviewed answer-to-next-question reason')
        elif pair.causes_next_question is not None or pair.next_question_reason is not None:
            errors.append('story_chain_open_end: last answer must close the chain')
    for i,(_,answer) in enumerate(anchors[:-1]):
        following=anchors[i+1][0]
        if answer>=following:errors.append(f'story_chain_order: pair {i+2} question precedes previous answer')
    ids=list(scenes)
    referenced={q.scene_id for p in r.pairs for q in (p.question,p.answer)}
    for c in r.scene_coverage:
        if c.role=='intro' and c.scene_id!=ids[0]:errors.append('story_chain_intro: only the first scene can be an intro')
        if c.role=='closing' and c.scene_id!=ids[-1]:errors.append('story_chain_closing: only the last scene can be closing')
        if c.role=='chain' and c.scene_id not in referenced:errors.append(f'story_chain_unlinked: scene {c.scene_id}')
        if c.role=='mechanism' and not any(p.question.scene_id<=c.scene_id<=p.answer.scene_id for p in r.pairs):
            errors.append(f'story_chain_unlinked_mechanism: scene {c.scene_id}')
    for scene_id,text in scenes.items():
        for match in re.finditer(r'[^.!?。？！]*[?？]',text):
            start=match.start()+len(match.group())-len(match.group().lstrip())
            if not any(p.question.scene_id==scene_id and text.find(p.question.quote)<=start and text.find(p.question.quote)+len(p.question.quote)>=match.end() for p in r.pairs):
                errors.append(f'story_chain_unreviewed_question: scene {scene_id}: {match.group().strip()}')
    return errors


def _named_gate(run, filename, errors, **evidence):
    atomic_write(Path(run)/filename,json.dumps({'schema_version':1,'status':'failed' if errors else 'passed','issues':errors,**evidence},ensure_ascii=False,indent=2)+'\n')
    if errors:raise ValueError('\n'.join(errors)+'\nRepair the failed review/plan and rerun the gate. --force cannot bypass it.')


def _gate(run, name, errors, **evidence):
    _named_gate(run,f'{name}-gate.json',errors,**evidence)


def require_story_chain(run):
    run=Path(run)
    try:errors=check_story_chain(read_json(run/'script.json'),read_json(run/'story-chain.json'))
    except (OSError,ValueError,KeyError,TypeError) as e:errors=[f'story_chain_missing_or_invalid: {e}']
    _gate(run,'story',errors)


def beat_order(local):
    return [(s['sequence_id'],b) for s in local['sequences'] for b in sorted(s['timeline'],key=lambda b:(b['start_frame'],b.get('priority',0)))]


def check_continuity_plan(local,review,local_hash):
    try:p=ContinuityPlan.model_validate(review)
    except ValueError as e:return [f'continuity_plan_invalid: {e}']
    errors=[]
    if p.local_sequence_plan_sha256!=local_hash:errors.append('continuity_plan_stale: local plan changed')
    if p.verdict!='passed':errors.append('continuity_plan_failed: editorial transition review not passed')
    beats=beat_order(local);expected=[(a[1]['beat_id'],b[1]['beat_id']) for a,b in zip(beats,beats[1:])]
    if [(t.from_beat,t.to_beat) for t in p.transitions]!=expected:errors.append('continuity_plan_coverage: every adjacent beat boundary must be declared once in order')
    for t in p.transitions:
        if not t.reviewed:errors.append(f'continuity_transition_unreviewed: {t.from_beat}->{t.to_beat}')
        if t.mode!='cut' and not t.actors:errors.append(f'continuity_actors_missing: {t.from_beat}->{t.to_beat}')
    seq={s['sequence_id']:s for s in local['sequences']}
    for c in p.direction_checks:
        if c.sequence_id not in seq or c.frame>=seq.get(c.sequence_id,{}).get('duration_frames',0):errors.append('continuity_direction_frame: invalid sequence/frame')
        if c.kind in ('screen_direction','screen_rotation') and (c.vector is None or sum(v*v for v in c.vector)<1e-12):errors.append('continuity_direction_vector: nonzero world vector required')
        if c.kind=='screen_rotation' and (c.start_frame is None or c.start_frame>=c.frame or c.expected not in ('counterclockwise','clockwise')):errors.append('continuity_rotation_range: valid start/end and rotation direction required')
        if c.kind!='screen_rotation' and c.expected not in ('left','right','up','down'):errors.append('continuity_direction_axis: expected screen/path direction invalid')
        if c.kind=='path_direction' and not c.path:errors.append('continuity_direction_path: rendered geometry path required')
    return errors


def require_creative_plan(run):
    run=Path(run);require_story_chain(run)
    try:errors=check_continuity_plan(read_json(run/'local-sequence-plan.json'),read_json(run/'continuity-plan.json'),digest(run/'local-sequence-plan.json'))
    except (OSError,ValueError,KeyError,TypeError) as e:errors=[f'continuity_plan_missing_or_invalid: {e}']
    _gate(run,'continuity-plan',errors)


def text_policy_of(run):
    path=Path(run)/'run-settings.json'
    if not path.is_file():return 'legacy'
    try:return read_json(path).get('local_video',{}).get('text_policy','legacy')
    except (OSError,ValueError):return 'legacy'


def _skip_gate(run,name,reason):
    atomic_write(Path(run)/f'{name}-gate.json',json.dumps({'schema_version':1,'status':'skipped','issues':[],'reason':reason},ensure_ascii=False,indent=2)+'\n')


def require_text_plan(run):
    """Keyword-label contract on the local plan; fail-closed for keywords runs."""
    run=Path(run)
    policy=text_policy_of(run)
    if policy=='legacy':return _skip_gate(run,'text-plan','text_policy is legacy')
    from .text_labels import plan_text_issues
    try:
        local=read_json(run/'local-sequence-plan.json');errors=plan_text_issues(local,policy=policy)
        declared=any(b.get('controller_options',{}).get('labels') for s in local['sequences'] for b in s['timeline'])
        excluded=read_json(run/'production-plan.json').get('style_bible',{}).get('excluded_elements',[])
        # Keyword labels replace subtitles; subtitle runs keep them beside formula labels.
        if policy=='keywords' and declared and 'subtitles' not in excluded:errors.append('style_bible_subtitles_allowed: excluded_elements must list subtitles when labels are declared')
    except (OSError,ValueError,KeyError,TypeError) as e:errors=[f'text_plan_missing_or_invalid: {e}']
    _gate(run,'text-plan',errors)


def require_translations(run):
    """Translations must exist for every scene/language before any localized voice runs."""
    run=Path(run)
    from .settings import resolve_run_settings, subtitle_language_list
    policy=text_policy_of(run)
    try:languages=subtitle_language_list(resolve_run_settings(run)) if (run/'run-settings.json').is_file() else []
    except (OSError,ValueError) as e:return _gate(run,'translation',[f'translations_settings_unreadable: {e}'])
    if policy!='subtitles' or not languages:return _skip_gate(run,'translation','no subtitle languages for this policy')
    from .translations import load_translations, translation_issues, TRANSLATIONS_FILENAME
    from .language_voices import load_language_voices
    from .models import ScriptArtifact
    try:
        if not (run/TRANSLATIONS_FILENAME).is_file():errors=[f'translations_missing: run translate-scaffold and fill {TRANSLATIONS_FILENAME}']
        else:
            script=ScriptArtifact.model_validate_json((run/'script.json').read_text(encoding='utf-8'))
            errors=translation_issues(load_translations(run),script,digest(run/'script.json'),load_language_voices(run),languages)
    except (OSError,ValueError,KeyError,TypeError) as e:errors=[f'translations_invalid: {e}']
    _gate(run,'translation',errors)


def require_text_render(run, artifact_root, quality):
    run=Path(run);root=Path(artifact_root)
    policy=text_policy_of(run)
    if policy=='legacy':return _skip_gate(run,'text-'+quality,'text_policy is legacy')
    from .text_labels import render_text_issues
    try:
        local=read_json(run/'local-sequence-plan.json');samples={};width=height=None
        if quality=='preview':
            report=read_json(run/'preview-report.json');width,height=report['width'],report['height']
            samples={s['sequence_id']:s['state_samples'] for s in report['sequences']}
        else:
            for seq in local['sequences']:
                report=read_json(root/'videoFiles/sequences'/quality/(seq['sequence_id']+'-frame-report.json'))
                width,height=report['width'],report['height'];samples[seq['sequence_id']]=report['state_samples']
        errors=render_text_issues(local,samples,width=width,height=height,policy=policy)
    except (OSError,ValueError,KeyError,TypeError) as e:errors=[f'text_render_missing: {e}']
    _gate(run,'text-'+quality,errors,artifact_root=str(root))


def norm(v):return math.sqrt(sum(x*x for x in v))
def minus(a,b):return [x-y for x,y in zip(a,b)]
def qangle(a,b):
    n=norm(a)*norm(b)
    if not n:raise ValueError('zero quaternion')
    return math.degrees(2*math.acos(min(1,abs(sum(x*y for x,y in zip(a,b))/n))))


def rotate_inverse(q,v):
    w,x,y,z=q;n=norm(q);w,x,y,z=[a/n for a in (w,-x,-y,-z)]
    cross=[y*v[2]-z*v[1],z*v[0]-x*v[2],x*v[1]-y*v[0]]
    second=[y*cross[2]-z*cross[1],z*cross[0]-x*cross[2],x*cross[1]-y*cross[0]]
    return [v[i]+2*w*cross[i]+2*second[i] for i in range(3)]


def projected(state,name):
    cam=state['camera'];actor=state['actors'][name]
    local=rotate_inverse(cam['rotation'],minus(actor['position'],cam['position']))
    width=cam['ortho_scale'] if cam['projection']=='ORTHO' else -local[2]*cam.get('sensor_width',36)/cam['lens']
    if width<=0:raise ValueError('actor behind camera')
    return [local[0]/width,local[1]/width,actor['radius']/width]


def continuity_state_issues(boundary,before,after):
    if boundary['mode']=='cut':return []
    try:
        if len(before)<2 or not after:raise ValueError('two preceding and one following actual samples required')
        x,y,z=[row['continuity'] for row in (before[-2],before[-1],after[0])]
        if not all((x,y,z)):raise ValueError('evaluated 3D capture missing')
        # JSON floats from external renderer reports must not bypass comparisons.
        def finite(value):
            if isinstance(value,float) and not math.isfinite(value):raise ValueError('nonfinite actual state')
            if isinstance(value,dict):
                for v in value.values():finite(v)
            if isinstance(value,list):
                for v in value:finite(v)
        for row in before[-3:] + after[:1]:finite(row['continuity'])
        dt0=before[-1]['simulation_time']-before[-2]['simulation_time']
        dt1=after[0]['simulation_time']-before[-1]['simulation_time']
        if dt0<=0 or dt1<=0 or dt1>dt0*1.51:raise ValueError('simulation time discontinuity')
        errors=[]
        if boundary['mode']=='match_cut':
            for m in boundary['actors']:
                a,b=projected(y,m['from']),projected(z,m['to'])
                if norm(minus(a[:2],b[:2]))>.025 or abs(a[2]-b[2])>max(a[2],b[2])*.06:
                    errors.append('continuity_match_cut: projected actor position/size jumps')
            return errors
        def predict(get):
            rows=before[-3:];times=[s['simulation_time'] for s in rows];target=after[0]['simulation_time']
            if len(set(times))!=len(times):raise ValueError('duplicate sample time')
            values=[get(s['continuity']) for s in rows]
            return sum(value*math.prod((target-times[j])/(times[i]-times[j]) for j in range(len(times)) if j!=i) for i,value in enumerate(values))
        camera_extent=max(y['camera']['ortho_scale'] if y['camera']['projection']=='ORTHO' else norm(y['camera']['position']),1)
        pairs=[('camera',x['camera'],y['camera'],z['camera'],camera_extent,.025,3)]
        for m in boundary['actors']:
            a,b,c=x['actors'][m['from']],y['actors'][m['from']],z['actors'][m['to']]
            pairs.append((m['from'],a,b,c,max(b['radius'],1e-6),.08,5))
        for name,a,b,c,size,tolerance,rotation_tolerance in pairs:
            getpose=(lambda s:s['camera']) if name=='camera' else (lambda s:s['actors'][name])
            predicted=[predict(lambda s:getpose(s)['position'][i]) for i in range(3)]
            if norm(minus(c['position'],predicted))/size>tolerance:errors.append(f'continuity_position: {name} jumps at boundary')
            previous=qangle(a['rotation'],b['rotation']);following=qangle(b['rotation'],c['rotation'])
            if following>previous*dt1/dt0+rotation_tolerance:errors.append(f'continuity_rotation: {name} orientation/roll jumps')
            for i in range(3):
                expected=b['scale'][i]+(b['scale'][i]-a['scale'][i])*dt1/dt0
                if abs(c['scale'][i]-expected)>max(abs(b['scale'][i]),1e-6)*.05:errors.append(f'continuity_scale: {name} scale jumps')
        a,b=y['camera'],z['camera']
        if a['projection']!=b['projection']:errors.append('continuity_projection: camera projection switches')
        for key in (('ortho_scale',) if a['projection']=='ORTHO' else ('lens',)):
            predicted=a[key]+(a[key]-x['camera'][key])*dt1/dt0
            if abs(b[key]-predicted)>max(abs(a[key]),1e-6)*.05:errors.append(f'continuity_camera: {key} jumps')
        return errors
    except (KeyError,ValueError,TypeError,IndexError,ZeroDivisionError) as e:return [f'continuity_capture_missing_or_invalid: {e}']


def check_render_continuity(run, local, samples_by_sequence):
    plan=read_json(Path(run)/'continuity-plan.json');errors=check_continuity_plan(local,plan,digest(Path(run)/'local-sequence-plan.json'))
    if errors:return errors
    beats={b['beat_id']:(seq,b) for seq,b in beat_order(local)}
    for transition in plan['transitions']:
        if transition['mode']=='cut':continue
        left,a=beats[transition['from_beat']];right,b=beats[transition['to_beat']]
        before=[s for s in samples_by_sequence.get(left,[]) if a['start_frame']<=s['canonical_frame']<a['end_frame']]
        after=[s for s in samples_by_sequence.get(right,[]) if b['start_frame']<=s['canonical_frame']<b['end_frame']]
        errors.extend(f"{transition['from_beat']}->{transition['to_beat']}: {e}" for e in continuity_state_issues(transition,before,after))
    for check in plan.get('direction_checks',[]):
        try:
            rows=samples_by_sequence[check['sequence_id']];row=min(rows,key=lambda r:abs(r['canonical_frame']-check['frame']))
            if abs(row['canonical_frame']-check['frame'])>3:raise ValueError('direction sample missing')
            state=row['continuity']
            def screen_vector(state):
                vector=check['vector']
                if check.get('actor'):
                    q=state['actors'][check['actor']]['rotation'];vector=rotate_inverse([q[0],-q[1],-q[2],-q[3]],vector)
                result=rotate_inverse(state['camera']['rotation'],vector)
                if not all(math.isfinite(v) for v in result):raise ValueError('nonfinite screen vector')
                return result
            if check['kind']=='screen_rotation':
                selected=[s for s in rows if check['start_frame']<=s['canonical_frame']<=check['frame']]
                vectors=[screen_vector(s['continuity']) for s in selected]
                sign=1 if check['expected']=='counterclockwise' else -1
                angles=[math.atan2(a[0]*b[1]-a[1]*b[0],a[0]*b[0]+a[1]*b[1])*sign for a,b in zip(vectors,vectors[1:])]
                if len(angles)<2 or sum(angles)<math.radians(60) or min(angles)<-.005:errors.append(f"continuity_screen_rotation: {check['reason']}")
            elif check['kind']=='screen_direction':
                v=screen_vector(state);length=math.hypot(v[0],v[1])
                component=v[0] if check['expected'] in ('left','right') else v[1]
                sign=-1 if check['expected'] in ('left','down') else 1
                if length<1e-8 or component*sign/length<.95:errors.append(f"continuity_direction: {check['reason']}")
            else:
                points=state['paths'][check['path']];axis=0 if check['expected'] in ('left','right') else 1;sign=-1 if check['expected'] in ('left','down') else 1
                if any(len(point)!=3 or not all(math.isfinite(v) for v in point) for point in points):raise ValueError('nonfinite or malformed geometry path')
                if len(points)<3 or (points[-1][axis]-points[0][axis])*sign<=.01 or any((b[axis]-a[axis])*sign<-.001 for a,b in zip(points,points[1:])):
                    errors.append(f"continuity_refraction_direction: {check['reason']}")
        except (KeyError,ValueError,TypeError,IndexError,ZeroDivisionError) as e:errors.append(f'continuity_direction_capture: {e}')
    return errors


def require_rendered_continuity(run, artifact_root, quality='final'):
    run=Path(run);root=Path(artifact_root)
    require_creative_plan(run)
    try:
        local=read_json(run/'local-sequence-plan.json')
        samples={seq['sequence_id']:read_json(root/'videoFiles/sequences'/quality/(seq['sequence_id']+'-frame-report.json'))['state_samples'] for seq in local['sequences']}
        errors=check_render_continuity(run,local,samples)
    except (OSError,ValueError,KeyError,TypeError) as e:errors=[f'continuity_render_missing: {e}']
    _gate(run,'continuity-'+quality,errors,artifact_root=str(root))


def main(argv=None):
    p=argparse.ArgumentParser(description='Required causal-story and 3D continuity gates; failure never grants approval.')
    p.add_argument('action',choices=['story','plan','render']);p.add_argument('run_directory',type=Path);p.add_argument('--artifact-root',type=Path);p.add_argument('--quality',choices=['draft','final'],default='final')
    args=p.parse_args(argv);run=args.run_directory.resolve()
    try:
        if args.action=='story':require_story_chain(run)
        else:
            require_creative_plan(run)
            if args.action=='render':
                root=args.artifact_root or run;local=read_json(run/'local-sequence-plan.json');samples={}
                for seq in local['sequences']:
                    path=root/'videoFiles/sequences'/args.quality/(seq['sequence_id']+'-frame-report.json')
                    samples[seq['sequence_id']]=read_json(path)['state_samples']
                _gate(run,'continuity-'+args.quality,check_render_continuity(run,local,samples),artifact_root=str(root))
    except (OSError,ValueError,KeyError) as e:
        print(str(e));return 1
    print('Required creative gate passed');return 0


def require_legacy_render_gate(run, quality):
    require_story_chain(run)
    if quality=='final':
        raise ValueError('Final publication requires produce with story and 3D continuity gates. Migrate legacy plans before production.')


def render_continuity_review(run):
    path=Path(run)/'continuity-plan.json'
    if not path.is_file():return ''
    plan=read_json(path)
    if not plan.get('transitions'):return ''
    lines=['','## 필수 3D 전환 검토','','| 경계 | 전환 | 이유 |','|---|---|---|']
    for t in plan['transitions']:
        lines.append(f"| {t['from_beat']} → {t['to_beat']} | {t['mode']} | {t['reason'].replace('|','/')} |")
    lines+=['','### 실제 렌더 방향 검사','']
    lines.extend(f"- {c['sequence_id']} / 프레임 {c['frame']}: {c['reason']}" for c in plan.get('direction_checks',[]))
    return '\n'.join(lines)+'\n'


def render_report_continuity_issues(run,local,report,sources=None):
    try:
        samples={}
        for result in report.sequences:
            root=sources[result.sequence_id].root if sources is not None else report.artifact_root
            path=Path(root)/result.state_report_file
            if not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('state report escapes artifact root')
            samples[result.sequence_id]=read_json(path)['state_samples']
        return check_render_continuity(run,local.model_dump(mode='json'),samples)
    except (OSError,ValueError,KeyError,TypeError) as e:return [f'continuity_render_missing: {e}']


def validate_creative_run(run,output_mode):
    run=Path(run)
    try:
        require_story_chain(run)
        if (run/'local-sequence-plan.json').is_file():
            require_creative_plan(run)
            from .video_plan_approval import require_current_video_plan_approval
            require_current_video_plan_approval(run)
            if output_mode!='prompts_only' and (run/'final.mp4').is_file():
                require_rendered_continuity(run,run)
        elif (run/'final.mp4').is_file():
            return ['Final publication requires a reviewed sequence continuity plan; migrate legacy plans first.']
    except (OSError,ValueError,KeyError,TypeError) as e:return [str(e)]
    return []
