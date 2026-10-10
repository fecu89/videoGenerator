"""Seekable choreography and dipole geometry, not an MHD geodynamo solver.

+Z is geographic north. The ideal moment points -Z, so exterior lines enter
near geographic north. Flow loops are illustrative streamlines within the
liquid shell. Particle speed and current paths are qualitative encodings.
"""
import math

GRAPH='geomagnetic-dynamo-blender-v1'
CONTROLLER='geomagnetic-dynamo'
FLOW_PERIOD=9.


def smooth(q):
    q=max(0.,min(1.,q))
    return q*q*(3-2*q)


def mix(a,b,q):
    return tuple(x+(y-x)*q for x,y in zip(a,b))


def dipole_field(p):
    r2=sum(x*x for x in p)
    if r2<=0:raise ValueError('dipole singularity at origin')
    r=math.sqrt(r2);dot=-p[2]
    return tuple((3*x*dot/r2+(1 if i==2 else 0))/r**3 for i,x in enumerate(p))


def field_path(l_shell,azimuth,surface_radius=3.05,count=96):
    if l_shell<=surface_radius or count<3:raise ValueError('field path must remain outside the surface')
    a=math.asin(math.sqrt(surface_radius/l_shell))
    result=[]
    for i in range(count+1):
        theta=math.pi-a-(math.pi-2*a)*i/count
        r=l_shell*math.sin(theta)**2
        result.append((r*math.sin(theta)*math.cos(azimuth),r*math.sin(theta)*math.sin(azimuth),r*math.cos(theta)))
    return result


def bar_field_path(l_shell,azimuth,surface_radius=1.25,count=72):
    # The supplied bar is oriented with its red north pole at +Z. Exterior
    # arrows therefore leave +Z and enter -Z, opposite Earth's geographic
    # north-facing inward field. Shape comparison must not reverse pole physics.
    return list(reversed(field_path(l_shell,azimuth,surface_radius,count)))


def magnetosphere_path(points,amount):
    # Qualitative solar-wind deformation. Sun is at -X; the day side is
    # compressed, the night side stretches +X. Surface anchors stay fixed.
    # This is a conceptual field shape, not a magnetopause/MHD calculation.
    q=max(0.,min(1.,amount));result=[]
    for x,y,z in points:
        r=math.sqrt(x*x+y*y+z*z)
        strength=smooth((r-3.05)/3.15)
        scale=1+q*strength*(1.65 if x>=0 else -.36)
        result.append((x*scale,y,z))
    return result


def solar_wind_point(q,lane):
    x=-7.8+25.8*q
    sign=-1 if lane<3 else 1
    z=sign*(.65+.65*(lane%3)+3.2*math.exp(-((x+.7)/3.0)**2))
    return x,-1.6,z


def flow_point(lane,t,offset=0.):
    # Qualitative rotation-constrained convection: circulate around a local
    # column parallel to +Z, with axial motion as well as horizontal motion.
    # This is not an observed core velocity field or a differential-rotation
    # dynamo calculation. Keep the complete closed path inside the source shell.
    phi=-math.pi+.20+lane*(math.pi-.40)/7
    a=math.tau*(t/FLOW_PERIOD+offset)
    return (1.32*math.cos(phi)+.13*math.cos(2*a+lane*.4),
            1.32*math.sin(phi)+.13*math.sin(2*a+lane*.4),.60*math.sin(a))


def parcel_state(q):
    a=math.tau*(q%1)
    p=(1.04-.25*math.cos(a),-.68,.25*math.sin(a))
    return p,(1+math.cos(a))/2


def wire_field_point(q,z=0.):
    a=math.tau*q
    return .72*math.cos(a),.72*math.sin(a),z


