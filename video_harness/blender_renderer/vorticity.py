"""Native Blender vorticity scenes; GLBs and deterministic teaching geometry."""
import math
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
from scene import SpectralGallery, CYAN, GOLD, INK
from vorticity_math import contributions, earth_pose
from vorticity_direction import VorticityDirection
from animated_materials import animated_sockets

PINK = (1.0, .23, .42)
LABELS = {
    1: ('굽이치는 바람', '북 ↑     동 →'),
    2: ('편서풍', '상층 제트류'),
    3: ('남북 이동', '회전 변화'),
    4: ('소용돌이도', '와도'),
    5: ('관람차는 회전', '객실의 방향은 유지'),
    6: ('이동 ≠ 회전', '작은 부분의 회전'),
    7: ('우주에서 관찰', '지구와 함께 회전'),
    8: ('지표에서 관찰', '상대 회전 0'),
    9: ('상대와도\n+ 행성와도', '= 절대와도'),
    10: ('지역의 수직축', '축 주위의 회전'),
    11: ('북극: 나란함', '적도: 직각'),
    12: ('f = 2Ω sinφ', '적도 0 → 북극 최대'),
    13: ('ζ + f = 일정', '마찰 없음\n두께 일정'),
    14: ('북상: f ↑  ζ ↓', '시계 방향'),
    15: ('남하: f ↓  ζ ↑', '반시계 방향'),
    16: ('회전 → 주변 흐름', '파동과의 연결'),
    17: ('시계 회전의 동쪽', '남쪽으로'),
    18: ('반시계 회전의 동쪽', '북쪽으로'),
    19: ('이웃한 흐름의 연결', '로스비파'),
}


def ease(p):
    p = max(0., min(1., p))
    return p*p*(3-2*p)


