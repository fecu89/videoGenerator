"""Perspective pullback: slow departure, fast stellar parallax, Earth foreground."""
import math
import random
from pathlib import Path

import bpy

try:
    from .flight_path import flight_distance, flight_speed
    from .spectra import smooth
except ImportError:
    from flight_path import flight_distance, flight_speed
    from spectra import smooth


class DistanceFlight:
    def __init__(self, gallery, start_frame, profile="original"):
        self.profile=profile
        self.rapid=profile=="rapid"
        self.g=gallery
        self.origin=10000.
        camera=bpy.data.cameras.new('Distance flight perspective')
        camera.type='PERSP';camera.lens=35;camera.sensor_width=36
        camera.clip_start=.1;camera.clip_end=12000
        self.camera=gallery.link('Distance flight camera',camera)
        marker=gallery.scene.timeline_markers.new('Flight behind Earth',frame=start_frame+1)
        marker.camera=self.camera
        gallery.scene.world.use_nodes=True
        gallery.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.005,.012,.027,1)
        self.star=gallery.star('Flight target white star',self.origin,0,4.2,(.83,.9,1))
        self.star.location.z=0
        self.star_halo=bpy.data.objects.get('Flight target white star glow')
        rng=random.Random(20260916)
        # Distant stars are camera children beyond the target star and Earth.
        for i in range(190):
            x=rng.uniform(-2050,2050);y=rng.uniform(-1150,1150)
            size=rng.uniform(.7,2.7)
            shade=rng.uniform(.12,.48)
            obj=gallery.rect('Distant sky point',0,0,size,size,(shade*.75,shade*.86,shade),0)
            obj.parent=self.camera;obj.location=(x,y,-4000)
        self.passers=[]
        for i in range(360 if self.rapid else 150):
            angle=rng.random()*math.tau
            radius=rng.uniform(8,240) if self.rapid else rng.uniform(9,90)
            x=radius*math.cos(angle);y=radius*math.sin(angle)
            z=rng.uniform(42,2290)
            obj=gallery.rect('Passing starlight',self.origin+x,y,1,1,(.62,.78,1),z)
            self.passers.append((obj,x,y,z,rng.uniform(.025,.07)))
        self.build_earth()
        # Camera-space labels appear only once the camera arrives behind Earth.
        self.label=gallery.text('지구',0,0,.21,(.2,.73,1))
        self.label.parent=self.camera;self.label.location=(-2.65,-2.4,-10)

    def build_earth(self):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=128,ring_count=96,radius=20,location=(self.origin-30,-18,2320))
        self.earth=bpy.context.object;self.earth.name='Earth foreground'
        for face in self.earth.data.polygons:face.use_smooth=True
        self.earth.rotation_euler=(-math.pi/2,0,-.35)
        mat=bpy.data.materials.new('Earth ocean land and clouds');mat.use_nodes=True
        n=mat.node_tree.nodes;n.clear();l=mat.node_tree.links
        tex=n.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(Path(__file__).parent/'assets/earth-atmos-r160.jpg'),check_existing=True);tex.image.pack()
        geom=n.new('ShaderNodeNewGeometry')
        dot=n.new('ShaderNodeVectorMath');dot.operation='DOT_PRODUCT';dot.inputs[1].default_value=(.78,.50,-.37)
        maximum=n.new('ShaderNodeMath');maximum.operation='MAXIMUM';maximum.inputs[1].default_value=0
        light=n.new('ShaderNodeMath');light.operation='MULTIPLY_ADD';light.inputs[1].default_value=1.1;light.inputs[2].default_value=.12
        emission=n.new('ShaderNodeEmission');out=n.new('ShaderNodeOutputMaterial')
        l.new(geom.outputs['Normal'],dot.inputs[0]);l.new(dot.outputs['Value'],maximum.inputs[0]);l.new(maximum.outputs[0],light.inputs[0])
        l.new(tex.outputs['Color'],emission.inputs['Color']);l.new(light.outputs[0],emission.inputs['Strength']);l.new(emission.outputs[0],out.inputs['Surface'])
        self.earth.data.materials.append(mat)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96,ring_count=64,radius=20.22,location=self.earth.location)
        self.atmosphere=bpy.context.object;self.atmosphere.name='Earth blue atmospheric rim'
        for face in self.atmosphere.data.polygons:face.use_smooth=True
        mat=bpy.data.materials.new('Atmospheric limb');mat.use_nodes=True;mat.surface_render_method='BLENDED'
        n=mat.node_tree.nodes;n.clear();l=mat.node_tree.links
        facing=n.new('ShaderNodeLayerWeight');power=n.new('ShaderNodeMath');power.operation='POWER';power.inputs[1].default_value=5
        strength=n.new('ShaderNodeMath');strength.operation='MULTIPLY';strength.inputs[1].default_value=.6
        clear=n.new('ShaderNodeBsdfTransparent');emit=n.new('ShaderNodeEmission');emit.inputs['Color'].default_value=(.03,.35,1,1)
        mix=n.new('ShaderNodeMixShader');out=n.new('ShaderNodeOutputMaterial')
        l.new(facing.outputs['Facing'],power.inputs[0]);l.new(power.outputs[0],strength.inputs[0]);l.new(strength.outputs[0],mix.inputs[0])
        l.new(clear.outputs[0],mix.inputs[1]);l.new(emit.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],out.inputs['Surface']);self.atmosphere.data.materials.append(mat)

    def sample(self, p, time):
        z=flight_distance(p,self.profile)
        cx=3.8*(1-smooth(p/(.12 if self.rapid else .22)))-6*smooth((p-(.38 if self.rapid else .65))/(.27))
        cy=-5*smooth((p-(.38 if self.rapid else .65))/.27)
        self.camera.location=(self.origin+cx,cy,z)
        self.star.rotation_euler.y=.105*time
        tracked=[self.camera,self.star,self.earth,self.atmosphere,self.label]
        arrival=smooth((p-(.58 if self.rapid else .80))/.12)
        self.label.scale=(arrival,arrival,arrival)
        self.earth.rotation_euler.y=.10*smooth((p-.72)/.28)
        previous_z=flight_distance(max(0,p-(.045 if self.rapid else .013)),self.profile)
        for obj,x,y,sz,size in self.passers:
            depth=z-sz;old_depth=previous_z-sz
            if depth<4 or abs((x-cx)/depth)>1.1 or abs((y-cy)/depth)>.7:
                obj.scale=(0,0,0)
            else:
                ratio=depth/max(1,old_depth)
                dx=(x-cx)*(ratio-1);dy=(y-cy)*(ratio-1)
                length=min(math.hypot(dx,dy),depth*(.60 if self.rapid else .26))
                angle=math.atan2(dy,dx)
                fade=1-smooth((p-(.40 if self.rapid else .72))/(.19 if self.rapid else .18))
                obj.location=(self.origin+x+math.cos(angle)*length/2,y+math.sin(angle)*length/2,sz)
                obj.rotation_euler.z=angle
                obj.scale=(max(size,length)*fade,max(size*.65,depth*(.0012 if self.rapid else .00065))*fade,1)
            tracked.append(obj)
        for obj,socket in getattr(self,"intro_labels",[]):
            socket.default_value=0
            tracked.append(obj)
        return tracked

    def add_intro_labels(self):
        try:
            from .animated_materials import fade_material
        except ImportError:
            from animated_materials import fade_material
        self.intro_labels=[]
        for body,x,y,size,color in [
            ('별의 표면 온도',2.08,1.33,.229,(.07,.66,.9)),
            ('10,000 K',2.08,.458,.604,(.72,.84,1)),
            ('어떻게 알았을까?',2.08,-.52,.292,(1,.55,.1))]:
            obj=self.g.text(body,0,0,size,color);obj.parent=self.camera;obj.location=(x,y,-10)
            self.intro_labels.append((obj,fade_material(obj)))

    def sample_intro(self, elapsed, time):
        try:
            from .opening_motion import opening_camera_z, opening_text_opacity
        except ImportError:
            from opening_motion import opening_camera_z, opening_text_opacity
        tracked=self.sample(0,time)
        self.camera.location.z=opening_camera_z(elapsed)
        for obj,socket in self.intro_labels:
            socket.default_value=opening_text_opacity(elapsed)
        return tracked
