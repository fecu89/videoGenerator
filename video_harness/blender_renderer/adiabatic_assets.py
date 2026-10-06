"""Asset-based opening, balloon boundary microscope, and atmosphere ascent.

The atmospheric cylinder is an explanatory air column, not a solid container.
The imported balloon is the pressure probe; its rubber fades for the free-air
parcel explanation. Earth/column heights and microscopic scale are illustrative.
"""
import math,random
from pathlib import Path
import bpy
from mathutils import Vector,Matrix
try:
 from .animated_materials import fade_material, fade_all_materials
 from .adiabatic_math import state_at,sphere_particle,boundary_collision,smooth
except ImportError:
 from animated_materials import fade_material, fade_all_materials
 from adiabatic_math import state_at,sphere_particle,boundary_collision,smooth

ASSETS=Path(__file__).resolve().parents[2]/'assets'


def imported(g,file,name,size,select_material=None,rotate=None):
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(g.asset_dir/file))
    g.scene.view_layers[0].update()
    imported_objects=list(set(bpy.data.objects)-before)
    meshes=[o for o in imported_objects if o.type=='MESH' and (select_material is None or any(m and m.name.split('.')[0]==select_material for m in o.data.materials))]
    if not meshes:raise ValueError(f'asset selection empty: {file}/{select_material}')
    transforms={o:o.matrix_world.copy() for o in meshes}
    for o in meshes:
        o.parent=None;o.animation_data_clear();o.modifiers.clear()
        o.data=o.data.copy();o.data.transform(transforms[o]);o.matrix_world=Matrix.Identity(4)
        if rotate:o.data.transform(rotate)
    points=[v.co.copy() for o in meshes for v in o.data.vertices]
    lo=Vector([min(p[i] for p in points) for i in range(3)]);hi=Vector([max(p[i] for p in points) for i in range(3)])
    mid=(lo+hi)/2;factor=size/max(hi-lo)
    for o in meshes:o.data.transform(Matrix.Scale(factor,4)@Matrix.Translation(-mid))
    for o in imported_objects:
        if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:bpy.ops.object.join()
    obj=bpy.context.view_layer.objects.active;obj.name=name
    if file=='PET-bottle.glb':
        dec=obj.modifiers.new('Asset preview surface reduction','DECIMATE');dec.ratio=.12
        bpy.ops.object.modifier_apply(modifier=dec.name)
    for face in obj.data.polygons:face.use_smooth=True
    return obj


def opacity(obj):
    return fade_material(obj)


def balloon_cutaway(obj):
    """Retain a thin central XZ slice of the actual asset, not a hemisphere."""
    mat=obj.data.materials[0].copy();obj.data.materials[0]=mat;mat.use_nodes=True
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    out=next(n for n in nodes if n.type=='OUTPUT_MATERIAL');source=out.inputs['Surface'].links[0].from_socket
    coords=nodes.new('ShaderNodeTexCoord');xyz=nodes.new('ShaderNodeSeparateXYZ');links.new(coords.outputs['Generated'],xyz.inputs[0])
    center=nodes.new('ShaderNodeMath');center.operation='SUBTRACT';center.inputs[1].default_value=.5;links.new(xyz.outputs['Y'],center.inputs[0])
    absolute=nodes.new('ShaderNodeMath');absolute.operation='ABSOLUTE';links.new(center.outputs[0],absolute.inputs[0])
    front=nodes.new('ShaderNodeMath');front.operation='GREATER_THAN';front.inputs[1].default_value=.035;links.new(absolute.outputs[0],front.inputs[0])
    reveal=nodes.new('ShaderNodeValue');reveal.name='Cutaway reveal';reveal.outputs[0].default_value=0
    mul=nodes.new('ShaderNodeMath');mul.operation='MULTIPLY';links.new(front.outputs[0],mul.inputs[0]);links.new(reveal.outputs[0],mul.inputs[1])
    transparent=nodes.new('ShaderNodeBsdfTransparent');mix=nodes.new('ShaderNodeMixShader');links.new(mul.outputs[0],mix.inputs[0]);links.new(source,mix.inputs[1]);links.new(transparent.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs['Surface']);mat.surface_render_method='DITHERED'
    return reveal.outputs[0]


