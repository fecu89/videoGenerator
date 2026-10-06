"""Native camera match cuts: a traced sphere connects different teaching models.

Blue is the persistent tracked-object colour here. View-relative shading keeps
its appearance identical when scale and location change between demonstrations.
No image dissolve or replacement frame is used.
"""
import math
from mathutils import Vector
try:
    from .adiabatic_match_math import zoom_weight,match_distance
    from .animated_materials import fade_material
except ImportError:
    from adiabatic_match_math import zoom_weight,match_distance
    from animated_materials import fade_material


def prepare(g,config):
    ob=g.scene.objects[config['actor']]
    mat=g.surface('Tracked blue sphere',(.04,.33,1))
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    view=nodes.new('ShaderNodeLayerWeight')
    shade=nodes.new('ShaderNodeMath');shade.operation='MULTIPLY_ADD';shade.inputs[1].default_value=-.65;shade.inputs[2].default_value=1
    links.new(view.outputs['Facing'],shade.inputs[0])
    emission=nodes.new('ShaderNodeEmission');emission.inputs['Color'].default_value=(.04,.33,1,1)
    links.new(shade.outputs[0],emission.inputs['Strength'])
    out=next(n for n in nodes if n.type=='OUTPUT_MATERIAL');links.new(emission.outputs[0],out.inputs['Surface'])
    ob.data.materials[0]=mat
    g.match_actor=ob;g.match_alpha=fade_material(ob)
    g.camera.data.type='PERSP';g.camera.data.clip_start=.005


def apply(g,frame):
    config=g.job['timeline'][0]['controller_options'].get('sphere_match')
    if not config:return
    if not hasattr(g,'match_actor'):prepare(g,config)
    actor=g.match_actor
    # The parcel parent has translation only; use current authored transforms
    # without depending on a previously evaluated Blender frame.
    center=actor.location.copy()
    if actor.parent:center+=actor.parent.location
    base_alpha=g.gas_alpha.default_value if hasattr(g,'gas_alpha') else 1
    fps=g.job['canonical_fps']
    w=zoom_weight(frame,g.job['duration_frames'],config.get('entry_seconds',0)*fps,config.get('exit_seconds',0)*fps)
    g.match_alpha.default_value=base_alpha+(1-base_alpha)*w
    s=g.current
    target=Vector((s['focus_x'],s.get('focus_y',0),s['focus_z']))
    base=g.camera.location.copy();offset=base-target
    if not g.asset_mode:
        g.camera.data.lens=36*offset.length/s['camera_scale']
    lens=g.camera.data.lens
    distance=math.exp((1-w)*math.log(offset.length)+w*math.log(match_distance(config['radius'])))
    direction=(offset.normalized()*(1-w)+Vector((0,-1,0))*w).normalized()
    tracking=min(1,w*3);tracking=tracking*tracking*(3-2*tracking)
    aim=target.lerp(center,tracking)
    g.camera.location=aim+direction*distance
    g.camera.rotation_euler=(-direction).to_track_quat('-Z','Y').to_euler()
    g.camera.data.lens=lens+(85-lens)*w
