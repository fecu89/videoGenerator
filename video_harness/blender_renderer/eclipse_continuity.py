"""Shared-space eclipse staging, opt-in through continuous_space beat options.

Absolute narration time drives cross-sequence endpoints. Solar staging is an
explicitly compressed spatial illustration, not a scale model of the 400:1
numbers. The tilted orbit retains its actual five-degree geometry.
"""
import math
import bpy
from mathutils import Vector, Matrix, Quaternion
from bpy_extras.object_utils import world_to_camera_view
try:
    from .eclipse_math import orbit_position, shadow_radii
except ImportError:
    from eclipse_math import orbit_position, shadow_radii

WHITE=(.84,.91,1); GOLD=(1,.64,.20); BLUE=(.16,.57,1); RED=(.75,.10,.035)

def smooth(x):
    x=max(0,min(1,x));return x*x*x*(x*(x*6-15)+10)

def ramp(t,a,b):return smooth((t-a)/(b-a))

class ContinuityRig:
    def __init__(self,g):
        self.g=g;self.groups={};self.labels={};self.sockets={}
        names={b['controller'] for b in g.job['timeline']}
        if names & {'eclipse-intro','eclipse-question','eclipse-angular-size','solar-eclipse-alignment'}:
            self.build_solar()
        if names & {'lunar-eclipse-alignment','eclipse-red-moon'}:
            self.build_lunar()
        if 'eclipse-inclination' in names:
            g.current='eclipse-inclination';g.origin=Vector((0,0,0))
            before=set(g.scene.objects)
            self.hud('orbit_miss','대부분은 그림자를 비껴간다',-7.5,-3.9,.78,WHITE)
            self.hud('orbit_align','교점에서 정렬되면 식',-7.5,-3.9,.86,GOLD)
            self.groups['orbit_extra']=[o for o in g.scene.objects if o not in before]

    def begin(self,name):
        self.g.origin=Vector((0,0,0));self.g.current=name
        return set(self.g.scene.objects)

    def finish(self,name,before):
        g=self.g;objs=[o for o in g.scene.objects if o not in before];self.groups[name]=objs
        blockers=[o for o in objs if o.get('eclipse_blocker')]
        for light in (o for o in objs if o.type=='LIGHT'):
            col=bpy.data.collections.new(name+' shadow casters')
            for obj in blockers:col.objects.link(obj)
            light.light_linking.blocker_collection=col

    def hud(self,key,body,x,y,size=.85,color=WHITE):
        g=self.g;o=g.text(body,0,0,size,color,'LEFT');o.parent=g.camera
        o.rotation_euler=(0,0,0)
        # Independent material permits fades without dimming other objects.
        o.data.materials[0]=o.data.materials[0].copy()
        socket=next(n for n in o.data.materials[0].node_tree.nodes if n.type=='EMISSION').inputs['Strength']
        g.node_sockets.append(socket);self.sockets[key]=socket
        self.labels[key]=(o,x,y);return o

    def show_label(self,key,amount=1,xy=None):
        o,x,y=self.labels[key]
        if xy is not None:x,y=xy
        cam=self.g.camera.data
        factor=(2*2*cam.sensor_width/(2*cam.lens)/18.8 if cam.type=='PERSP' else cam.ortho_scale/18.8)
        o.location=(x*factor,y*factor,-2);o.scale=(factor,)*3
        o.hide_render=o.hide_viewport=amount<.002
        self.sockets[key].default_value=amount

    def camera(self,pos,target,lens=46,up=(0,0,1)):
        cam=self.g.camera;cam.data.type='PERSP';cam.data.lens=lens
        cam.data.clip_start=.01;cam.location=pos
        direction=(Vector(target)-Vector(pos)).normalized()
        right=direction.cross(Vector(up)).normalized();up=right.cross(direction)
        cam.rotation_euler=Matrix((right,up,-direction)).transposed().to_euler()

    def visible(self,group):
        for obj in self.groups[group]:obj.hide_render=obj.hide_viewport=False

    def hide_base(self):
        for panel in self.g.panels.values():
            for obj in panel['objects']:obj.hide_render=obj.hide_viewport=True

    def plain_sun(self,pos,r):
        g=self.g;before=set(g.scene.objects);sun=g.sun(pos,r)
        for obj in list(set(g.scene.objects)-before):
            if 'glow' in obj.name:bpy.data.objects.remove(obj,do_unlink=True)
        return sun

    def build_solar(self):
        g=self.g;before=self.begin('continuous solar')
        self.sun=self.plain_sun((-39,0,0),4)
        self.earth=g.sphere('Continuous Earth',(3.4,0,0),2.3,'earth')
        self.moon=g.sphere('Continuous Moon',(-8,1.6,0),1.05)
        g.node_sockets.append(next(n for n in self.moon.data.materials[0].node_tree.nodes if n.type=='BSDF_PRINCIPLED').inputs['Emission Strength'])
        self.sunlight=g.light((-39,0,0),(3.4,0,0),4);self.sunlight.data.energy=60000
        self.surface_marks=[]
        for title,y,z,color in [('Umbra observer',.035,0,BLUE),('Penumbra observer',-.75,.8,WHITE)]:
            x=3.4-math.sqrt(2.31**2-y*y-z*z)
            obj=g.sphere(title,(x,y,z),.055,unlit=True);obj.data.materials.clear();obj.data.materials.append(g.material(color))
            self.surface_marks.append(obj)
        self.guides=[]
        for label,color,radius in [('Umbra',(.22,.29,.40),0),('Penumbra',(.14,.38,.61),1)]:
            for sign in (-1,1):
                o=g.line(label+' shared space',[(-8,sign*1.05,0),(6,0,0)],color,.023)
                o['animate_points']=True;o['animate_curve_reveal']=True
                self.guides.append((o,radius,sign))
        self.hud('solar_title','일식',-6.6,3.3,1.05,GOLD)
        self.hud('lunar_title','월식',2.1,3.3,1.05,BLUE)
        self.hud('question1','작은 달이',.4,.8,1.05)
        self.hud('question2','태양을 가린다?',.4,-.6,1.05,GOLD)
        self.hud('ratio1','실제 지름 약 400배',-7.8,3.45,.84,GOLD)
        self.hud('ratio2','실제 거리 약 400배',-7.8,2.25,.84,BLUE)
        self.hud('ratio3','겉보기 크기는 비슷',.7,3.45,.77)
        self.hud('sun_name','태양',0,0,.85,GOLD)
        self.hud('moon_name','달',0,0,.75)
        self.hud('earth_name','지구',0,0,.85,BLUE)
        self.hud('shadow_title','달의 그림자가 지구에 닿으면',-7.8,3.65,.85)
        self.hud('umbra_name','본그림자',1.9,.1,1.2,BLUE)
        self.hud('penumbra_name','반그림자',1.9,2.4,1.2)
        self.shadow_leaders=[]
        for name,color in [('umbra_name',BLUE),('penumbra_name',WHITE)]:
            line=g.line(name+' surface leader',[(0,0,-2),(0,0,-2),(0,0,-2)],color,.018)
            line.parent=g.camera;line['animate_points']=True
            self.shadow_leaders.append((line,name))
        self.intro_lunar,self.intro_shadow=g.observed_lunar(0,2.35)
        self.intro_lunar.parent=g.camera
        g.node_sockets.append(next(n for n in self.intro_lunar.data.materials[0].node_tree.nodes if n.type=='EMISSION').inputs['Strength'])
        # The introductory comparison is a camera-facing observer inset.
        self.finish('solar',before)

    def solar(self,t):
        g=self.g;self.hide_base();self.visible('solar')
        a=ramp(t,19.0,24.4);b=ramp(t,30.3,34.4);c=ramp(t,36.6,40.8)
        eye=Vector((1,0,0));diagonal=Vector((-8,-55,24)).lerp(Vector((-11,-52,29)),ramp(t,24.4,30.3));overhead=Vector((-17,-3,67))
        pos=eye.lerp(diagonal,a).lerp(overhead,b).lerp(Vector((-2,-5,8)),c)
        sun_dir=(Vector((-39,0,0))-pos).normalized()
        moon_dir=(Vector((-8,0,0))-pos).normalized()
        earth_dir=(Vector((3.4,0,0))-pos).normalized()
        center=(sun_dir+moon_dir).normalized().lerp((sun_dir+earth_dir).normalized(),ramp(a,.3,.85)).normalized()
        center += center.cross(Vector((0,0,1))).normalized()*(.1875*(1-a)**2)
        fly_target=pos+center*40
        close_target=Vector((4.17,-2.17,0));close_pos=close_target+Vector((-14,-5,7))
        pos=eye.lerp(diagonal,a).lerp(overhead,b).lerp(close_pos,c)
        target=fly_target.lerp(Vector((-17,0,0)),b).lerp(close_target,c)
        self.camera(pos,target,45-9*a+4*c)
        if 0<a<1 and b==0:
            # Fit both separated disks throughout the flyout, including the
            # middle of the move; endpoint-only framing misses this case.
            forward=(target-pos).normalized();right=forward.cross(Vector((0,0,1))).normalized();up=right.cross(forward)
            limit=self.g.camera.data.lens
            for center,radius in [(Vector((-39,0,0)),4),(Vector((-8,0,0)),1.05)]:
                delta=center-pos;angular=math.asin(min(.99,radius/delta.length));depth=delta.dot(forward)
                horizontal=abs(math.atan2(delta.dot(right),depth))+angular+.035
                vertical=abs(math.atan2(delta.dot(up),depth))+angular+.025
                limit=min(limit,36/(2*math.tan(horizontal)),36/(2*math.tan(vertical)*16/9))
            self.g.camera.data.lens=max(15,limit)
        # The physical Moon keeps its identity throughout the camera excursion.
        self.moon.location.y=1.6-1.05*ramp(t,0,11.3)-.37*ramp(t,11.3,19.5)-.155*ramp(t,19.5,24.4)
        bs=next(n for n in self.moon.data.materials[0].node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        bs.inputs['Emission Strength'].default_value=.0005+.0345*ramp(a,.08,.5)
        self.sun.rotation_euler.y=.025*t;self.earth.rotation_euler.z=.018*t
        for key in self.labels:self.show_label(key,0)
        intro=1-ramp(t,9.8,11.3)
        self.show_label('solar_title',intro);self.show_label('lunar_title',intro)
        factor=4*g.camera.data.sensor_width/(2*g.camera.data.lens)/18.8
        self.intro_lunar.location=(4.4*factor,0,-2)
        self.intro_lunar.scale=(factor,)*3
        self.intro_lunar.hide_render=self.intro_lunar.hide_viewport=t>11.3
        self.intro_shadow.default_value=-.7+1.2*ramp(t,0,11.3)
        # Fade the inset using its surface brightness, with no backing plate.
        emission=next(n for n in self.intro_lunar.data.materials[0].node_tree.nodes if n.type=='EMISSION')
        emission.inputs['Strength'].default_value=intro
        question=ramp(t,11.3,12.0)*(1-ramp(t,18.8,19.4))
        self.show_label('question1',question);self.show_label('question2',question)
        text=ramp(t,24.1,24.8)*(1-ramp(t,29.7,30.3))
        for key in ('ratio1','ratio2','ratio3'):self.show_label(key,text)
        alignment=ramp(t,34.1,34.8)*(1-ramp(t,36.3,37.0))
        self.show_label('shadow_title',alignment)
        label_amount=max(text,alignment)
        for key,obj in [('sun_name',self.sun),('moon_name',self.moon),('earth_name',self.earth)]:
            local=g.camera.rotation_euler.to_quaternion().inverted() @ (obj.location-g.camera.location)
            halfwidth=max(.001,-local.z*g.camera.data.sensor_width/(2*g.camera.data.lens))
            self.show_label(key,label_amount,(local.x/halfwidth*9.4-.5,local.y/halfwidth*9.4-1.8))
        source=Vector((-39,0,0));blocker=self.moon.location.copy();axis=(blocker-source).normalized()
        perp=Vector((-axis.y,axis.x,0));radii=shadow_radii(4,1.05,(blocker-source).length,14)
        reveal=ramp(t,33.8,35.6)
        for obj,index,sign in self.guides:
            obj.hide_render=obj.hide_viewport=reveal<.002 or c>.8
            obj.data.bevel_factor_end=max(.001,reveal)
            for point,co in zip(obj.data.splines[0].points,[blocker+perp*sign*1.05,blocker+axis*14+perp*sign*radii[index]]):point.co=(*co,1)
        close_text=ramp(t,40.4,41.1)
        self.show_label('umbra_name',close_text);self.show_label('penumbra_name',close_text)
        for obj in self.surface_marks:
            obj.hide_render=obj.hide_viewport=close_text<.002
            obj.scale=(max(.001,close_text),)*3
        factor=4*g.camera.data.sensor_width/(2*g.camera.data.lens)/18.8
        for (line,key),mark in zip(self.shadow_leaders,self.surface_marks):
            local=g.camera.rotation_euler.to_quaternion().inverted() @ (mark.location-g.camera.location)
            start=local*(-2/local.z)
            _,x,y=self.labels[key]
            end=Vector(((x-.2)*factor,(y+.42)*factor,-2))
            elbow=Vector((.9*factor,end.y,-2))
            for point,co in zip(line.data.splines[0].points,[start,elbow,end]):point.co=(*co,1)
            line.data.bevel_depth=.018*factor
            line.hide_render=line.hide_viewport=close_text<.002

    def build_lunar(self):
        g=self.g;before=self.begin('continuous lunar')
        self.lsun=self.plain_sun((-26,0,0),2.5)
        self.learth=g.sphere('Lunar eclipse Earth',(0,0,0),2.3,'earth')
        self.lmoon,self.lshadow=g.observed_lunar(0,.9);self.lmoon.name='Continuous eclipsed Moon'
        g.light((-26,0,0),(0,0,0),2.5)
        self.lguides=[]
        radii=shadow_radii(2.5,2.3,26,14)
        for radius,color in zip(radii,[(.17,.22,.32),(.16,.38,.6)]):
            for sign in (-1,1):self.lguides.append(g.line('Lunar shadow boundary',[(0,sign*2.3,0),(14,sign*radius,0)],color,.018))
        self.hud('lunar_alignment','태양 — 지구 — 달',-7.5,3.65,.9)
        self.hud('partial','부분월식',.8,1,.95)
        self.hud('total','개기월식',.8,1,.95)
        self.hud('red_question','왜 붉게 보일까?',.8,-.65,.9,RED)
        self.hud('scatter','푸른빛은 주변으로 산란',-3.2,4.35,.72,BLUE)
        self.hud('refract','남은 붉은빛은 굴절',-7.4,-3.65,.86,GOLD)
        self.hud('reflect','달에서 반사',3.2,-3.65,.86,RED)
        self.atmosphere=[]
        ring=g.line('Earth atmospheric limb',[(2.55*math.cos(i*math.tau/128),2.55*math.sin(i*math.tau/128),.12) for i in range(129)],(.025,.09,.19),.12)
        self.atmosphere.append(ring)
        self.white_ray=g.line('One incident white sunlight ray',[(-6,2.52,.2),(-.5,2.52,.2)],WHITE,.045)
        self.white_ray['animate_curve_reveal']=True;self.atmosphere.append(self.white_ray)
        try:from .atmospheric_light import build_atmospheric_light
        except ImportError:from atmospheric_light import build_atmospheric_light
        self.spectral_band,self.band_reveal,self.scatter_packets=build_atmospheric_light(g)
        self.atmosphere.append(self.spectral_band)
        self.reflection=g.line('Red light reflected by Moon',[(8.2,.24,.2),(6.5,-1.7,1.4)],(1,.08,.025),.032)
        self.reflection['animate_curve_reveal']=True;self.atmosphere.append(self.reflection)
        self.finish('lunar',before)

    def lunar(self,t):
        g=self.g;self.hide_base();self.visible('lunar')
        for key in ('lunar_alignment','partial','total','red_question','scatter','refract','reflect'):self.show_label(key,0)
        v=ramp(t,69.6,77.5)
        # Increasing polar angle as seen from the north: counterclockwise.
        angle=-.52*(1-ramp(t,66.2,82.4))
        self.lmoon.location=(9*math.cos(angle),9*math.sin(angle),0)
        # In this north-pole spatial view the Moon enters from below the
        # shadow, so the shadow first covers its upper limb.
        self.lmoon.rotation_euler.z=-math.pi/2
        # Roll the view counterclockwise on screen from the north-pole view
        # into the observer inset: the upper shadow edge becomes the left edge.
        observer_roll=-math.pi/2*ramp(t,71.8,77.3)
        close=self.lmoon.location+Vector((1.19*math.cos(observer_roll),1.19*math.sin(observer_roll),0))
        target=Vector((-9,0,0)).lerp(close,v)
        pos=Vector((-9,7,39)).lerp(close+Vector((0,0,12)),v)
        pullback=ramp(t,84.9,88.4)
        target=target.lerp(Vector((2.5,.35,0)),pullback)
        pos=pos.lerp(Vector((2.5,.35,24)),pullback)
        g.point_camera(pos,target,(44+(6.4-44)*v)*(1-pullback)+17.5*pullback)
        g.camera.rotation_euler=(g.camera.rotation_euler.to_quaternion() @ Quaternion((0,0,1),observer_roll*(1-pullback))).to_euler()
        self.lshadow.default_value=-.7+1.2*ramp(t,72.0,83.3)
        self.lsun.rotation_euler.y=.025*t;self.learth.rotation_euler.z=.018*t
        for obj in self.lguides:obj.hide_render=obj.hide_viewport=v>.7
        self.show_label('lunar_alignment',1-ramp(t,69.0,69.7))
        label=ramp(t,77.2,77.9)
        self.show_label('partial',label*(1-ramp(t,81.7,82.1)))
        self.show_label('total',ramp(t,81.7,82.1)*(1-ramp(t,84.5,85.2)))
        self.show_label('red_question',ramp(t,82.6,83.4)*(1-ramp(t,84.5,85.2)))
        for obj in self.atmosphere:obj.hide_render=obj.hide_viewport=t<88.0
        self.fade_base(self.atmosphere[0],ramp(t,87.9,88.7))
        white=ramp(t,88.0,89.4);self.white_ray.data.bevel_factor_end=max(.001,white)
        self.white_ray.hide_render=self.white_ray.hide_viewport=white<.002
        self.band_reveal.default_value=ramp(t,89.0,95.0)
        self.spectral_band.hide_render=self.spectral_band.hide_viewport=t<89.0
        try:from .atmospheric_light import animate_scattering
        except ImportError:from atmospheric_light import animate_scattering
        animate_scattering(self.scatter_packets,t)
        reflection=ramp(t,96.0,98.3)
        self.reflection.data.bevel_factor_end=max(.001,reflection)
        self.reflection.hide_render=self.reflection.hide_viewport=reflection<.002
        self.show_label('scatter',ramp(t,89.2,90.0))
        self.show_label('refract',ramp(t,92.1,92.8))
        self.show_label('reflect',ramp(t,96.0,96.7))

    def observers(self,t,panel):
        g=self.g
        v=ramp(t,50.2,52.4)
        panel['a'].location.x=-4.4+.9*v;panel['am'].location.x=-4.4+.9*v
        ratio=1+(2.65/2.35-1)*v
        panel['a'].scale=(ratio,)*3;panel['am'].scale=(ratio,)*3
        for obj in panel['objects']:
            if obj.type=='FONT' or obj in (panel['b'],panel['bm']) or 'glow' in obj.name:
                # Fade explanatory words and the second observer before focus.
                if obj.type=='FONT':self.fade_base(obj,1-ramp(t,49.8,50.7))
                elif obj in (panel['b'],panel['bm']):self.fade_base(obj,1-v)
                else:
                    if 'continuity_side' not in obj:obj['continuity_side']=1 if obj.location.x>0 else -1
                    if obj['continuity_side']<0:
                        obj.location.x=-4.4+.9*v;obj.scale=(ratio,)*3
                    else:self.fade_base(obj,1-v)

    def fade_base(self,obj,amount):
        key='base_'+obj.name
        if key not in self.sockets:
            obj.data.materials[0]=obj.data.materials[0].copy()
            socket=next(n for n in obj.data.materials[0].node_tree.nodes if n.type=='EMISSION').inputs['Strength']
            if socket.is_linked:
                nt=obj.data.materials[0].node_tree;old=socket.links[0].from_socket
                mult=nt.nodes.new('ShaderNodeMath');mult.operation='MULTIPLY'
                nt.links.new(old,mult.inputs[0]);nt.links.new(mult.outputs[0],socket)
                socket=mult.inputs[1]
            self.sockets[key]=socket;self.g.node_sockets.append(socket)
        self.sockets[key].default_value=amount
        obj.hide_render=obj.hide_viewport=amount<.002

    def annular(self,t,panel):
        for obj in panel['objects']:
            if obj.type=='FONT':self.fade_base(obj,ramp(t,52.4,53.3))

    def orbit(self,name,p,t,panel):
        g=self.g
        if name=='eclipse-monthly':
            g.point_camera(Vector((0,-3,28)),Vector((0,0,0)),24)
            for obj,xy in panel['hud_labels']:
                obj.location=(xy[0]*24/18.8,xy[1]*24/18.8,-2);obj.scale=(24/18.8,)*3
                self.fade_base(obj,1-ramp(t,108.2,108.9))
            return
        self.visible('orbit_extra')
        tilt=ramp(p,0,.38);zoom=ramp(p,.66,.95)
        angle=math.pi/2+1.5*math.pi*smooth(p)
        moon=Vector(orbit_position(angle,node=math.pi/2))
        panel['moon'].location=moon;panel['moon_marker'].location=moon
        sunangle=math.pi+math.pi/2*ramp(p,.62,1)
        shadowdir=Vector((-math.cos(sunangle),-math.sin(sunangle),0))
        panel['light'].location=-shadowdir*20
        panel['light'].rotation_euler=shadowdir.to_track_quat('-Z','Y').to_euler()
        perp=Vector((-shadowdir.y,shadowdir.x,0))
        for guide,sign in panel['shadow_guides']:
            for point,co in zip(guide.data.splines[0].points,[perp*sign*.1,shadowdir*7+perp*sign*.0675]):point.co=(*co,1)
        target=Vector((0,0,0)).lerp(moon,zoom)
        offset=Vector((0,-3,28)).lerp(Vector((0,-27,3.8)),tilt).lerp(Vector((3,6,8)),zoom)
        scale=24+(.35-24)*zoom
        g.point_camera(target+offset,target,scale)
        marker=1-ramp(p,.58,.78)
        for key in ('earth_marker','moon_marker'):
            panel[key].scale=(max(.001,marker),)*3
            panel[key].hide_render=panel[key].hide_viewport=marker<.002
        panel['enlarged_caption'].hide_render=panel['enlarged_caption'].hide_viewport=marker<.002
        for curve in panel['thin_curves']:
            curve.data.bevel_depth=max(.00015,.012*scale/18.8)
            if curve in panel['objects']:curve.hide_render=curve.hide_viewport=zoom>.85
        for obj,xy in panel['hud_labels']:
            obj.location=(xy[0]*scale/18.8,xy[1]*scale/18.8,-2);obj.scale=(scale/18.8,)*3
            if obj in panel['labels']:obj.hide_render=obj.hide_viewport=p>.08
            else:
                self.fade_base(obj,ramp(p,0,.08))
                if obj==panel['enlarged_caption'] and marker<.002:obj.hide_render=obj.hide_viewport=True
        self.show_label('orbit_miss',ramp(p,.12,.2)*(1-ramp(p,.6,.68)))
        self.show_label('orbit_align',ramp(p,.9,.97))

    def sample(self,name,t,p,frame):
        for group in self.groups.values():
            for obj in group:obj.hide_render=obj.hide_viewport=True
        if name in ('eclipse-intro','eclipse-question','eclipse-angular-size','solar-eclipse-alignment'):self.solar(t)
        elif name in ('lunar-eclipse-alignment','eclipse-red-moon','eclipse-atmosphere'):self.lunar(t)
        elif name=='eclipse-observers':self.observers(t,self.g.panels[name])
        elif name=='eclipse-annular':self.annular(t,self.g.panels[name])
        elif name in ('eclipse-monthly','eclipse-inclination'):self.orbit(name,p,t,self.g.panels[name])
        for panel in self.g.panels.values():
            if 'enlarged_caption' in panel:
                panel['enlarged_caption'].hide_render=panel['enlarged_caption'].hide_viewport=True
        return [o for group in self.groups.values() for o in group]
