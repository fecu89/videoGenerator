"""Neutral bpy scene primitives. Video-specific animation belongs in run scripts."""
import math
from pathlib import Path
import bpy
from callout import CalloutLayer, labels_from_job

INK = (0.72, 0.84, 1.0)
CYAN = (0.07, 0.66, 0.9)


class BlenderGalleryBase:
    def __init__(self, job):
        self.job = job
        self.scene = bpy.data.scenes.new(job['sequence_id'])
        if bpy.context.window:
            bpy.context.window.scene = self.scene
        self.materials = {}
        self.objects = {}
        self.animated = []
        font = Path('/System/Library/Fonts/Supplemental/AppleGothic.ttf')
        self.font = bpy.data.fonts.load(str(font)) if font.is_file() else bpy.data.fonts.get('Bfont')
        self.configure()
        self.build()
        self.callouts = CalloutLayer(self)
        self.callouts.bind(labels_from_job(job), {**{obj.name: obj for obj in self.scene.objects}, **self.objects})

    def configure(self):
        scene = self.scene
        scene.render.engine = 'BLENDER_EEVEE'
        scene.render.resolution_x = self.job['output']['width']
        scene.render.resolution_y = self.job['output']['height']
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        scene.render.fps = self.job['canonical_fps']
        scene.frame_start = 1
        scene.frame_end = self.job['duration_frames']
        scene.world = bpy.data.worlds.new('World')
        scene.world.color = (0.04, 0.04, 0.04)
        camera = bpy.data.cameras.new('Camera')
        camera.type = 'ORTHO'
        camera.ortho_scale = 28.444
        self.camera = self.link('Camera', camera)
        self.camera.location = (0, 0, 25)
        scene.camera = self.camera

    def build(self):
        pass

    def sample(self, canonical_frame):
        return self.job['canonical_state_cache'][canonical_frame], self.animated

    def bake(self):
        # A run can override this to bake editable keyframes. sample() must still
        # evaluate an arbitrary canonical frame deterministically for previews.
        self.sample(0)

    def material(self,color,strength=1):
        key=(*color,strength)
        if key in self.materials:return self.materials[key]
        mat=bpy.data.materials.new('Spectrum emission'); mat.use_nodes=True
        nodes=mat.node_tree.nodes; nodes.clear()
        emit=nodes.new('ShaderNodeEmission'); emit.inputs['Color'].default_value=(*color,1)
        emit.inputs['Strength'].default_value=strength
        out=nodes.new('ShaderNodeOutputMaterial'); mat.node_tree.links.new(emit.outputs[0],out.inputs['Surface'])
        self.materials[key]=mat
        return mat

    def link(self,name,data):
        obj=bpy.data.objects.new(name,data); self.scene.collection.objects.link(obj)
        return self.register_object(name, obj)

    def register_object(self, name, obj):
        """Keep authored IDs stable even when a desktop scene adds .001 suffixes."""
        self.objects[name] = obj
        return obj

    def rect(self,name,x,y,w,h,color,z=0):
        mesh=bpy.data.meshes.new(name)
        mesh.from_pydata([(-w/2,-h/2,0),(w/2,-h/2,0),(w/2,h/2,0),(-w/2,h/2,0)],[],[(0,1,2,3)])
        obj=self.link(name,mesh); obj.location=(x,y,z); mesh.materials.append(self.material(color))
        return obj

    def text(self,body,x,y,size=.55,color=INK,align='CENTER'):
        curve=bpy.data.curves.new(body,'FONT'); curve.body=body; curve.font=self.font
        curve.align_x=align; curve.size=size*1.12
        obj=self.link(body,curve); obj.location=(x,y,1.2); curve.materials.append(self.material(color))
        return obj

    def path(self,name,points,color=CYAN,radius=.025):
        curve=bpy.data.curves.new(name,'CURVE');curve.dimensions='3D';curve.bevel_depth=radius;curve.bevel_resolution=2
        spline=curve.splines.new('POLY');spline.points.add(len(points)-1)
        for p,xyz in zip(spline.points,points):p.co=(*xyz,1)
        obj=self.link(name,curve);curve.materials.append(self.material(color));return obj

    def ring(self,name,x,y,r,color=CYAN):
        return self.path(name,[(x+r*math.cos(a*math.tau/96),y+r*math.sin(a*math.tau/96),.25) for a in range(97)],color,.035)
