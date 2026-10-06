"""Qualitative lunar-eclipse transmission: reddening plus refraction, not dispersion.

A single narrow beam loses short wavelengths along its passage through the limb.
Sparse blue packets depict scattering into different directions, not spectral rays.
"""
import math
import bpy
from mathutils import Vector
try:
    from .animated_materials import fade_material
except ImportError:
    from animated_materials import fade_material


def smooth(x):
    x=max(0,min(1,x));return x*x*(3-2*x)


def beam_point(u):
    if u<=.3:
        t=u/.3
        return Vector((-.5+1.9*t,2.52-.28*t*t,.24))
    x=1.4+(8.25-1.4)*(u-.3)/.7
    return Vector((x,2.24-(.56/1.9)*(x-1.4),.24))


def build_atmospheric_light(g):
    cols=97;vertices=[];colors=[];progress=[]
    for side in (-1,0,1):
        for j in range(cols):
            u=j/(cols-1);p=beam_point(u)
            # Every cross-section has one color. No spatial wavelength separation.
            p.y+=side*.044;vertices.append(tuple(p))
            depth=smooth(u/.3)
            color=(.93+.07*depth,.94*math.exp(-3.25*depth),math.exp(-6.2*depth),1)
            colors.append(color);progress.append(u)
    faces=[]
    for row in range(2):
        for j in range(cols-1):
            a=row*cols+j;faces.append((a,a+1,a+cols+1,a+cols))
    mesh=bpy.data.meshes.new('Reddened transmitted sunlight');mesh.from_pydata(vertices,[],faces);mesh.update()
    obj=g.link('Reddened transmitted sunlight',mesh);obj['qa_path_indices']=list(range(cols))
    obj['optical_process']='selective scattering reduces blue; single refracted transmitted beam'
    ca=mesh.color_attributes.new(name='transmitted_color',type='FLOAT_COLOR',domain='POINT')
    ua=mesh.attributes.new(name='beam_u',type='FLOAT',domain='POINT')
    for item,color in zip(ca.data,colors):item.color=color
    for item,u in zip(ua.data,progress):item.value=u
    mat=bpy.data.materials.new('White to red atmospheric transmission');mat.use_nodes=True;mat.surface_render_method='BLENDED'
    n=mat.node_tree.nodes;l=mat.node_tree.links;n.clear()
    color=n.new('ShaderNodeAttribute');color.attribute_name='transmitted_color'
    coord=n.new('ShaderNodeAttribute');coord.attribute_name='beam_u'
    reveal=n.new('ShaderNodeMath');reveal.operation='LESS_THAN';l.new(coord.outputs['Fac'],reveal.inputs[0])
    emit=n.new('ShaderNodeEmission');l.new(color.outputs['Color'],emit.inputs['Color'])
    transparent=n.new('ShaderNodeBsdfTransparent');mix=n.new('ShaderNodeMixShader')
    l.new(reveal.outputs[0],mix.inputs[0]);l.new(transparent.outputs[0],mix.inputs[1]);l.new(emit.outputs[0],mix.inputs[2])
    out=n.new('ShaderNodeOutputMaterial');l.new(mix.outputs[0],out.inputs[0]);mesh.materials.append(mat)
    g.node_sockets.append(reveal.inputs[1])
    packets=[]
    directions=[(-.65,.65,.3),(.08,.95,.3),(.75,.62,.22),(-.8,-.12,.6),(.4,-.4,.8),(.65,.2,.7)]
    for i,d in enumerate(directions):
        direction=Vector(d).normalized();origin=beam_point(.035+.035*i)
        streak=g.line('Blue scattered light packet '+str(i+1),[(0,0,0),tuple(direction*.16)],(.07,.40,1),.024)
        opacity=fade_material(streak);g.node_sockets.append(opacity)
        packets.append((streak,opacity,origin,direction,i))
    return obj,reveal.inputs[1],packets


def animate_scattering(packets,t):
    for obj,opacity,origin,direction,index in packets:
        age=t-(89.6+.23*index)
        phase=(age%2.25)/2.25
        obj.location=origin+direction*(.06+1.25*phase)
        visible=age>=0 and t<97.6
        opacity.default_value=(1-smooth((phase-.4)/.6))*.85 if visible else 0
        obj.hide_render=obj.hide_viewport=not visible or opacity.default_value<.015
