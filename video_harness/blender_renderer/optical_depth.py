"""Native bpy optical-depth teaching scene; no on-screen text."""
import math
import random
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
try:
    from .scene import SpectralGallery
    from .optical_depth_math import state_at, free_depth
except ImportError:
    from scene import SpectralGallery
    from optical_depth_math import state_at, free_depth


class OpticalDepthGallery(SpectralGallery):
    def build(self):
        self.scene.name = 'Optical depth'
        self.scene.world.use_nodes=True
        self.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.004,.01,.023,1)
        self.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.4
        self.sun_mode = self.job['timeline'][0]['controller_options'].get('environment') == 'sun'
        self.animated = [self.camera]
        self.droplets = []
        self.colliders = []
        self.packets = []
        if self.sun_mode:
            self.build_sun()
        else:
            self.build_fog()

    def sphere(self, name, radius, color, location):
        obj = self.star(name, 0, 0, radius, color)
        obj.location = location
        return obj

    def import_asset(self, filename):
        path = Path(__file__).resolve().parents[2] / 'assets' / filename
        before = set(self.scene.objects)
        if path.suffix == '.usdz':
            bpy.ops.wm.usd_import(filepath=str(path))
        else:
            bpy.ops.import_scene.gltf(filepath=str(path))
        imported = list(set(self.scene.objects)-before)
        meshes = [obj for obj in imported if obj.type == 'MESH']
        self.scene.view_layers[0].update()
        for obj in meshes:
            world = obj.matrix_world.copy()
            obj.parent = None
            obj.data.transform(world)
            obj.matrix_world = Matrix.Identity(4)
        for obj in imported:
            if obj not in meshes:
                bpy.data.objects.remove(obj, do_unlink=True)
        for obj in meshes:
            for material in obj.data.materials:
                if material and material.node_tree:
                    for node in material.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image:
                            node.image.pack()
        return meshes

    def build_sun(self):
        self.sun = self.import_asset('Sun 3D Model Interactive.usdz')[0]
        self.sun.name = 'Sun'
        self.sun.data.transform(Matrix.Scale(3.,4))
        for face in self.sun.data.polygons:
            face.use_smooth = True
        mat = self.sun.data.materials[0]
        nodes = mat.node_tree.nodes; links = mat.node_tree.links
        tex = next(n for n in nodes if n.type == 'TEX_IMAGE')
        out = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL')
        emission = nodes.new('ShaderNodeEmission')
        links.new(tex.outputs['Color'],emission.inputs['Color'])
        # Reveal an angular cutaway in the original textured asset. The gas
        # surface remains in place; it does not peel away like a solid shell.
        coords = nodes.new('ShaderNodeTexCoord')
        subtract = nodes.new('ShaderNodeVectorMath'); subtract.operation='SUBTRACT'
        subtract.inputs[1].default_value=(.5,.5,.5)
        links.new(coords.outputs['Generated'],subtract.inputs[0])
        xyz = nodes.new('ShaderNodeSeparateXYZ'); links.new(subtract.outputs[0],xyz.inputs[0])
        angle = nodes.new('ShaderNodeMath'); angle.operation='ARCTAN2'
        links.new(xyz.outputs['Z'],angle.inputs[0]); links.new(xyz.outputs['X'],angle.inputs[1])
        positive = nodes.new('ShaderNodeMath'); positive.operation='GREATER_THAN'
        links.new(angle.outputs[0],positive.inputs[0])
        limit = nodes.new('ShaderNodeMath'); limit.operation='LESS_THAN'
        links.new(angle.outputs[0],limit.inputs[0])
        self.cutaway = nodes.new('ShaderNodeValue').outputs[0]
        self.cutaway.default_value=0
        links.new(self.cutaway,limit.inputs[1])
        mask = nodes.new('ShaderNodeMath'); mask.operation='MULTIPLY'
        links.new(positive.outputs[0],mask.inputs[0]); links.new(limit.outputs[0],mask.inputs[1])
        transparent = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        back = nodes.new('ShaderNodeNewGeometry')
        interior = nodes.new('ShaderNodeEmission'); interior.inputs['Color'].default_value=(.09,.016,.002,1)
        surface = nodes.new('ShaderNodeMixShader')
        links.new(back.outputs['Backfacing'],surface.inputs[0])
        links.new(emission.outputs[0],surface.inputs[1]);links.new(interior.outputs[0],surface.inputs[2])
        links.new(mask.outputs[0],mix.inputs[0]); links.new(surface.outputs[0],mix.inputs[1])
        links.new(transparent.outputs[0],mix.inputs[2]); links.new(mix.outputs[0],out.inputs['Surface'])
        mat.surface_render_method='DITHERED'
        rng = random.Random(19)
        for i in range(100):
            p = (rng.uniform(.15,3.2), rng.uniform(-2.8,2.8), rng.uniform(.2,2.8))
            if sum(x*x for x in p) < 17:
                self.sphere('Plasma-%03d'%i, .09, (1,.35,.05), p)
        for i in range(12):
            self.packets.append(self.sphere('SolarPhoton-%02d'%i,.075,(1,.9,.45),(0,0,0)))
        for i in range(4):
            self.sphere('SolarInteraction-%d'%i,.12,(1,.35,.05),(2.5,(i-1.5)*.65,1.5))
        self.animated += [self.sun, *self.packets]

    def build_fog(self):
        lamp = self.import_asset('street_lamp.glb')
        self.source = next(obj for obj in lamp if any(m and m.name.split('.')[0]=='light' for m in obj.data.materials))
        self.source.name='Lamp'
        points=[v.co for obj in lamp for v in obj.data.vertices]
        head=sum((v.co for v in self.source.data.vertices),Vector())/len(self.source.data.vertices)
        scale=4/(head.z-min(p.z for p in points))
        axes=Matrix(((-1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
        transform=Matrix.Translation(Vector((-9,0,-.2))-(axes@head)*scale) @ axes @ Matrix.Scale(scale,4)
        for obj in lamp:
            obj.data.transform(transform)
        self.source.data.materials.clear()
        self.source.data.materials.append(self.material((1,.8,.32),1.5))
        self.path('Ground',[(-11,-4.1,-1),(11,-4.1,-1)],(.13,.21,.3),.035)
        self.receiver = self.ring('DirectReceiver',9,0,1.9,(.32,.65,.8))
        rng = random.Random(28)
        for i in range(310):
            obj = self.sphere('Droplet-%03d'%i,.085,(.15,.38,.56),(0,0,0))
            self.droplets.append((obj,(rng.random(),rng.uniform(-2.7,2.7),rng.uniform(-1.3,.2))))
        for i in range(100):
            self.packets.append(self.sphere('Photon-%03d'%i,.09,(1,.78,.26),(0,0,0)))
            self.colliders.append(self.sphere('CollisionDroplet-%03d'%i,.075,(.15,.38,.56),(0,0,0)))
        bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,-.6))
        self.fog=bpy.context.object;self.fog.name='FogVolume'
        material=bpy.data.materials.new('Water-droplet haze');material.use_nodes=True
        nodes=material.node_tree.nodes;nodes.clear();links=material.node_tree.links
        volume=nodes.new('ShaderNodeVolumePrincipled')
        volume.inputs['Color'].default_value=(.42,.65,.8,1)
        self.fog_density=volume.inputs['Density']
        self.fog_density.default_value=.12
        output=nodes.new('ShaderNodeOutputMaterial');links.new(volume.outputs['Volume'],output.inputs['Volume'])
        self.fog.data.materials.append(material)
        self.dividers=[]
        for i in range(3):
            obj=self.path('LayerBoundary-%d'%i,[(0,-2.9,-.4),(0,2.9,-.4)],(.18,.4,.5),.025)
            self.dividers.append(obj)
        self.animated += [self.source,self.receiver,self.fog,*self.packets,*self.colliders,*self.dividers,
                          *(obj for obj,_ in self.droplets)]

    def sample(self, frame):
        st = state_at(self.job, frame); self.state = st
        entry = self.job['canonical_state_cache'][frame]
        t = entry['simulation_time']
        self.camera.location = (st['camera_x'], st['camera_y'], 25)
        profile = self.job.get('variant_profile', {}) or {}
        self.camera.data.ortho_scale = st['camera_width'] * {
            'wide': 1.08, 'close': .96, 'restrained': 1.04
        }.get(profile.get('camera_profile'), 1.)
        if self.sun_mode:
            self.cutaway.default_value = st['opening']*math.pi/2
            for i,obj in enumerate(self.packets):
                p = (t*.55+i/12)%1
                collision = .45
                if p < collision:
                    obj.location=(.25+p*5,(i%4-1.5)*.65,1.5)
                else:
                    offset = (p-collision)*5*(-1 if i%2 else 1) if i%3 else 0
                    obj.location=(.25+collision*5, (i%4-1.5)*.65+offset,1.5)
                size = 1 if i%3 or p < collision else max(0,1-(p-collision)*12)
                obj.scale=(size,)*3
            return entry,self.animated
        length, tau = st['length'], st['tau']
        left = -4.
        self.fog.location=(left+length/2,0,-.6)
        self.fog.scale=(length,5.8,2.4)
        self.fog_density.default_value=.4*tau/length
        # Droplets fill a fixed cross-section; visual number follows n*L ~ tau.
        # Collision droplets are part of the same population, not extra matter.
        # Total visible markers follow 100*tau, keeping n constant when L and
        # tau grow together and doubling n when L halves at constant tau.
        background_count = tau*100-(100-st['direct_packets'])
        for i,(obj,point) in enumerate(self.droplets):
            obj.location=(left+point[0]*length,point[1],point[2])
            size=max(0,min(1,background_count-i))
            obj.scale=(size,)*3
        for i,obj in enumerate(self.packets):
            # A 10x10 train in the image plane keeps all 100 samples distinct.
            # Stagger columns in time rather than hiding packets behind each other.
            x=-9+((t*.22-(i//10)*.012)%1)*18
            y=((i%10)-4.5)*.34; z=.75
            collision=left+free_depth(i)*length/max(tau,1e-9)
            collider = self.colliders[i]
            collider.location = (min(left+length,collision),y,z)
            collider.scale = ((1 if collision < left+length else 0),)*3
            if collision < left+length and x > collision:
                # Fog extinction is scattering: packets leave the direct bundle.
                y += (x-collision)*(.8+(i%7)*.11)*(-1 if i%2 else 1)
                x = collision
            obj.location=(x,y,z)
        for i,obj in enumerate(self.dividers):
            obj.location.x=left+(i+1)*3
            size=max(0,min(1,st['layers']-i))
            obj.scale=(1,size,1)
        return entry,self.animated

    def bake(self):
        # Bulk curves avoid millions of repeated keyframe insertions for droplets.
        from array import array
        from bpy_extras import anim_utils
        self.sample(0)
        for obj in self.animated:
            for prop in ('location','scale'):
                obj.keyframe_insert(data_path=prop,frame=1)
        self.camera.data.keyframe_insert(data_path='ortho_scale',frame=1)
        if self.sun_mode:
            self.cutaway.keyframe_insert(data_path='default_value',frame=1)
        if not self.sun_mode:
            self.fog_density.keyframe_insert(data_path='default_value',frame=1)
        owners=[*self.animated,self.camera.data]
        if self.sun_mode:
            owners.append(self.sun.data.materials[0].node_tree)
        else:
            owners.append(self.fog.data.materials[0].node_tree)
        channels=[]
        for owner in owners:
            data=getattr(owner,'animation_data',None)
            if not data or not data.action:
                continue
            bag=anim_utils.action_get_channelbag_for_slot(data.action,data.action_slot)
            for curve in bag.fcurves:
                value=owner.path_resolve(curve.data_path)
                channels.append((curve,owner,curve.data_path,curve.array_index,hasattr(value,'__len__')))
        values=[array('f') for _ in channels]
        frames=self.job['duration_frames']
        for frame in range(frames):
            self.sample(frame)
            for (_,owner,path,index,vector),column in zip(channels,values):
                value=owner.path_resolve(path)
                column.append(float(value[index] if vector else value))
        for (curve,*_),column in zip(channels,values):
            if all(value==column[0] for value in column):
                continue
            points=curve.keyframe_points;points.add(frames-len(points))
            co=array('f',[0.])*(2*frames)
            co[0::2]=array('f',range(1,frames+1));co[1::2]=column
            points.foreach_set('co',co)
            for point in points:
                point.interpolation='LINEAR'
            curve.update()
        self.scene.frame_set(1)
        bpy.ops.file.pack_all()

    def extra_state(self):
        return dict(self.state)
