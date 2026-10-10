"""Conservative classroom ledger and an explicitly idealized zonal energy budget.

R(phi)=1-3 sin(phi)^2, F(phi)=sin(phi) cos(phi)^2. Thus dF/dphi=R cos(phi):
positive net radiation grows poleward transport; a deficit reduces it. Units are
arbitrary, not an observational estimate of watts or an exact peak latitude.
"""
import math

GRAPH = 'energy-transport-blender-v1'
CONTROLLER = 'energy-transport'


def coin_ledger(surpluses):
    incoming, next_id, result = [], 0, []
    for surplus in surpluses:
        added = list(range(next_id, next_id + max(0, surplus)))
        next_id += len(added)
        available = incoming + added
        if -surplus > len(available):
            raise ValueError('deficit exceeds incoming coins')
        spent = available[:max(0, -surplus)]
        outgoing = available[len(spent):]
        result.append(dict(incoming=incoming[:], added=added, spent=spent, outgoing=outgoing))
        incoming = outgoing
    return result


def radiation_budget(latitude):
    return 1 - 3 * math.sin(math.radians(latitude)) ** 2


def radiation_fluxes(latitude):
    """Schematic absorbed solar / emitted thermal flux on one common scale.

    Both decline poleward; absorption declines faster. Their difference is
    0.4 * radiation_budget, preserving the transport maximum. Not observed W/m²
    or a claim that tropical cloud effects are a monotonic latitude function.
    """
    sin2 = math.sin(math.radians(latitude)) ** 2
    return 1.8 - 1.7 * sin2, 1.4 - .5 * sin2


def transport(latitude):
    phi = math.radians(latitude)
    return math.sin(phi) * math.cos(phi) ** 2

DESK_Y = [-2.0, -.8, .4, 1.6, 2.8]
DESK_TOP = .79
EARTH_CENTER = (0., 22., 3.)
PEAK_LATITUDE = math.degrees(math.asin(1 / math.sqrt(3)))


def smooth(x):
    x = min(1., max(0., x))
    return x*x*(3-2*x)


def mix(a,b,q):
    return tuple(x+(y-x)*q for x,y in zip(a,b))


