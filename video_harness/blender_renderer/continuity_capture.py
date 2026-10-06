"""Capture evaluated Blender transforms, including camera roll, for continuity QA."""
import math
from mathutils import Vector


def capture_continuity(scene, camera):
    def pose(obj):
        location, rotation, scale = obj.matrix_world.decompose()
        return {'position': list(location), 'rotation': list(rotation), 'scale': list(scale)}
    actors = {}
    for obj in scene.objects:
        if obj.type not in {'MESH', 'CURVE', 'EMPTY', 'FONT'}:
            continue
        row = pose(obj)
        row['kind'] = obj.type
        row['visible'] = not obj.hide_render
        row['radius'] = max(.000001, max(obj.dimensions) / 2)
        if obj.type == 'EMPTY':
            center=obj.matrix_world.translation
            row['radius']=max([row['radius'], *[
                (child.matrix_world @ Vector(corner)-center).length
                for child in obj.children_recursive if child.type in {'MESH','CURVE'}
                for corner in child.bound_box]])
        actors[obj.name] = row
    cam = pose(camera)
    cam.update(projection=camera.data.type, lens=float(camera.data.lens),
               ortho_scale=float(camera.data.ortho_scale),
               sensor_width=float(camera.data.sensor_width))
    paths = {}
    for obj in scene.objects:
        if obj.type == 'CURVE' and obj.data.splines:
            spline=obj.data.splines[0]
            points=spline.bezier_points if spline.type=='BEZIER' else spline.points
            paths[obj.name]=[list(obj.matrix_world @ Vector(point.co[:3])) for point in points]
        indices = obj.get('qa_path_indices')
        if obj.type == 'MESH' and indices:
            paths[obj.name] = [list(obj.matrix_world @ obj.data.vertices[int(i)].co) for i in indices]
            # A row-major band exposes its middle and final wavelength too.
            width=len(indices)
            if list(indices)==list(range(width)) and len(obj.data.vertices)%width==0:
                rows=len(obj.data.vertices)//width
                for label,row in [('middle',rows//2),('last',rows-1)]:
                    paths[obj.name+'/'+label]=[list(obj.matrix_world @ obj.data.vertices[row*width+i].co) for i in range(width)]
    return {'camera': cam, 'actors': actors, 'paths': paths}