def section_outline(g,obj):
    """Trace the supplied mesh's central section so its cut edge stays visible."""
    points=set()
    for edge in obj.data.edges:
        a,b=(obj.data.vertices[i].co for i in edge.vertices)
        if (a.y<=0<b.y) or (b.y<=0<a.y):
            p=a+(b-a)*(-a.y/(b.y-a.y));points.add((round(p.x,5),0,round(p.z,5)))
    ordered=sorted(points,key=lambda p:math.atan2(p[2],p[0]))
    if len(ordered)<8:raise ValueError('balloon central section is missing')
    return g.path('balloon-section-edge',ordered+[ordered[0]],(.38,.23,.57),.035)


def build(g):
    g.asset_mode=True;g.objects=[];g.extra_sockets=[]
    g.asset_dir=Path(g.job['timeline'][0]['controller_options'].get('asset_root',ASSETS))
    g.gasmat=g.surface('Thermal particles red',(.95,.06,.025))
    g.coldmat=g.surface('Exterior air',(.08,.48,1.))
    g.darkmat=g.surface('Apparatus navy',(.03,.12,.22))
    g.camera.data.type='PERSP';g.camera.data.clip_start=.02;g.camera.data.clip_end=500
    g.scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.34,.63,.89,1)
    g.earth=None;g.asset_cloud=None;g.balloon_asset=None;g.bottle=None;g.column_objects=[];g.pressure_arrows=[];g.column_particles=[];g.outer=[];g.particles=[]
    g.boundary=[];g.surroundings=[]
    if g.env in ('sky','atmosphere','parcel'):
        g.landscape=imported(g,'nature_landscape.glb','asset-nature-landscape',40)
        g.landscape.location=(0,5,-1.2)
    if g.env in ('sky','parcel'):
        g.asset_cloud=imported(g,'cloud.glb','asset-cloud',6)
        g.cloud_sockets=fade_all_materials(g.asset_cloud);g.objects.append(g.asset_cloud)
    if g.env=='sky':
        g.parcel=g.link('asset-parcel',None);g.objects.append(g.parcel)
    else:
        g.balloon_asset=imported(g,'air_balloons.glb','asset-balloon',3.3,'redpurple',Matrix.Rotation(math.pi/2,4,'X'))
        balloon_cutaway(g.balloon_asset)
        g.balloon_alpha=opacity(g.balloon_asset);g.objects.append(g.balloon_asset)
        g.surface_radius=max(abs(v.co.x) for v in g.balloon_asset.data.vertices)
        g.reveal_socket=g.balloon_asset.data.materials[0].node_tree.nodes['Cutaway reveal'].outputs[0]
        g.extra_sockets.append(g.reveal_socket)
        g.slice_edge=section_outline(g,g.balloon_asset);g.slice_alpha=opacity(g.slice_edge);g.objects.append(g.slice_edge)
        g.parcel=g.link('asset-parcel',None);g.objects.append(g.parcel)
    if g.env=='sky':
        for ob in g.cage('expanding-air-boundary',1,(.08,.35,.55)):
            g.boundary.append((ob,opacity(ob)));g.objects.append(ob)
    for i in range(38):
        ob=g.sphere(f'molecule-{i:02}',.105,g.gasmat);g.particles.append(ob);g.objects.append(ob)
        ob.parent=g.parcel
    first=opacity(g.particles[0]);g.gasmat=g.particles[0].data.materials[0];g.gas_alpha=first
    for ob in g.particles[1:]:ob.data.materials[0]=g.gasmat
    if g.env=='balloon':
        g.bottle=imported(g,'PET-bottle.glb','asset-pet-bottle',4.1)
        # Keep supplied shape but remove its scanned package text/branding.
        mat=g.surface('Unlabelled PET plastic',(.10,.37,.52));g.bottle.data.materials.clear();g.bottle.data.materials.append(mat)
        for poly in g.bottle.data.polygons:poly.material_index=0
        g.bottle_alpha=opacity(g.bottle);g.bottle_alpha.default_value=.72;g.bottle.location=(-4,0,0)
        for i in range(10):
            ob=g.sphere('bottle-air-'+str(i),.08,g.gasmat,(-4+.22*math.cos(i),.15*math.sin(i),-1.3+i*.24))
        for i in range(21):
            ob=g.sphere('external-impact-'+str(i),.105,g.coldmat);g.outer.append(ob);g.objects.append(ob)
        g.exterior_alpha=opacity(g.outer[0])
        for ob in g.outer[1:]:ob.data.materials[0]=g.outer[0].data.materials[0]
    elif g.env=='atmosphere':
        # Open cylinder: transparent sides + rings rather than a solid vessel.
        verts=[];faces=[]
        for z in (0,12):
            verts.extend((1.55*math.cos(i*math.tau/64),1.55*math.sin(i*math.tau/64),z) for i in range(64))
        for i in range(64):faces.append((i,(i+1)%64,(i+1)%64+64,i+64))
        mesh=bpy.data.meshes.new('air-column');mesh.from_pydata(verts,[],faces);ob=g.link('air-column',mesh);mesh.materials.append(g.surface('Column cyan',(.05,.55,1)))
        g.column_objects.append((ob,opacity(ob),.06))
        for z in (0,3,6,9,12):
            ob=g.path('column-ring-'+str(z),[(1.55*math.cos(i*math.tau/64),1.55*math.sin(i*math.tau/64),z) for i in range(65)],(.15,.65,1),.018)
            g.column_objects.append((ob,opacity(ob),.75))
        for x in (-2.25,2.25):
            for z in (3.4,6.8,10.2):
                ob=g.path('pressure-shaft',[(x,0,z+1),(x,0,z)],(1,.65,.1),.07)
                bpy.ops.mesh.primitive_cone_add(vertices=20,radius1=0,radius2=.23,depth=.42,location=(x,0,z-.15))
                tip=bpy.context.object;tip.name='pressure-down';tip.data.materials.append(g.material((1,.65,.1)))
                for o in (ob,tip):g.pressure_arrows.append((o,opacity(o)))
        rng=random.Random(88)
        for i in range(130):
            z=min(11.8,-3.4*math.log(max(.03,rng.random())));a=rng.random()*math.tau;rad=1.35*math.sqrt(rng.random())
            ob=g.sphere('column-air-'+str(i),.055,g.coldmat,(rad*math.cos(a),rad*math.sin(a),z));g.column_particles.append((ob,tuple(ob.location)))
            g.objects.append(ob)
        g.objects.extend(o for o,s,a in g.column_objects);g.objects.extend(o for o,s in g.pressure_arrows)
    if g.env=='parcel':
        g.nucleus=g.sphere('condensation-nucleus',.13,g.darkmat)
        g.droplet=g.sphere('water-droplet',.5,g.coldmat)
        g.detail_objects=[g.nucleus,g.droplet];g.vapor=[];g.ice=[]
        for i in range(9):g.vapor.append(g.sphere('water-vapour-'+str(i),.09,g.coldmat))
        for i in range(6):
            a=i*math.tau/6
            g.ice.append(g.path('ice-arm-'+str(i),[(0,0,0),(.65*math.cos(a),0,.65*math.sin(a))],(.68,.9,1),.04))
        for ob in [*g.detail_objects,*g.vapor,*g.ice]:
            g.objects.append(ob)
        rng=random.Random(41)
        for i in range(30):
            ob=g.sphere('surrounding-air-'+str(i),.07,g.coldmat)
            p=(rng.uniform(-5,5),rng.uniform(-1,2),rng.uniform(-2.3,3))
            g.surroundings.append((ob,p,opacity(ob)));g.objects.append(ob)
    g.states=[state_at(g.job,f) for f in range(g.job['duration_frames'])]
    g.phases=[];phase=0
    for st in g.states:
        g.phases.append(phase);phase+=2.3*st['speed']/st['volume']**(1/3)/g.job['canonical_fps']