class VorticityGallery(SpectralGallery):
    def __init__(self, job):
        self.groups = {}
        self.wheel_cache = []
        self.earth_meshes = []
        super().__init__(job)
        self.scene.name = 'Vorticity '+job['sequence_id']
        self.scene.world.use_nodes=True
        self.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.005,.012,.027,1)
        self.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.6
        self.camera.name = 'VorticityCamera'
        self.camera.data.ortho_scale = 24

    def group(self, key, build):
        before = set(self.scene.objects)
        build()
        self.groups[key] = list(set(self.scene.objects)-before)

    def arrow(self, name, start, end, color=CYAN):
        a, b = Vector(start), Vector(end)
        d = (b-a).normalized()
        side = Vector((-d.y, d.x, 0))*.17
        return [self.path(name, [a,b], color, .035),
                self.path(name+'Tip', [b-d*.32+side,b,b-d*.32-side], color, .035)]

    def marker(self, name, pos, color=GOLD, radius=.14):
        return self.star(name, pos[0], pos[1], radius, color)

    def ring(self,name,x,y,r,color=CYAN):
        curve=super().ring(name,x,y,r,color)
        self.scene.view_layers[0].update()
        mesh=bpy.data.meshes.new_from_object(curve.evaluated_get(bpy.context.evaluated_depsgraph_get()))
        obj=self.link(name+' mesh',mesh);obj.matrix_world=curve.matrix_world.copy()
        bpy.data.objects.remove(curve,do_unlink=True);obj.name=name
        return obj

    def import_meshes(self, filename):
        before = set(self.scene.objects)
        root = Path(self.job['style']['asset_root'])
        bpy.ops.import_scene.gltf(filepath=str(root/filename))
        imported = list(set(self.scene.objects)-before)
        meshes = [o for o in imported if o.type=='MESH']
        return imported, meshes

    def build_wheel(self):
        imported, meshes = self.import_meshes('wheel_of_brisbane_ferris_wheel_low-poly_free.glb')
        def ground(o):
            while o:
                if 'ground' in o.name.lower(): return True
                o=o.parent
            return False
        subjects = [o for o in meshes if not ground(o)]
        self.scene.frame_set(1)
        points = [o.matrix_world@Vector(v) for o in subjects for v in o.bound_box]
        lo=Vector([min(v[i] for v in points) for i in range(3)])
        hi=Vector([max(v[i] for v in points) for i in range(3)])
        norm = Matrix.Translation((-4,0,0)) @ Matrix.Rotation(-math.pi/2,4,'X') @ Matrix.Scale(8/max(hi-lo),4) @ Matrix.Translation(-(lo+hi)/2)
        for f in range(self.job['duration_frames']):
            source = 1+(f/self.job['canonical_fps']*60)%1499
            self.scene.frame_set(int(source), subframe=source-int(source))
            self.scene.view_layers[0].update()
            self.wheel_cache.append([norm@o.matrix_world.copy() for o in subjects])
        for o in imported: o.animation_data_clear()
        for o in subjects:
            o.parent=None;o.rotation_mode='XYZ'
        for o in imported:
            if o not in subjects: bpy.data.objects.remove(o,do_unlink=True)
        self.wheel_meshes=subjects
        for o,m in zip(subjects,self.wheel_cache[0]): o.matrix_world=m
        self.wheel_cabin=next(o for o in subjects if o.name.startswith('Pla_k52m5y__'))
        self.cabin_direction=self.path('CabinDirection',[(0,-.23,.05),(0,.42,.05)],GOLD,.055)
        self.cabin_direction.parent=self.wheel_cabin
        self.cabin_direction.matrix_parent_inverse=self.wheel_cabin.matrix_world.inverted()
        self.wheel_bridge=self.ring('WheelHandoffRing',0,0,3.3,(.82,.82,.78))
        self.wheel_bridge.location=(-4,.111,0)
        self.wheel_bridge_dot=self.marker('WheelHandoffDot',(0,0),GOLD,.226)
        self.scene.frame_set(1)

    def build_earth(self):
        imported, meshes = self.import_meshes('earth.glb')
        self.scene.view_layers[0].update()
        pts=[o.matrix_world@Vector(v) for o in meshes for v in o.bound_box]
        lo=Vector([min(v[i] for v in pts) for i in range(3)])
        hi=Vector([max(v[i] for v in pts) for i in range(3)])
        norm=Matrix.Rotation(-math.pi/2,4,'X')@Matrix.Scale(6/max(hi-lo),4)@Matrix.Translation(-(lo+hi)/2)
        self.earth_tilt=Matrix.Rotation(math.radians(30),4,'X')
        self.earth_origin=Vector((-4,0,0))
        self.earth_meshes=[(o,norm@o.matrix_world.copy()) for o in meshes]
        for o,m in self.earth_meshes:
            o.parent=None;o.rotation_mode='XYZ';o.animation_data_clear();o.matrix_world=Matrix.Translation((-4,0,0))@m
            o.name='Earth'
        for o in imported:
            if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
        self.axis=self.path('EarthAxis',[self.earth_origin+self.earth_tilt@Vector((0,-4.2,0)),self.earth_origin+self.earth_tilt@Vector((0,4.2,0))],GOLD,.045)
        self.local_axis=self.path('LocalVertical',[(-4,3,.1),(-4,4,.1)],CYAN,.065)
        self.air=self.link('AirParcel',None)
        ring=self.ring('AirParcelRing',0,0,.55,PINK);ring.parent=self.air
        heading=self.marker('AirHeading',(.55,0),GOLD,.13)
        heading.parent=self.air;heading.location=(.55,0,.25)
        spoke=self.path('AirHeadingSpoke',[(0,0,.25),(.55,0,.25)],PINK,.04)
        spoke.parent=self.air

    def build_flow(self):
        self.flow=self.path('FlowRibbon',[(-9+i/18,1.5*math.cos((-3+i/18)*math.pi/5),0) for i in range(181)],CYAN,.09)
        self.dots=[self.marker('FlowParcel%02d'%i,(0,0),GOLD) for i in range(16)]
        self.neg=self.link('NegativeRotor',None); self.neg.location=(-6,1.5,.2)
        self.pos=self.link('PositiveRotor',None); self.pos.location=(-1,-1.5,.2)
        for rotor,prefix,color in [(self.neg,'NegativeRotor',PINK),(self.pos,'PositiveRotor',CYAN)]:
            ring=self.ring(prefix+'Ring',0,0,.85,color);ring.parent=rotor
            dot=self.marker(prefix+'Dot',(.85,0),color,.17);dot.parent=rotor
        self.south=self.arrow('SouthVelocity',(-4.7,1.5,.4),(-4.7,-.2,.4),PINK)
        self.north=self.arrow('NorthVelocity',(.3,-1.5,.4),(.3,.2,.4),CYAN)
        self.latitude=self.path('InitialLatitude',[(-9,0,-.1),(1,0,-.1)],INK,.02)
        self.parcel=self.link('DisplacedParcel',None)
        ring=self.ring('ParcelRing',0,0,1.0,GOLD);ring.parent=self.parcel
        dot=self.marker('ParcelHeading',(1.0,0),GOLD);dot.parent=self.parcel
        self.comparison_start=self.link('ComparisonStart',None)
        self.comparison_north=self.link('ComparisonNorth',None)
        for parent,prefix in [(self.comparison_start,'StartComparison'),(self.comparison_north,'NorthComparison')]:
            ring=self.ring(prefix+'Ring',0,0,1,GOLD);ring.parent=parent
            dot=self.marker(prefix+'Heading',(1,0),GOLD);dot.parent=parent

    def build(self):
        numbers={b['controller_options']['scene_number'] for b in self.job['timeline']}
        self.group('flow',self.build_flow)
        if numbers & {5,6}:self.group('wheel',self.build_wheel)
        if numbers & set(range(6,13)):self.group('earth',self.build_earth)
        self.labels={}
        for n in sorted(numbers):
            def label(n=n):
                a,b=LABELS[n]
                self.labels[n]=[self.text(a,7.0,2.2 if n==9 else 1.4,1.56),self.text(b,7.0,-1.4 if n==9 else -.7,1.30)]
            self.group('label'+str(n),label)
        self.bar_f=self.rect('PlanetaryContribution',6,-3.6,3,.27,CYAN)
        self.bar_z=self.rect('RelativeContribution',6,-4.6,3,.27,PINK)
        self.bar_labels=[self.text('f',3.2,-3.85,.9,CYAN),self.text('ζ',3.2,-4.85,.9,PINK)]
        self.direction=VorticityDirection(self)
        self.track=list(self.scene.objects)

    def set_earth_pose(self,pose):
        self.earth_pose=pose
        self.earth_tilt=Matrix.Rotation(math.radians(30),4,'X')
        rotation=self.earth_tilt@Matrix.Rotation(pose['physical_angle'],4,'Y')
        for o,m in self.earth_meshes:
            o.matrix_world=Matrix.Translation(self.earth_origin)@rotation@m
        phi=pose['latitude']
        direction=rotation@Vector((math.cos(phi),math.sin(phi),0))
        endpoint=self.earth_origin+3.12*direction
        for p,v in zip(self.axis.data.splines[0].points,
                       [self.earth_origin+self.earth_tilt@Vector((0,y,0)) for y in (-4.2,4.2)]):p.co=(*v,1)
        self.axis['animate_points']=True
        for p,v in zip(self.local_axis.data.splines[0].points,[self.earth_origin+3*direction,endpoint+direction]):p.co=(*v,1)
        self.local_axis['animate_points']=True
        self.air.matrix_world=(Matrix.Translation(endpoint)@rotation
                              @Matrix.Rotation(phi-math.pi/2,4,'Z')
                              @Matrix.Rotation(-math.pi/2,4,'X'))

    def sample(self,frame):
        self.direction.begin()
        entry=self.job['canonical_state_cache'][frame]
        beat=max((b for b in self.job['timeline'] if b['beat_id'] in entry['active_beat_ids']),key=lambda b:b.get('priority',0))
        n=beat['controller_options']['scene_number']; t=frame/self.job['canonical_fps']
        q=ease((frame-beat['start_frame'])/max(1,beat['end_frame']-beat['start_frame']-1))
        family='wheel' if n in (5,6) else 'earth' if 7<=n<=12 else 'flow'
        for key,objects in self.groups.items():
            for o in objects:o.hide_render=o.hide_viewport=key not in (family,'label'+str(n))
        self.camera.location=(0,0,25);self.camera.rotation_euler=(0,0,0)
        profile=self.job.get('variant_profile',{}).get('camera_profile','base')
        self.camera.data.ortho_scale={'base':24,'wide':26,'close':23.5,'restrained':24.6}.get(profile,24)
        if family=='wheel':
            for o,m in zip(self.wheel_meshes,self.wheel_cache[frame]):o.matrix_world=m
            # A world-upright marker follows the cabin without inheriting scale.
            self.cabin_direction.parent=None
            self.cabin_direction.location=self.wheel_cabin.matrix_world.translation+Vector((0,0,.25))
        elif family=='earth':
            pose=earth_pose(frame,self.job['timeline'],self.job['canonical_fps'])
            self.set_earth_pose(pose)
        else:
            for i,o in enumerate(self.dots):
                x=-9+(i*.625+t*.75)%10
                o.location=(x,1.5*math.cos((x+6)*math.pi/5),.25)
            self.neg.rotation_euler.z=-t*.6;self.pos.rotation_euler.z=t*.6
            for o in [self.neg,*self.neg.children,self.pos,*self.pos.children]:o.hide_render=o.hide_viewport=n not in (3,4,16,17,18,19)
            for o in self.south:o.hide_render=o.hide_viewport=n not in (17,18,19)
            for o in self.north:o.hide_render=o.hide_viewport=n not in (18,19)
            for o in [self.latitude,self.parcel,*self.parcel.children]:o.hide_render=o.hide_viewport=n not in (13,14,15)
            for o in [self.flow,*self.dots]:o.hide_render=o.hide_viewport=n in (13,14,15)
            latitude=40+(20*q if n==14 else -20*q if n==15 else 0)
            self.parcel.location=(-4,(latitude-40)/10,.2)
            # Rotation accumulates with the growing relative-vorticity anomaly.
            sign=-1 if n==14 else 1 if n==15 else 0
            self.parcel.rotation_euler.z=sign*math.tau*q*q
        bars=n in (9,12,13,14,15)
        self.bar_f.hide_render=self.bar_z.hide_render=not bars
        self.bar_f.hide_viewport=self.bar_z.hide_viewport=not bars
        for o in self.bar_labels:o.hide_render=o.hide_viewport=not bars
        if n==12:
            self.bar_z.hide_render=self.bar_z.hide_viewport=True
            self.bar_labels[1].hide_render=self.bar_labels[1].hide_viewport=True
        f,z=contributions(n,q)
        reveal=q if n==13 else 1
        self.bar_f.scale.x=max(.001,f/2*reveal);self.bar_z.scale.x=max(.001,abs(z)/2)
        self.bar_f.location.x=6+1.5*f/2*reveal
        self.bar_z.location.x=6+(1.5 if z>=0 else -1.5)*abs(z)/2
        progress=(frame-beat['start_frame'])/max(1,beat['end_frame']-beat['start_frame']-1)
        self.scene.view_layers[0].update()
        self.direction.apply(n,progress,t,frame)
        return entry,self.track

    def bake(self):
        for frame in range(self.job['duration_frames']):
            _,objects=self.sample(frame)
            for obj in objects:
                for prop in ('location','rotation_euler','scale','hide_render','hide_viewport'):
                    obj.keyframe_insert(data_path=prop,frame=frame+1)
                if obj.get('animate_points'):
                    for p in obj.data.splines[0].points:p.keyframe_insert(data_path='co',frame=frame+1)
                if obj.get('animate_curve_reveal'):
                    obj.data.keyframe_insert(data_path='bevel_factor_end',frame=frame+1)
                for socket in animated_sockets(obj):socket.keyframe_insert(data_path='default_value',frame=frame+1)
            self.direction.bake(frame+1)
            self.camera.data.keyframe_insert(data_path='ortho_scale',frame=frame+1)
        self.scene.frame_set(1);self.font.pack();bpy.ops.file.pack_all()

    def extra_state(self):
        return {'visible':[o.name for o in self.track if not o.hide_render],
                'earth_observer':getattr(self,'earth_pose',None),
                'direction':self.direction.state}
