"""One continuous wavelength band, bending toward Earth at the upper limb."""
import math
import bpy


def build_refracted_band(g):
    colors=[(1,.035,.012),(1,.23,.015),(1,.78,.02),(.12,.9,.055),(.02,.7,.9),(.035,.12,1),(.48,.035,1)]
    rows,cols=49,65
    vertices=[];rgba=[];progress=[]
    def smooth(x):
        x=max(0,min(1,x));return x*x*(3-2*x)
    for i in range(rows):
        wavelength=i/(rows-1)
        endx=6+2.25*(1-smooth((wavelength-.1)/.18))
        ex,ey=1.4,2.24-.33*wavelength
        slope=(ey-2.52)/.95
        c=wavelength*6;k=min(5,int(c));color=[colors[k][j]*(1-(c-k))+colors[k+1][j]*(c-k) for j in range(3)]
        for j in range(cols):
            u=j/(cols-1)
            if u<=.3:
                t=u/.3
                x=(1-t)**2*(-.5)+2*(1-t)*t*.45+t*t*ex
                y=(1-t)**2*2.52+2*(1-t)*t*2.52+t*t*ey
            else:
                x=ex+(endx-ex)*(u-.3)/.7;y=ey+slope*(x-ex)
            y+=.045*(1-2*wavelength)
            vertices.append((x,y,.22))
            white=1-smooth(u/.12)
            alpha=1-smooth((u-.72)/.28)*smooth((wavelength-.08)/.12)
            rgba.append(tuple(white+(1-white)*v for v in color)+(alpha,));progress.append(u)
    faces=[]
    for i in range(rows-1):
        for j in range(cols-1):
            a=i*cols+j;faces.append((a,a+1,a+1+cols,a+cols))
    mesh=bpy.data.meshes.new('Continuous refracted spectrum');mesh.from_pydata(vertices,[],faces);mesh.update()
    obj=g.link('Continuous refracted spectrum',mesh)
    obj['qa_path_indices']=list(range(cols))
    ca=mesh.color_attributes.new(name='wavelength',type='FLOAT_COLOR',domain='POINT')
    ua=mesh.attributes.new(name='beam_u',type='FLOAT',domain='POINT')
    for item,color in zip(ca.data,rgba):item.color=color
    for item,value in zip(ua.data,progress):item.value=value
    mat=bpy.data.materials.new('Continuous wavelength gradient');mat.use_nodes=True;mat.surface_render_method='BLENDED'
    nodes=mat.node_tree.nodes;links=mat.node_tree.links;nodes.clear()
    color=nodes.new('ShaderNodeAttribute');color.attribute_name='wavelength'
    u=nodes.new('ShaderNodeAttribute');u.attribute_name='beam_u'
    reveal=nodes.new('ShaderNodeMath');reveal.operation='LESS_THAN';links.new(u.outputs['Fac'],reveal.inputs[0])
    opacity=nodes.new('ShaderNodeMath');opacity.operation='MULTIPLY';links.new(reveal.outputs[0],opacity.inputs[0]);links.new(color.outputs['Alpha'],opacity.inputs[1])
    emit=nodes.new('ShaderNodeEmission');links.new(color.outputs['Color'],emit.inputs['Color'])
    transparent=nodes.new('ShaderNodeBsdfTransparent');mix=nodes.new('ShaderNodeMixShader')
    links.new(opacity.outputs[0],mix.inputs[0]);links.new(transparent.outputs[0],mix.inputs[1]);links.new(emit.outputs[0],mix.inputs[2])
    out=nodes.new('ShaderNodeOutputMaterial');links.new(mix.outputs[0],out.inputs[0]);mesh.materials.append(mat)
    g.node_sockets.append(reveal.inputs[1]);return obj,reveal.inputs[1]