def sample(g,frame):
    s=g.states[frame];g.current=s;t=frame/g.job['canonical_fps'];z=s['altitude']
    camera=Vector((s['camera_x'],s['camera_y'],s['camera_z']));target=Vector((s['focus_x'],s['focus_y'],s['focus_z']))
    g.camera.location=camera;g.camera.rotation_euler=(target-camera).to_track_quat('-Z','Y').to_euler();g.camera.data.lens=s['lens']
    radius=1.38*s['volume']**(1/3)
    if g.env=='balloon':radius=1.1+.3*s['inflate']
    g.parcel.location=(0,0,z)
    cold=min(1,max(0,(1-s['temperature'])*3))
    g.gasmat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(.96*(1-cold)+.04*cold,.06*(1-cold)+.33*cold,.025*(1-cold)+1*cold,1)
    for i,ob in enumerate(g.particles):
        p=sphere_particle(i,g.phases[frame]);ob.location=tuple(x*(radius-.18) for x in p)
        if g.balloon_asset is not None:ob.location.y*=1-s['reveal']
    if g.env=='sky':
        g.asset_cloud.location=(0,0,z)
        for socket in g.cloud_sockets:socket.default_value=1-.96*s['reveal']
        g.gas_alpha.default_value=s['reveal']
        for ob,socket in g.boundary:
            ob.scale=(radius,)*3;ob.location=(0,0,z);socket.default_value=s['reveal']
    else:
        sc=(radius/1.4);g.balloon_asset.scale=(sc,sc,sc);g.balloon_asset.location=(0,0,z-.06)
        g.reveal_socket.default_value=s['reveal'];g.gas_alpha.default_value=max(.12,s['reveal'])
        g.slice_edge.scale=g.balloon_asset.scale;g.slice_edge.location=g.balloon_asset.location;g.slice_alpha.default_value=s['reveal']
        g.balloon_alpha.default_value=1
    if g.env=='balloon':
        collision_radius=g.surface_radius*g.balloon_asset.scale.x
        for i,ob in enumerate(g.outer):
            p=boundary_collision(i,t,collision_radius);distance=math.sqrt(sum(v*v for v in p));angle=(i-10)*.035
            ob.location=(distance*math.cos(angle),0,distance*math.sin(angle)+z)
        g.exterior_alpha.default_value=s['outside']
        # Inner near-wall particle paired with an exterior approach: separated by
        # the actual rubber boundary, both trajectories reverse at their surface.
        for i in range(5):
            travel=abs((t+i*.19)%2-1)*.75
            yy=0;zz=(i-2)*.24
            wall=math.sqrt(max(.01,collision_radius**2-yy**2-zz**2))
            g.particles[i].location=(wall-.105-travel,yy,zz)
    elif g.env=='atmosphere':
        for o,socket,alpha in g.column_objects:socket.default_value=alpha*s['column']
        for o,socket in g.pressure_arrows:socket.default_value=s['arrow']
        for i,(o,p) in enumerate(g.column_particles):o.location=(p[0]+.035*math.sin(t+i),p[1],p[2]+.035*math.cos(t*.8+i))
    if g.env=='parcel':
        c=s['cloud'];detail=s['detail'];fade=1-smooth((c-.75)/.25)
        g.balloon_alpha.default_value=fade;g.slice_alpha.default_value=fade*s['reveal'];g.gas_alpha.default_value=fade*max(.3,s['reveal'])
        for ob,p,socket in g.surroundings:
            x,y,zz=p;d=max(.01,math.sqrt(x*x+y*y+zz*zz));push=max(1,(radius+.45)/d)
            ob.location=(x*push,y*push,z+zz*push);socket.default_value=fade
        g.asset_cloud.location=(0,0,z)
        size=max(.001,smooth((c-.3)/.7));g.asset_cloud.scale=(size,)*3
        for socket in g.cloud_sockets:socket.default_value=smooth((c-.3)/.7)
        g.nucleus.location=(0,-.4,z);g.nucleus.scale=(max(.001,detail*fade),)*3
        g.droplet.location=(0,-.4,z);g.droplet.scale=(max(.001,detail*c*.95*fade),)*3
        for i,ob in enumerate(g.vapor):
            a=i*math.tau/len(g.vapor)+t*.14;rad=1.3*(1-smooth(c/.5))+.18
            ob.location=(rad*math.cos(a),-.4,z+rad*math.sin(a));ob.scale=(max(.001,detail*(1-smooth(c/.5))),)*3
        for ob in g.ice:
            ob.location=(2,-.7,z+.5);ob.scale=(max(.001,smooth((c-.65)/.35)*fade),)*3
    return g.job['canonical_state_cache'][frame],[*g.objects,g.camera]
