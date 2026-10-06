"""Editable native Blender eclipse gallery. No video is rendered by construction.

Wide views use a compressed teaching scale with finite disk area lighting.
Observed lunar shadows use a deterministic projected shadow cross-section.
The 400:1 comparison and the five-degree orbit are separate exact-ratio models.
"""
import math
from pathlib import Path
import bpy
from mathutils import Vector, Matrix
try:
    from .scene import SpectralGallery
    from .eclipse_math import shadow_radii, orbit_position, northern_solar_offset
except ImportError:
    from scene import SpectralGallery
    from eclipse_math import shadow_radii, orbit_position, northern_solar_offset

WHITE=(.84,.91,1); GOLD=(1,.64,.20); BLUE=(.16,.57,1); RED=(.75,.10,.035)


def ease(x):
    x=max(0,min(1,x));return x*x*(3-2*x)


class EclipseGallery(SpectralGallery):
    def __init__(self,job):
        self.job=job;self.materials={};self.panels={};self.node_sockets=[]
        self.continuity_enabled=any(b.get('controller_options',{}).get('continuous_space') for b in job['timeline'])
        self.continuity=None
        self.scene=bpy.data.scenes.new('Eclipses '+job['sequence_id'])
        if bpy.context.window:bpy.context.window.scene=self.scene
        self.font=bpy.data.fonts.load('/System/Library/Fonts/Supplemental/AppleGothic.ttf')
        self.configure();self.scene.eevee.taa_render_samples=16
        self.camera.data.clip_end=3000
        for obj in list(self.scene.objects):
            if obj.type=='LIGHT':bpy.data.objects.remove(obj,do_unlink=True)
        self.scene.world.use_nodes=True
        self.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.002,.005,.013,1)
        self.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.15
        for i,name in enumerate(dict.fromkeys(b['controller'] for b in job['timeline'])):
            before=set(self.scene.objects);self.origin=Vector((0 if self.continuity_enabled else i*90,0,0));self.current=name
            self.panels[name]={'origin':self.origin.copy(),'objects':[]}
            self.build_panel(name)
            self.panels[name]['objects']=[o for o in self.scene.objects if o not in before]
            blockers=[o for o in self.panels[name]['objects'] if o.get('eclipse_blocker')]
            for light in (o for o in self.panels[name]['objects'] if o.type=='LIGHT'):
                collection=bpy.data.collections.new(name+' physical shadow blockers')
                for blocker in blockers:collection.objects.link(blocker)
                light.light_linking.blocker_collection=collection
            if name in ('eclipse-monthly','eclipse-inclination'):
                self.panels[name]['hud_labels']=[]
                for obj in self.panels[name]['objects']:
                    if obj.type=='FONT':
                        xy=(obj.location.x-self.origin.x,obj.location.y)
                        obj.parent=self.camera;obj.rotation_euler=(0,0,0)
                        self.panels[name]['hud_labels'].append((obj,xy))
        if self.continuity_enabled:
            try:from .eclipse_continuity import ContinuityRig
            except ImportError:from eclipse_continuity import ContinuityRig
            self.continuity=ContinuityRig(self)
        self.sample(0)

    def label(self,body,x,y,size=.8,color=WHITE):
        o=self.text(body,self.origin.x+x,y,size,color,'LEFT');o.location.z=8 if self.current in ('eclipse-intro','eclipse-ending','eclipse-question','eclipse-angular-size') else 3.5
        return o

    def sphere(self,name,pos,r,kind='moon',unlit=False):
        world=self.origin+Vector(pos)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64,ring_count=40,radius=r,location=world)
        o=bpy.context.object;o.name=name
        o['eclipse_blocker']=not unlit
        for p in o.data.polygons:p.use_smooth=True
        m=bpy.data.materials.new(name+' surface');m.use_nodes=True;n=m.node_tree.nodes;l=m.node_tree.links;n.clear()
        out=n.new('ShaderNodeOutputMaterial');bs=n.new('ShaderNodeEmission' if unlit else 'ShaderNodeBsdfPrincipled')
        if kind=='earth':
            tex=n.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(Path(__file__).parent/'assets/earth-atmos-r160.jpg'),check_existing=True);tex.image.pack()
            color=tex.outputs['Color']
        else:
            tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=24;tex.inputs['Detail'].default_value=4
            ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.09,.095,.11,1);ramp.color_ramp.elements[1].color=(.65,.66,.69,1)
            l.new(tex.outputs['Fac'],ramp.inputs[0]);color=ramp.outputs[0]
            if not unlit:
                bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.24;bump.inputs['Distance'].default_value=.035
                l.new(tex.outputs['Fac'],bump.inputs['Height']);l.new(bump.outputs[0],bs.inputs['Normal'])
        l.new(color,bs.inputs['Color' if unlit else 'Base Color'])
        if not unlit:
            bs.inputs['Roughness'].default_value=.84
            l.new(color,bs.inputs['Emission Color']);bs.inputs['Emission Strength'].default_value=.035
        l.new(bs.outputs[0],out.inputs[0]);o.data.materials.append(m)
        return o

    def sun(self,pos,r):
        before=set(self.scene.objects)
        o=self.star('Sun',self.origin.x+pos[0],pos[1],r,GOLD);o.location.z=pos[2]
        halo=next((obj for obj in self.scene.objects if obj not in before and 'glow' in obj.name),None)
        if halo:
            halo.location.z=pos[2]-1
            for node in halo.data.materials[0].node_tree.nodes:
                if node.type=='EMISSION':node.inputs['Color'].default_value=(.30,.37,.47,1)
        return o

    def light(self,pos,target,radius=2.5):
        light=bpy.data.lights.new('Finite solar disk','AREA');light.energy=28000;light.shape='DISK';light.size=radius*2
        if hasattr(light,'use_shadow_jitter'):light.use_shadow_jitter=True
        obj=self.link('Finite solar disk',light);obj.location=self.origin+Vector(pos)
        obj.rotation_euler=(Vector(target)-Vector(pos)).to_track_quat('-Z','Y').to_euler();return obj

    def line(self,name,points,color=BLUE,r=.018):
        return self.path(name,[self.origin+Vector(p) for p in points],color,r)

    def observed_solar(self,x=0,r=2.65):
        s=self.sun((x,0,0),r)
        moon=self.sphere('Foreground lunar silhouette',(x-r*1.9,.07,4),r*1.04,unlit=True)
        moon.data.materials.clear()
        sky_black=(.0003,.00075,.00195) if self.current in ('eclipse-intro','eclipse-ending','eclipse-question','eclipse-angular-size') else (.001,.002,.004)
        moon.data.materials.append(self.material(sky_black))
        return s,moon

    def observed_lunar(self,x=0,r=2.65):
        moon=self.sphere('Observed Moon',(x,0,0),r,unlit=True)
        # Shadow mask in the image plane, with a finite penumbral transition.
        m=moon.data.materials[0];n=m.node_tree.nodes;l=m.node_tree.links
        emission=next(q for q in n if q.type=='EMISSION');base=emission.inputs['Color'].links[0].from_socket
        coords=n.new('ShaderNodeTexCoord');sep=n.new('ShaderNodeSeparateXYZ');l.new(coords.outputs['Generated'],sep.inputs[0])
        xnode=n.new('ShaderNodeMath');xnode.operation='SUBTRACT';l.new(sep.outputs['X'],xnode.inputs[0]);xnode.inputs[1].default_value=-1
        ynode=n.new('ShaderNodeMath');ynode.operation='SUBTRACT';l.new(sep.outputs['Y'],ynode.inputs[0]);ynode.inputs[1].default_value=.5
        sqx=n.new('ShaderNodeMath');sqx.operation='MULTIPLY';l.new(xnode.outputs[0],sqx.inputs[0]);l.new(xnode.outputs[0],sqx.inputs[1])
        sqy=n.new('ShaderNodeMath');sqy.operation='MULTIPLY';l.new(ynode.outputs[0],sqy.inputs[0]);l.new(ynode.outputs[0],sqy.inputs[1])
        add=n.new('ShaderNodeMath');add.operation='ADD';l.new(sqx.outputs[0],add.inputs[0]);l.new(sqy.outputs[0],add.inputs[1])
        sqrt=n.new('ShaderNodeMath');sqrt.operation='SQRT';l.new(add.outputs[0],sqrt.inputs[0])
        ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.62;ramp.color_ramp.elements[0].color=(.24,.035,.012,1)
        ramp.color_ramp.elements[1].position=.79;ramp.color_ramp.elements[1].color=(1,1,1,1)
        l.new(sqrt.outputs[0],ramp.inputs[0]);mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1
        l.new(base,mix.inputs[1]);l.new(ramp.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],emission.inputs['Color'])
        self.node_sockets.append(xnode.inputs[1]);return moon,xnode.inputs[1]

    def build_panel(self,name):
        p=self.panels[name]
        if name in ('eclipse-intro','eclipse-ending'):
            p['sun'],p['moon']=self.observed_solar(-4.4,2.35);p['lunar'],p['shadow']=self.observed_lunar(4.4,2.35)
            self.label('일식',-6.65,3.25,1.05,GOLD);self.label('월식',2.15,3.25,1.05,BLUE)
        elif name=='eclipse-question':
            p['sun'],p['moon']=self.observed_solar(-3.5)
            self.label('작은 달이',1.1,.7,1.05);self.label('태양을 가린다?',1.1,-.65,1.05,GOLD)
        elif name=='eclipse-angular-size':
            p['sun'],p['moon']=self.observed_solar(-3.6)
            self.label('지름 약 400배',.5,1.7,.85,GOLD);self.label('거리 약 400배',.5,.35,.85,BLUE)
            self.label('겉보기 크기는 비슷',.5,-1.35,.72)
        elif name in ('solar-eclipse-alignment','lunar-eclipse-alignment'):
            lunar=name.startswith('lunar');p['sun']=self.sun((-26,0,0),2.5)
            p['earth']=self.sphere('Earth',(0 if lunar else 6,0,0),2.3,'earth')
            p['moon']=self.sphere('Moon',(9 if lunar else -2,1.8,0),.9)
            p['light']=self.light((-26,0,0),(6,0,0))
            p['lunar']=lunar
            # Boundaries are annotated geometric guides, not opaque shadow solids.
            blocker_x=0 if lunar else -2;br=2.3 if lunar else .9
            u,pen=shadow_radii(2.5,br,26+blocker_x,14)
            p['guides']=[]
            for radius,color,label in [(u,(.17,.22,.32),'Umbra'),(pen,(.16,.38,.6),'Penumbra')]:
                for sign in [-1,1]:
                    guide=self.line(label,[(blocker_x,sign*br,0),(blocker_x+14,sign*radius,0)],color,.013)
                    guide['animate_points']=True;p['guides'].append((guide,label,sign))
            # Labels are oriented as a presentation plane; close views hide them.
            p['labels']=[self.label('태양',-28,6,1.5,GOLD),self.label('지구',-1 if lunar else 5,6,1.5,BLUE),self.label('달',8 if lunar else -3,6,1.5)]
        elif name=='eclipse-observers':
            p['a'],p['am']=self.observed_solar(-4.4,2.35);p['b'],p['bm']=self.observed_solar(4.4,2.35)
            self.label('본그림자',-6.75,3.65,.65,BLUE);self.label('개기일식',-6.75,2.65,.85)
            self.label('반그림자',2.05,3.65,.65,BLUE);self.label('부분일식',2.05,2.65,.85)
        elif name=='eclipse-annular':
            p['sun'],p['moon']=self.observed_solar(-3.5)
            self.label('달의 거리 ↑',.8,1.8,.9,BLUE);self.label('겉보기 크기 ↓',.8,.45,.9)
            self.label('금환일식',.8,-1.35,1.1,GOLD)
        elif name=='eclipse-red-moon':
            p['moon'],p['shadow']=self.observed_lunar(-3.5)
            p['partial']=self.label('부분월식',.8,1,.95);p['total']=self.label('개기월식',.8,1,.95)
            self.label('왜 붉게 보일까?',.8,-.65,.9,RED)
        elif name=='eclipse-atmosphere':
            p['earth']=self.sphere('Earth atmosphere closeup',(-4,0,0),2.65,'earth');p['moon']=self.sphere('Moon receiving refracted light',(5,0,0),1.1)
            self.light((-20,8,9),(-4,0,0),4)
            self.ring('Atmospheric limb',self.origin.x-4,0,2.8,BLUE)
            points=[(-10,2.78,.3),(-4.6,2.78,.3),(-4,2.75,.3),(-3.4,2.67,.3),(4.1,.1,.3)]
            p['ray']=self.line('Representative refracted sunlight',points,WHITE,.045);p['ray']['animate_curve_reveal']=True
            p['redray']=self.line('Red component reaching Moon',points[2:],RED,.048);p['redray']['animate_curve_reveal']=True
            p['blue']=self.line('Scattered blue component',[(-4,2.75,.3),(-3.8,4.4,.3)],BLUE,.035);p['blue']['animate_curve_reveal']=True
            self.label('산란',-7.2,-3.65,.8,BLUE);self.label('굴절',-2,-3.65,.8,GOLD);self.label('달에서 반사',3,-3.65,.8)
            p['reflection']=self.line('Reflected red light',[(4.1,.1,.3),(2.5,-2.4,3)],RED,.035);p['reflection']['animate_curve_reveal']=True
            p['photon']=self.sphere('Tracked light packet',points[0],.11,unlit=True);p['points']=points
        elif name in ('eclipse-monthly','eclipse-inclination'):
            # This rig retains Earth/Moon/orbit relative sizes. The close camera
            # reveals the otherwise small spheres; their radii never change.
            p['earth']=self.sphere('Earth orbital reference',(0,0,0),.10,'earth');p['moon']=self.sphere('Moon inclined orbit',(6,0,0),.0273)
            p['earth_marker']=self.sphere('Enlarged Earth locator',(0,0,0),.55,'earth',True)
            p['moon_marker']=self.sphere('Enlarged Moon locator',(6,0,0),.24,unlit=True)
            p['enlarged_caption']=self.label('천체 크기 확대',-7.2,3.1 if name=='eclipse-inclination' else 4.15,.65)
            p['light']=self.light((-20,0,0),(0,0,0),.093)
            p['light'].data.energy=3500
            self.line('Ecliptic reference',[(6*math.cos(a*math.tau/128),6*math.sin(a*math.tau/128),0) for a in range(129)],(.12,.21,.32),.02)
            self.line('Lunar orbit five degrees',[orbit_position(a*math.tau/128,node=math.pi/2) for a in range(129)],BLUE,.015)
            self.line('Line of nodes',[(0,-7,0),(0,7,0)],GOLD,.012)
            p['shadow_guides']=[]
            for sign in (-1,1):
                guide=self.line('Umbra boundary',[(0,sign*.1,0),(7,sign*.0675,0)],(.22,.30,.43),.009)
                guide['animate_points']=True;p['shadow_guides'].append((guide,sign))
            p['thin_curves']=[o for o in self.scene.objects if o.type=='CURVE' and o.name not in {g.name for g,sign in p['shadow_guides']}]
            p['thin_curves'] += [g for g,sign in p['shadow_guides']]
            p['labels']=[self.label('삭',-7.2,-.6,.8),self.label('망 · 보름',4.8,-.6,.8)]
            if name=='eclipse-inclination':
                self.label('궤도면의 기울기',-7.2,4.15,.8);self.label('약 5°',3.3,4.15,1,GOLD)
        else:raise ValueError(name)

    def point_camera(self,position,target,scale):
        self.camera.location=position
        direction=(Vector(target)-Vector(position)).normalized()
        right=direction.cross(Vector((0,1,0))).normalized();up=right.cross(direction)
        self.camera.rotation_euler=Matrix((right,up,-direction)).transposed().to_euler()
        self.camera.data.ortho_scale=scale

    def sample(self,frame):
        entry=self.job['canonical_state_cache'][frame]
        active=[b for b in self.job['timeline'] if b['beat_id'] in entry['active_beat_ids']]
        beat=max(active,key=lambda b:b.get('priority',0));name=beat['controller'];panel=self.panels[name];origin=panel['origin']
        related=[b for b in self.job['timeline'] if b['controller']==name]
        start=min(b['start_frame'] for b in related);end=max(b['end_frame'] for b in related)
        p=(frame-start)/max(1,end-start-1);q=ease(p);time=entry['simulation_time']
        bp=(frame-beat['start_frame'])/max(1,beat['end_frame']-beat['start_frame']-1)
        tracked=[self.camera]
        self.camera.data.type='ORTHO'
        for key,pan in self.panels.items():
            for obj in pan['objects']:
                obj.hide_render=key!=name;obj.hide_viewport=key!=name
                tracked.append(obj)
        self.point_camera(origin+Vector((0,0,28)),origin,18.8)
        if name in ('eclipse-intro','eclipse-ending'):
            panel['moon'].location.x=origin.x-4.4+northern_solar_offset(p,3.7)
            panel['shadow'].default_value=-.7+1.2*q
        elif name in ('eclipse-question','eclipse-angular-size','eclipse-annular'):
            x=-3.6 if name=='eclipse-angular-size' else -3.5
            panel['moon'].location.x=origin.x+x+northern_solar_offset(p,.25 if name=='eclipse-question' else 3.9)
            if name=='eclipse-annular':
                panel['moon'].location.x=origin.x+x
                panel['moon'].scale=(1-.2*q,)*3
        elif name in ('solar-eclipse-alignment','lunar-eclipse-alignment'):
            lunar=panel['lunar'];panel['moon'].location.y=4.5*(1-ease((p-.3)/.7))
            blocker=Vector((0,0,0)) if lunar else panel['moon'].location-origin
            source=Vector((-26,0,0));axis=(blocker-source).normalized();perp=Vector((-axis.y,axis.x,0))
            br=2.3 if lunar else .9;u,pen=shadow_radii(2.5,br,(blocker-source).length,14)
            for guide,label,sign in panel['guides']:
                a=origin+blocker+perp*(sign*br)
                b=origin+blocker+axis*14+perp*(sign*(u if label=='Umbra' else pen))
                guide.data.splines[0].points[0].co=(*a,1);guide.data.splines[0].points[1].co=(*b,1)
            close=beat.get('controller_options',{}).get('view_mode')!='wide_alignment'
            if close:
                v=ease(min(1,bp*2));target=origin+Vector((9 if lunar else 6,panel['moon'].location.y if lunar else 0,0))
                pos=origin+Vector((3 if lunar else -1,(panel['moon'].location.y if lunar else 0)-1.5,12))
                self.point_camera((origin+Vector((-9,7,39))).lerp(pos,v),(origin+Vector((-9,0,0))).lerp(target,v),44+((5.8 if lunar else 9)-44)*v)
                for o in panel['labels']:o.hide_render=True;o.hide_viewport=True
                for guide,_,_ in panel['guides']:guide.hide_render=v>.65;guide.hide_viewport=v>.65
            else:self.point_camera(origin+Vector((-9,7,39)),origin+Vector((-9,0,0)),44)
        elif name=='eclipse-observers':
            panel['am'].location.x=origin.x-4.4+.08*math.sin(q*math.pi)
            panel['bm'].location.x=origin.x+4.4+1.65-.2*q
        elif name=='eclipse-red-moon':
            panel['shadow'].default_value=-.55+1.05*ease(p/.65)
            panel['partial'].hide_render=p>.55;panel['partial'].hide_viewport=p>.55
            panel['total'].hide_render=p<=.55;panel['total'].hide_viewport=p<=.55
        elif name=='eclipse-atmosphere':
            panel['ray'].data.bevel_factor_end=max(.001,min(1,p*1.7))
            panel['redray'].data.bevel_factor_end=max(.001,min(1,(p-.45)*2.2))
            panel['blue'].data.bevel_factor_end=max(.001,min(1,(p-.3)*3))
            panel['reflection'].data.bevel_factor_end=max(.001,min(1,(p-.85)/.15))
            points=panel['points'];u=q*(len(points)-1);i=min(int(u),len(points)-2)
            panel['photon'].location=origin+Vector(points[i]).lerp(Vector(points[i+1]),u-i)
        elif name in ('eclipse-monthly','eclipse-inclination'):
            if name=='eclipse-monthly':
                angle=math.pi/2+q*math.tau
                moonpos=Vector(orbit_position(angle,node=math.pi/2))
                shadowdir=Vector((1,0,0));tilt=ease(p)
                self.point_camera(origin+Vector((0,-18*tilt,28-17*tilt)),origin,18.8)
            else:
                # Earth progresses around the Sun; the fixed lunar nodes meet
                # the changing Sun direction. No instantaneous change of tilt.
                sunangle=math.pi-q*math.pi/2
                moonpos=Vector(orbit_position(sunangle+math.pi-math.pi/2,node=math.pi/2))
                shadowdir=Vector((-math.cos(sunangle),-math.sin(sunangle),0))
                zoom=ease((p-.35)/.5);target=origin.lerp(origin+moonpos,zoom)
                self.point_camera(target+Vector((0,10,10)),target,18.8+(.32-18.8)*zoom)
            panel['moon'].location=origin+moonpos
            panel['moon_marker'].location=origin+moonpos
            marker_factor=1 if name=='eclipse-monthly' else 1-ease((p-.35)/.35)
            for key in ('earth_marker','moon_marker'):
                panel[key].scale=(max(.001,marker_factor),)*3
                panel[key].hide_render=marker_factor<.01;panel[key].hide_viewport=marker_factor<.01
            panel['enlarged_caption'].hide_render=marker_factor<.01;panel['enlarged_caption'].hide_viewport=marker_factor<.01
            perp=Vector((-shadowdir.y,shadowdir.x,0))
            for guide,sign in panel['shadow_guides']:
                guide.data.splines[0].points[0].co=(*(origin+perp*sign*.1),1)
                guide.data.splines[0].points[1].co=(*(origin+shadowdir*7+perp*sign*.0675),1)
            panel['light'].location=origin-shadowdir*20
            panel['light'].rotation_euler=shadowdir.to_track_quat('-Z','Y').to_euler()
            for curve in panel['thin_curves']:
                curve.data.bevel_depth=max(.00015,.012*self.camera.data.ortho_scale/18.8)
                curve.data['animate_bevel_depth']=True
            ratio=self.camera.data.ortho_scale/18.8
            for obj,xy in panel['hud_labels']:
                obj.location=(xy[0]*ratio,xy[1]*ratio,-2);obj.scale=(ratio,)*3
                if name=='eclipse-inclination' and obj in panel['labels']:
                    obj.hide_render=p>.35;obj.hide_viewport=p>.35
        for key in ('sun','a','b'):
            obj=panel.get(key)
            if obj:obj.rotation_euler.y=.025*time
        for key in ('earth',):
            obj=panel.get(key)
            if obj:obj.rotation_euler.z=.018*time
        if self.continuity:
            tracked.extend(self.continuity.sample(name,time,p,frame))
        return entry,tracked

    def bake(self):
        for frame in range(self.job['duration_frames']):
            _,objects=self.sample(frame)
            for obj in objects:
                for prop in ('location','rotation_euler','scale','hide_render','hide_viewport'):
                    obj.keyframe_insert(data_path=prop,frame=frame+1)
                if obj.get('animate_curve_reveal'):obj.data.keyframe_insert(data_path='bevel_factor_end',frame=frame+1)
                if obj.type=='CURVE' and obj.data.get('animate_bevel_depth'):obj.data.keyframe_insert(data_path='bevel_depth',frame=frame+1)
                if obj.get('animate_points'):
                    for point in obj.data.splines[0].points:point.keyframe_insert(data_path='co',frame=frame+1)
            for socket in self.node_sockets:socket.keyframe_insert(data_path='default_value',frame=frame+1)
            self.camera.data.keyframe_insert(data_path='ortho_scale',frame=frame+1)
            self.camera.data.keyframe_insert(data_path='lens',frame=frame+1)
            self.camera.data.keyframe_insert(data_path='type',frame=frame+1)
        self.scene.frame_set(1);self.font.pack();bpy.ops.file.pack_all()

    def extra_state(self):
        return {'shadow_nodes':[float(s.default_value) for s in self.node_sockets],
                'visibility':{o.name:not o.hide_render for p in self.panels.values() for o in p['objects']}}
