"""Explicit sockets allow both editable Blender keyframes and render attestations."""
import bpy


def fade_material(obj, material_index=0):
    mat=obj.data.materials[material_index].copy();obj.data.materials[material_index]=mat
    mat.surface_render_method='BLENDED'
    n=mat.node_tree.nodes;l=mat.node_tree.links
    out=next(node for node in n if node.type=='OUTPUT_MATERIAL')
    source=out.inputs['Surface'].links[0].from_socket
    clear=n.new('ShaderNodeBsdfTransparent')
    mix=n.new('ShaderNodeMixShader');mix.name='Animated opacity'
    l.new(clear.outputs[0],mix.inputs[1]);l.new(source,mix.inputs[2]);l.new(mix.outputs[0],out.inputs['Surface'])
    mix.inputs[0].default_value=1
    if material_index==0:
        obj['animated_socket']='Animated opacity';obj['animated_input']=0
    else:
        obj['additional_animated_materials']=list(obj.get('additional_animated_materials',[]))+[material_index]
    return mix.inputs[0]


def animated_socket(obj):
    if 'animated_socket' in obj:
        return obj.data.materials[0].node_tree.nodes[obj['animated_socket']].inputs[int(obj['animated_input'])]
    return None


def animated_sockets(obj):
    result=[]
    socket=animated_socket(obj)
    if socket is not None:result.append(socket)
    for index in obj.get('additional_animated_materials',[]):
        result.append(obj.data.materials[index].node_tree.nodes['Animated opacity'].inputs[0])
    return result


def fade_all_materials(obj):
    return [fade_material(obj,index) for index in range(len(obj.data.materials))]