class Story:
    def __init__(self,timeline,fps,transition_seconds=.4):
        self.fps=fps;self.spans={}
        for beat in timeline:
            sid=beat['controller_options']['scene_id']
            a,z=self.spans.get(sid,(beat['start_frame'],beat['end_frame']))
            self.spans[sid]=(min(a,beat['start_frame']),max(z,beat['end_frame']))
        # Timing is authored in narration space; motion may straddle its markers.
        self.camera_keys=[(0,(0.,-.5,.0),12.8),
            (self.at(3,.75),(0.,-.5,.0),12.8),
            (self.at(4,.45),(0.,0.,0.),14.),
            (self.at(5,.85),(0.,0.,0.),8.),
            (self.at(7,.9),(0.,0.,0.),8.),
            (self.at(8,.18),(0.,0.,0.),18.),
            (self.at(8,.9),(0.,0.,0.),18.),
            (self.at(9,.45),(0.,-.3,0.),5.8),
            (self.at(10,.12),(1.04,-.68,0.),2.6),
            (self.at(10,.9),(1.04,-.68,0.),2.6),
            (self.at(11,.60),(0.,-.3,0.),6.8),
            (self.at(12,.35),(0.,0.,0.),12.),
            (self.at(12,.95),(0.,0.,0.),12.),
            (self.at(13,.30),(1.7,0.,0.),21.),
            (self.at(14,.90),(1.7,0.,0.),21.),
            (self.at(15,.65),(0.,-.3,0.),6.8),
            (self.at(16,.85),(0.,0.,0.),14.),
            (self.at(17,.15),(1.7,0.,0.),21.),
            (self.at(17,.95),(1.7,0.,0.),21.),
            (self.at(18,.35),(0.,-.3,0.),6.8),
            (self.at(18,.60),(0.,-.3,0.),6.8),
            (self.at(18,.90),(0.,0.,0.),14.),
            (self.at(19,.35),(0.,-.3,0.),6.8),
            (self.at(20,.02),(0.,-.3,0.),6.8),
            (self.at(20,.22),(-3.,0.,0.),34.),
            (self.at(21,.00),(-3.,0.,0.),34.),
            (self.at(21,.35),(0.,-.3,0.),6.8),
            (self.at(21,.90),(0.,-.3,0.),6.8),
            (self.at(22,.20),(0.,0.,0.),18.),
            (self.at(22,.90),(0.,0.,0.),18.),
            (self.at(23,.35),(1.,0.,0.),36.),
            (self.at(23,.95),(1.,0.,0.),36.),
            (self.at(24,.55),(0.,-.5,0.),14.),
            (self.at(24,.95),(0.,-.5,0.),14.),
            (self.at(25,.48),(-3.,0.,0.),34.),
            (self.at(25,1),(-3.,0.,0.),34.)]

    def at(self,sid,q):
        a,z=self.spans[sid]
        return a+(z-a-1)*q

    def ramp(self,frame,sid,lo=.08,hi=.75):
        return smooth((frame-self.at(sid,lo))/max(1.,self.at(sid,hi)-self.at(sid,lo)))

    def window(self,frame,start,end):
        return self.ramp(frame,start,.02,.25)*(1-self.ramp(frame,end,.72,.98))

    def camera(self,frame):
        target=self.camera_keys[-1][1];scale=self.camera_keys[-1][2]
        for left,right in zip(self.camera_keys,self.camera_keys[1:]):
            if frame<=right[0]:
                q=smooth((frame-left[0])/max(1.,right[0]-left[0]))
                target=mix(left[1],right[1],q);scale=left[2]+(right[2]-left[2])*q
                break
        # Looking nearly straight into the opened southern-facing hemisphere.
        eye=tuple(target[i]+(0,-20,4.2)[i] for i in range(3))
        return eye,target,scale

    def state(self,frame):
        sid=next((s for s,(a,z) in self.spans.items() if a<=frame<z),25)
        t=frame/self.fps
        globe20=self.ramp(frame,20,.0,.25)*(1-self.ramp(frame,21,.02,.50))
        cut=self.ramp(frame,5,.05,.95)*(1-globe20)*(1-self.ramp(frame,22,.02,.25))
        current=self.ramp(frame,15,.25,.90)
        compare=max(self.window(frame,8,8),self.window(frame,22,22))
        single=self.ramp(frame,10,.02,.08)*(1-self.ramp(frame,10,.92,.98))
        compass=((1-self.ramp(frame,5,.0,.25))+self.ramp(frame,24,.02,.50))*(1-self.ramp(frame,25,.02,.55))
        field=max(.45*self.window(frame,2,3),self.window(frame,4,4),compare,self.ramp(frame,16,.06,.84))*(1-self.ramp(frame,25,.02,.55))
        process=self.window(frame,18,18)
        current=current*(1-process)+process*self.ramp(frame,18,.15,.58)
        field=field*(1-process)+process*self.ramp(frame,18,.58,.92)
        return dict(scene_id=sid,time=t,camera=self.camera(frame),cutaway=cut,
            flow=self.ramp(frame,9,.22,.85)*(1-single),seed=self.window(frame,15,15),current=current,
            field=field,local_field=max(self.window(frame,2,3),self.window(frame,24,24)),
            wire=max(self.window(frame,13,14),self.window(frame,17,17)),
            wire_heat=self.window(frame,17,17),
            energy=self.ramp(frame,19,.06,.70),magnet=max(self.window(frame,4,4),self.window(frame,7,7),compare),
            compare=compare,single=single,compass=compass,
            sun=self.ramp(frame,20,.0,.18)*(1-compare),
            solar_wind=self.window(frame,23,23),magnetosphere=self.ramp(frame,23,.25,.78),
            full_surface=max(globe20,self.ramp(frame,23,.02,.25)),
            explode=self.window(frame,6,6),rotation=self.window(frame,12,12),
            hypothesis=max(self.window(frame,4,4),self.window(frame,7,7)),
            body_turn=.65*math.sin(t*1.15)*(1-self.ramp(frame,2,.05,.55)),
            needle_angle=.72*math.exp(-t*.68)*math.cos(t*4.2),
            compass_return=self.ramp(frame,24,.02,.5),
            hot_core=self.ramp(frame,7,.08,.55),
            generated=current*self.ramp(frame,16,.08,.82))


def validate_job(job):
    if job.get('scene_graph')!=GRAPH:raise ValueError('unsupported geomagnetic graph')
    if min(job['duration_frames'],job['canonical_fps'],job['frame_count'])<=0:raise ValueError('invalid frame contract')
    cursor=0
    for beat in job['timeline']:
        if beat['controller']!=CONTROLLER or beat['start_frame']!=cursor or beat['end_frame']<=cursor:
            raise ValueError('geomagnetic timeline must be contiguous and use the registered controller')
        cursor=beat['end_frame']
    if cursor!=job['duration_frames']:raise ValueError('timeline duration mismatch')
    story=Story(job['timeline'],job['canonical_fps'])
    if list(story.spans)!=list(range(1,26)):raise ValueError('geomagnetic story requires approved scenes 1 through 25')
    cache=job['canonical_state_cache']
    if len(cache)!=cursor:raise ValueError('canonical state cache length mismatch')
    previous=-math.inf
    for f,entry in enumerate(cache):
        if entry['canonical_frame']!=f or not math.isfinite(entry['simulation_time']) or entry['simulation_time']<previous:
            raise ValueError('invalid canonical clock')
        previous=entry['simulation_time']
