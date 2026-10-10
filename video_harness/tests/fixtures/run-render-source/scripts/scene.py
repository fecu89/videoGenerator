"""Small engine contract fixture; physical dimensions are Blender world units."""
import math
import bpy
from mathutils import Vector
from render_runtime.blender_base import BlenderGalleryBase


class Gallery(BlenderGalleryBase):
    def build(self):
        self.scene.eevee.taa_render_samples = self.job.get('physics', {}).get('samples', 8)
        self.camera.location = (17, -23, 22)
        self.camera.rotation_euler = (Vector((0, 0, 0)) - self.camera.location).to_track_quat('-Z', 'Y').to_euler()
        self.camera.data.ortho_scale = 35
        surface = bpy.data.materials.new('Matte')
        surface.diffuse_color = (.6, .68, .8, 1)
        bpy.ops.mesh.primitive_plane_add(size=36)
        bpy.context.object.name = 'Ground'
        bpy.context.object.data.materials.append(surface)
        for y in range(6):
            for x in range(6):
                bpy.ops.mesh.primitive_cube_add(size=1.2, location=((x-2.5)*3, (y-2.5)*3, .9))
                cube = bpy.context.object
                cube.name = f'Block-{x}-{y}'
                cube.scale.z = 1.5
                cube.data.materials.append(surface)
                self.animated.append(cube)
        lights = self.job.get('physics', {}).get('lights', 4)
        for index in range(lights):
            angle = index * math.tau / lights
            light = bpy.data.lights.new(f'Light-{index}', 'AREA')
            light.energy = 16000 / lights
            light.size = .4
            obj = self.link(light.name, light)
            obj.location = (12*math.cos(angle), 12*math.sin(angle), 10)
            obj.rotation_euler = (-obj.location).to_track_quat('-Z', 'Y').to_euler()

    def sample(self, canonical_frame):
        for index, obj in enumerate(self.animated):
            obj.rotation_euler.z = canonical_frame * .025 + index * .1
        return super().sample(canonical_frame)