def slot(desk,index,spent=False):
    if spent:
        return (.43, DESK_Y[desk] + .29, DESK_TOP + .02 + .025*index)
    return ((index%3-1)*.235, DESK_Y[desk] + (index//3-.5)*.24, DESK_TOP+.025)


def aisle_motion(progress):
    """Move out before passing the seated body, return only after clearing it."""
    outward=smooth(progress/.20)*(1-smooth((progress-.80)/.20))
    forward=smooth((progress-.20)/.60)
    return -.95*outward,forward,.25*outward


class Story:
    def __init__(self,timeline,fps,camera_transition_seconds=.4):
        self.fps=fps
        self.camera_transition_seconds=camera_transition_seconds
        self.camera_moves={}
        self.spans={}
        for beat in timeline:
            options=beat['controller_options']
            sid=options['scene_id']
            if 'camera_move_seconds' in options:
                self.camera_moves[sid]=(options['camera_move_seconds'],options.get('camera_lead_seconds',0.))
            a,z=self.spans.get(sid,(beat['start_frame'],beat['end_frame']))
            self.spans[sid]=(min(a,beat['start_frame']),max(z,beat['end_frame']))
        self.ledger=coin_ledger([3,2,1,-2])

    def progress(self,frame,scene,lo=0.,hi=1.):
        a,z=self.spans[scene]
        return smooth(((frame-a)/max(1,z-a-1)-lo)/(hi-lo))

    def state(self,frame):
        sid=next((s for s,(a,z) in self.spans.items() if a<=frame<z),16)
        t=frame/self.fps
        owners=[0,0,0,1,1,2,0,1,2]
        ownslots=[0,1,2,3,4,5,3,2,1]
        pos=[slot(d,i) for d,i in zip(owners,ownslots)]
        spent=[False]*9
        # Teacher allocation then each student's own expenditure. These three
        # spent coins remain in their bowls; the six surplus coins keep their IDs.
        q=self.progress(frame,5,.04,.38)
        for cid in range(9):
            origin=(-1.4+(cid%3)*.12,-2.8+(cid//3)*.12,1.0)
            pos[cid]=mix(origin,pos[cid],q)
        for cid in range(6,9):
            q=self.progress(frame,5,.55,.91)
            pos[cid]=mix(pos[cid],slot(owners[cid],0,True),q)
            spent[cid]=q>=1
        for s,desk,count in [(6,0,3),(7,1,5),(8,2,6)]:
            if frame<self.spans[s][0]:continue
            row=self.ledger[desk]
            merge=self.progress(frame,s,.10,.36)
            travel=self.progress(frame,s,.48,.92)
            for i,cid in enumerate(row['outgoing']):
                # Incoming coins arrived in the previous step's fixed slots.
                start=pos[cid]
                at=slot(desk,i)
                p=mix(start,at,merge)
                dx,forward,dz=aisle_motion(travel)
                p=mix(p,slot(desk+1,i),forward)
                pos[cid]=(p[0]+dx,p[1],p[2]+dz)
                if travel>=1:owners[cid]=desk+1
        if frame>=self.spans[10][0]:
            remove=self.progress(frame,10,.12,.42)
            for i,cid in enumerate(self.ledger[3]['spent']):
                pos[cid]=mix(pos[cid],slot(3,i,True),remove)
                spent[cid]=remove>=1
            q=self.progress(frame,10,.59,.94)
            for i,cid in enumerate(self.ledger[3]['outgoing']):
                dx,forward,dz=aisle_motion(q)
                # Keep the two spent positions empty: repacking while travelling
                # would make these four discs cross through each other.
                p=mix(pos[cid],slot(4,cid),forward)
                pos[cid]=(p[0]+dx,p[1],p[2]+dz)
                if q>=1:owners[cid]=4
        # Broad classroom views establish the setting; close views follow the
        # very same transfer. The Earth/classroom analogy uses two explicit cuts.
        def camera_pose(scene,at_frame):
            if scene in (4,5,11):return ((-6.2,-4.0,4.6),(0.,.3,.75),42.)
            if 6<=scene<=10:
                d={6:0,7:1,8:2,9:3,10:3}[scene]
                if scene in (6,7,8):q=self.progress(at_frame,scene,.48,.92)
                elif scene==10:q=self.progress(at_frame,scene,.59,.94)
                else:q=0
                x,forward,_=aisle_motion(q)
                y=DESK_Y[d]+1.2*forward
                return ((x-1.55,y-.8,2.15),(x,y,.83),43.)
            if scene in (3,14,15):return ((-.3,14.7,5.2),(0.,21.7,3.7),43.)
            return ((-.4,9.,4.2),(0.,22.,3.),43.)
        eye,look,lens=camera_pose(sid,frame)
        # Authored dolly moves can begin in the previous narration scene. The
        # target and common clock stay intact while the viewer approaches it.
        for destination in range(2,17):
            if destination in (4,12):continue  # Separate physical locations.
            duration,lead=self.camera_moves.get(destination,(self.camera_transition_seconds,0.))
            start=self.spans[destination][0]-lead*self.fps
            end=start+duration*self.fps
            if start<=frame<end and duration>0:
                q=smooth((frame-start)/(duration*self.fps))
                prev=camera_pose(destination-1,frame)
                target=camera_pose(destination,frame)
                eye=mix(prev[0],target[0],q);look=mix(prev[1],target[1],q)
                lens=prev[2]+(target[2]-prev[2])*q
                break
        return dict(scene_id=sid,time=t,coins=pos,coin_desks=owners,spent=spent,
                    classroom=4<=sid<=11,camera=(eye,look,lens),
                    transferred=[self.progress(frame,s,.48,.92) for s in (6,7,8)]+[self.progress(frame,10,.59,.94)],
                    budget_reveal=self.progress(frame,13,.08,.42),
                    peak_reveal=max(1. if sid<=3 else 0.,self.progress(frame,15,.12,.6)))


def validate_job(job):
    if job.get('scene_graph')!=GRAPH:raise ValueError('unsupported energy transport graph')
    if min(job['duration_frames'],job['canonical_fps'],job['frame_count'])<=0:raise ValueError('invalid duration')
    cursor=0
    for beat in job['timeline']:
        if beat['controller']!=CONTROLLER or beat['start_frame']!=cursor or beat['end_frame']<=cursor:
            raise ValueError('energy transport beats must be contiguous')
        cursor=beat['end_frame']
    if cursor!=job['duration_frames']:raise ValueError('timeline duration mismatch')
    story=Story(job['timeline'],job['canonical_fps'])
    if list(story.spans)!=list(range(1,17)):raise ValueError('energy transport requires scenes 1 through 16')
    cache=job['canonical_state_cache']
    if len(cache)!=cursor:raise ValueError('canonical cache length mismatch')
    previous=-math.inf
    for frame,entry in enumerate(cache):
        if entry['canonical_frame']!=frame or entry['simulation_time']<previous:raise ValueError('invalid canonical time')
        previous=entry['simulation_time']
