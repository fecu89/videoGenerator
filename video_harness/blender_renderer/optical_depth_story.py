"""Perspective city, real fog, microscopic plasma and a synchronized scientific graph."""
import math,random
from array import array
import bpy
from mathutils import Vector,Matrix
from bpy_extras.object_utils import world_to_camera_view
try:
    from .optical_depth import OpticalDepthGallery
    from .optical_depth_story_math import state_at,free_depth,transition_at
except ImportError:
    from optical_depth import OpticalDepthGallery
    from optical_depth_story_math import state_at,free_depth,transition_at

class OpticalDepthStoryGallery(OpticalDepthGallery):
    def build(self):
        self.scene.name='Optical depth — city and plasma'
        self.scene.world.use_nodes=True
        bg=self.scene.world.node_tree.nodes['Background'];bg.inputs[0].default_value=(.075,.11,.18,1);bg.inputs[1].default_value=.35
        self.scene.eevee.taa_render_samples=32
        self.camera.data.type='PERSP';self.camera.data.clip_end=300
        self.camera.data.lens=38;self.animated=[self.camera];self.sockets=[];self.extra_owners=[]
        self.sun_mode=self.job['timeline'][0]['controller_options']['environment']=='sun'
        self.graph_fonts=[]
        tree=bpy.data.node_groups.new('Optical atmosphere composite','CompositorNodeTree');self.scene.compositing_node_group=tree
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        layers=tree.nodes.new('CompositorNodeRLayers');glare=tree.nodes.new('CompositorNodeGlare');glare.inputs['Type'].default_value='Fog Glow';glare.inputs['Quality'].default_value='Medium'
        if glare.inputs.get('Threshold'):glare.inputs['Threshold'].default_value=1.4
        layers.scene=self.scene
        wash=tree.nodes.new('ShaderNodeMix');wash.data_type='RGBA';wash.blend_type='MIX';wash.inputs[7].default_value=(4.,3.8,3.3,1)
        self.flash=wash.inputs[0];self.flash.default_value=0.;self.sockets.append(self.flash);self.extra_owners.append(tree)
        out=tree.nodes.new('NodeGroupOutput');tree.links.new(layers.outputs['Image'],glare.inputs[0]);tree.links.new(glare.outputs[0],wash.inputs[6]);tree.links.new(wash.outputs[2],out.inputs[0])
        if self.sun_mode:self.build_plasma()
        else:self.build_street()

    def solid(self,name,color,metal=0.,rough=.4):
        m=bpy.data.materials.new(name);m.use_nodes=True;n=m.node_tree.nodes.get('Principled BSDF')
        n.inputs['Base Color'].default_value=(*color,1);n.inputs['Metallic'].default_value=metal;n.inputs['Roughness'].default_value=rough
        return m

    def ball(self,name,r,mat,loc):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=r,location=loc)
        o=bpy.context.object;o.name=name;o.data.materials.append(mat)
        for f in o.data.polygons:f.use_smooth=True
        return o

    def root(self,name):return self.link(name,None)

    def attach(self,obj,root):
        obj.parent=root;return obj

    def light(self,name,kind,loc,power,color,size=1,target=None):
        d=bpy.data.lights.new(name,kind);d.energy=power;d.color=color
        if kind=='AREA':d.shape='DISK';d.size=size
        elif kind in ('POINT','SPOT'):d.shadow_soft_size=size
        o=self.link(name,d);o.location=loc
        if target is not None:o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
        return o

    def alpha_material(self,obj):
        for mat in obj.data.materials:
            if not mat or not mat.node_tree:continue
            n=mat.node_tree.nodes;links=mat.node_tree.links;out=next((x for x in n if x.type=='OUTPUT_MATERIAL'),None)
            if not out or not out.inputs['Surface'].links:continue
            old=out.inputs['Surface'].links[0].from_socket
            tr=n.new('ShaderNodeBsdfTransparent');mix=n.new('ShaderNodeMixShader')
            links.new(tr.outputs[0],mix.inputs[1]);links.new(old,mix.inputs[2]);links.new(mix.outputs[0],out.inputs['Surface'])
            mix.inputs[0].default_value=1;mat.surface_render_method='DITHERED'
            self.sockets.append(mix.inputs[0]);self.extra_owners.append(mat.node_tree)
            return mix.inputs[0]

    def build_plasma(self):
        self.sun=self.import_asset('Sun 3D Model Interactive.usdz')[0];self.sun.name='Sun';self.sun.data.transform(Matrix.Scale(3,4))
        m=self.sun.data.materials[0];nodes=m.node_tree.nodes;links=m.node_tree.links;tex=next(n for n in nodes if n.type=='TEX_IMAGE');out=next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
        em=nodes.new('ShaderNodeEmission');links.new(tex.outputs['Color'],em.inputs[0]);em.inputs[1].default_value=1.2;links.new(em.outputs[0],out.inputs['Surface'])
        self.sun_alpha=self.alpha_material(self.sun)
        self.micro=self.root('PlasmaCloud');self.animated += [self.sun,self.micro]
        template=self.import_asset('Hydrogen animation.glb')
        proton=next(o for o in template if any(m.name.startswith('proton') for m in o.data.materials))
        electron=next(o for o in template if o!=proton)
        for o in template:
            if o.animation_data:o.animation_data_clear()
            center=sum((v.co for v in o.data.vertices),Vector())/len(o.data.vertices)
            o.data.transform(Matrix.Translation(-center));o.hide_render=True
        pmat=self.solid('Hydrogen proton',(1,.12,.06),.25,.25);nmat=self.solid('Helium neutron',(.3,.55,.95),.2,.25)
        emat=self.material((.15,.55,1),2)
        rng=random.Random(92);self.nuclei=[];self.electrons=[]
        for i in range(34):
            center=Vector((rng.uniform(-3.7,3.7),rng.uniform(-.5,8),rng.uniform(-2,3)))
            offsets=[(0,0,0)] if i%4 else [(-.09,0,.07),(.09,0,.07),(0,-.09,-.07),(0,.09,-.07)]
            for j,offset in enumerate(offsets):
                o=self.link(('H' if len(offsets)==1 else 'He')+'Nucleus-%d-%d'%(i,j),proton.data.copy());o.data.materials.clear();o.data.materials.append(pmat if j<2 else nmat)
                o.location=center+Vector(offset);o.scale=(.14,)*3;self.attach(o,self.micro)
            self.nuclei.append(center)
        for i in range(20):
            o=self.link('FreeElectron-%02d'%i,electron.data);o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(emat);o.scale=(.055,)*3
            o.location=(rng.uniform(-3,3),rng.uniform(0,7),rng.uniform(-1.5,2.5));self.attach(o,self.micro);self.electrons.append(o)
        self.micro_photons=[]
        for i in range(16):
            o=self.ball('SolarPhoton-%02d'%i,.045,self.material((1,.82,.22),4),(0,0,0));self.attach(o,self.micro);self.micro_photons.append(o)
        self.animated+=self.micro_photons
        self.transition_photon=self.ball('Transition photon',.06,self.material((1,.88,.58),15),(0,3,1));self.animated.append(self.transition_photon)
        self.light('Plasma key','AREA',(-3,-4,6),1200,(1,.55,.3),6,(0,2,0))
        self.light('Plasma rim','AREA',(4,6,4),1500,(.25,.5,1),5,(0,2,0))

    def build_street(self):
        self.city=[];self.city_fades=[]
        meshes=self.import_asset('street_city_7_for_games_free.glb');groups={}
        for obj in meshes:groups.setdefault(obj.name.split('_')[0],[]).append(obj)
        candidates=[]
        for key,objs in groups.items():
            pts=[v.co for o in objs for v in o.data.vertices];lo=Vector([min(p[i] for p in pts) for i in range(3)]);hi=Vector([max(p[i] for p in pts) for i in range(3)])
            if hi.z-lo.z>5 and max(hi.x-lo.x,hi.y-lo.y)<18:candidates.append((key,objs,lo,hi))
        used=set()
        for i,(key,objs,lo,hi) in enumerate(candidates[:10]):
            side=1 if i%2 else -1;x=-24+(i//2)*12;y=side*11
            root=self.root('CityBuilding-%02d'%i);root.location=(x,y,0);self.city.append(root);self.animated.append(root)
            center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));scale=min(1.,9/(hi.z-lo.z))
            for o in objs:
                o.data.transform(Matrix.Scale(scale,4)@Matrix.Translation(-center));self.attach(o,root);used.add(o)
                for slot in o.material_slots:
                    if slot.material:slot.material=slot.material.copy()
                socket=self.alpha_material(o)
                if socket:self.city_fades.append((socket,1. if side<0 else .75))
        for o in meshes:
            if o not in used:bpy.data.objects.remove(o,do_unlink=True)
        # Reuse fog_place terrain and its shader-domain mesh, replacing the
        # unportable GLSL fog with actual Blender volume scattering.
        fog_asset=self.import_asset('fog_place.glb');terrain=next(o for o in fog_asset if any(m.name.startswith('lambert6') for m in o.data.materials))
        cube=next(o for o in fog_asset if len(o.data.vertices)==24)
        terrain.name='FogPlaceTerrain';terrain.data.transform(Matrix.Scale(.65,4));terrain.location.z=-2.0
        for o in fog_asset:
            if o not in (terrain,cube):bpy.data.objects.remove(o,do_unlink=True)
        pts=[v.co for v in cube.data.vertices];lo=Vector([min(p[i] for p in pts) for i in range(3)]);hi=Vector([max(p[i] for p in pts) for i in range(3)])
        for v in cube.data.vertices:v.co=Vector([(v.co[i]-(lo[i]+hi[i])/2)/(hi[i]-lo[i]) for i in range(3)])
        self.fog=cube;cube.name='FogPlaceVolume';cube.location=(0,0,7);cube.scale=(75,60,18)
        fm=bpy.data.materials.new('Atmospheric fog');fm.use_nodes=True;n=fm.node_tree.nodes;n.clear();ln=fm.node_tree.links
        vol=n.new('ShaderNodeVolumePrincipled');vol.inputs['Color'].default_value=(.68,.77,.87,1);vol.inputs['Anisotropy'].default_value=.25
        self.density=vol.inputs['Density'];self.density.default_value=.065;out=n.new('ShaderNodeOutputMaterial');ln.new(vol.outputs[0],out.inputs['Volume']);cube.data.materials.clear();cube.data.materials.append(fm)
        self.sockets.append(self.density);self.extra_owners.append(fm.node_tree);self.animated.append(cube)
        bpy.ops.mesh.primitive_plane_add(size=1,location=(0,0,.02));road=bpy.context.object;road.name='Street';road.scale=(70,15,1);road.data.materials.append(self.solid('Damp asphalt',(.045,.058,.072),.15,.22))
        for y in (-7.2,7.2):self.path('Curb', [(-35,y,.12),(35,y,.12)],(.28,.33,.36),.06)
        for x in range(-30,31,5):self.path('Road marking',[(x,0,.035),(x+2,0,.035)],(.5,.49,.36),.025)
        lamp=self.import_asset('street_lamp.glb');head=next(o for o in lamp if any(m.name.split('.')[0]=='light' for m in o.data.materials))
        pts=[v.co for o in lamp for v in o.data.vertices];minz=min(p.z for p in pts);headcenter=sum((v.co for v in head.data.vertices),Vector())/len(head.data.vertices)
        scale=5.5/(headcenter.z-minz);transform=Matrix.Translation(Vector((-8,0,5.5))-headcenter*scale)@Matrix.Scale(scale,4)
        self.lamp=self.root('Lamp');self.lamp.location=(-8,0,5.5)
        # The asset's arm points -X; the observer is on +X. Keep the emitting
        # head fixed so the photon paths and brightness-match cameras still align.
        self.lamp.rotation_euler.z=math.pi
        for o in lamp:o.data.transform(transform);o.data.transform(Matrix.Translation(-self.lamp.location));self.attach(o,self.lamp)
        head.data.materials.clear();head.data.materials.append(self.material((1,.68,.27),6))
        self.spot=self.light('Lamp beam','SPOT',(-8,0,5.4),2400,(1,.72,.4),.28,(8,0,1.7));self.spot.data.spot_size=math.radians(48);self.spot.data.spot_blend=.7
        self.light('Lamp glow','POINT',(-8,0,5.3),170,(1,.7,.4),.3)
        self.light('Moon','AREA',(0,-2,20),2300,(.4,.57,1),28,(0,0,0))
        self.light('Street fill','AREA',(4,-12,10),1700,(.65,.74,1),20,(0,0,3))
        self.observer=self.root('Observer');self.observer.location=(8,0,0);self.animated.append(self.observer)
        human=self.import_asset('human.glb')
        pts=[Vector(v) for o in human for v in o.bound_box]
        # import_asset bakes world-space vertices, so refresh mesh bounds first.
        for o in human:o.data.update()
        self.scene.view_layers[0].update()
        pts=[Vector(v) for o in human for v in o.bound_box]
        lo=Vector([min(p[i] for p in pts) for i in range(3)]);hi=Vector([max(p[i] for p in pts) for i in range(3)])
        center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));size=1.8/(hi.z-lo.z)
        transform=Matrix.Rotation(-math.pi/2,4,'Z')@Matrix.Scale(size,4)@Matrix.Translation(-center)
        self.observer_visibility=[];seen_materials=set()
        for i,o in enumerate(human):
            o.name='Observer human-%02d'%i;o.data.transform(transform);self.attach(o,self.observer)
            for face in o.data.polygons:face.use_smooth=True
            material=o.data.materials[0] if o.data.materials else None
            if material and material not in seen_materials:
                socket=self.alpha_material(o)
                if socket:self.observer_visibility.append(socket)
                seen_materials.add(material)
        self.observer_fill=self.light('Observer fill','AREA',(8,-3,4),90,(.55,.7,1),4,(8,0,1))
        self.animated.extend([self.lamp,self.spot,self.observer_fill])
        self.photons=[];self.tails=[]
        gold=self.material((1,.55,.055),2.2)
        for i in range(64):
            o=self.ball('LightPacket-%02d'%i,.055,gold,(0,0,0));self.photons.append(o)
        self.animated+=self.photons
        self.build_graph()
        self.ending_sun=self.import_asset('Sun 3D Model Interactive.usdz')[0];self.ending_sun.name='Closing Sun';self.ending_sun.data.transform(Matrix.Scale(3,4));self.ending_sun.location=(0,0,100)
        mat=self.ending_sun.data.materials[0];nodes=mat.node_tree.nodes;links=mat.node_tree.links
        tex=next(n for n in nodes if n.type=='TEX_IMAGE');out=next(n for n in nodes if n.type=='OUTPUT_MATERIAL');em=nodes.new('ShaderNodeEmission');links.new(tex.outputs['Color'],em.inputs[0]);em.inputs[1].default_value=1.2;links.new(em.outputs[0],out.inputs['Surface'])
        self.animated.append(self.ending_sun)

    def hud(self,obj,x,y,depth=2):
        obj.parent=self.camera;obj.location=(x,y,-depth);return obj

    def build_graph(self):
        self.graph_root=self.root('ScientificGraph');self.graph_root.parent=self.camera
        self.graph_objects=[];self.graph_fonts=[]
        # Camera-space graph spans the right 36% of the picture.
        self.gx=.20;self.gy=-.24;self.gw=.54;self.gh=.48
        def line(name,points,color=(.65,.76,.86),radius=.002):
            o=self.path(name,[(x,y,0) for x,y in points],color,radius);o.parent=self.graph_root;self.graph_objects.append(o);return o
        x,y,w,h=self.gx,self.gy,self.gw,self.gh
        line('GraphAxes',[(x,y+h),(x,y),(x+w,y)])
        self.graph_curve=line('TransmissionCurve',[(x+w*i/90,y+h*math.exp(-5*i/90)) for i in range(91)],(1,.66,.18),.0035)
        self.graph_curve.data.bevel_factor_end=0
        self.graph_point=self.ball('TransmissionPoint',.011,self.material((1,.85,.35),3),(0,0,0));self.graph_point.parent=self.graph_root;self.graph_objects.append(self.graph_point)
        texts=[('광학적 깊이',x+w*.48,y-.10,.048),('광량',x-.025,y+h+.065,.048),('0',x,y-.045,.037),('1',x+w/5,y-.045,.037),('2',x+w*2/5,y-.045,.037),('3',x+w*3/5,y-.045,.037),('5',x+w,y-.045,.037),('100%',x-.075,y+h,.032),('37%',x-.065,y+h*math.exp(-1),.032),('14%',x-.065,y+h*math.exp(-2),.032),('5%',x-.065,y+h*math.exp(-3),.032)]
        for text,xp,yp,size in texts:
            o=self.text(text,xp,yp,size,(.82,.89,1),'CENTER');o.name='GraphText:'+text;o.parent=self.graph_root;o.location.z=.01;self.graph_objects.append(o);self.graph_fonts.append(o)
        self.animated += [self.graph_root,self.graph_point,*self.graph_fonts]

    def sample(self,frame):
        st=state_at(self.job,frame);self.state=st;entry=self.job['canonical_state_cache'][frame];t=entry['simulation_time']
        transition=transition_at(self.job,frame);self.flash.default_value=transition['flash']
        self.camera.location=st['camera'];self.camera.rotation_euler=(Vector(st['target'])-self.camera.location).to_track_quat('-Z','Y').to_euler();self.camera.data.lens=st['lens']
        if self.sun_mode:
            self.transition_photon.scale=(max(.00001,transition['zoom']*5),)*3
            q=st['solar_zoom'];self.sun_alpha.default_value=1-min(1,max(0,(q-.25)/.45));self.sun.rotation_euler.z=t*.025
            self.micro.scale=(max(.00001,q),)*3
            for i,o in enumerate(self.micro_photons):
                hit=self.electrons[i%len(self.electrons)].location;p=(t*.5+i*.061)%1
                if p<.52:o.location=hit+Vector((0,-(1-p/.52)*4,0))
                else:o.location=hit+Vector(((p-.52)*7*(-1 if i%2 else 1),(p-.52)*2,(p-.52)*3*((i%3)-1)))
                scale=1 if i%6 or p<.52 else max(0,1-(p-.52)*15)
                o.scale=(scale,)*3
            return entry,self.animated
        self.ending_sun.hide_render=transition['kind']!='sun_pullback';self.ending_sun.rotation_euler.z=t*.025
        self.observer.location.x=-8+math.sqrt(st['distance']**2-(5.5-1.68)**2);eye=Vector((self.observer.location.x,0,1.68));source=Vector((-8,0,5.5));axis=eye-source
        visibility=max(0.,min(1.,((self.camera.location-eye).length-1.)/.7))
        for socket in self.observer_visibility:socket.default_value=visibility
        self.observer_fill.location.x=self.observer.location.x
        self.spot.rotation_euler=(eye-self.spot.location).to_track_quat('-Z','Y').to_euler()
        self.density.default_value=(.55*st['tau']/st['distance'])*(1-.75*st['section'])
        self.fog.location=(0,0,7);self.fog.scale=(75,60,18)
        for socket,amount in self.city_fades:socket.default_value=1-amount*st['section']
        for i,o in enumerate(self.photons):
            u=(t*.43+(i*.61803398875)%1)%1;depth=free_depth(i,64);collision=depth/max(st['tau'],1e-8)
            lane=Vector((0,.25*math.sin(i*2.4),.18*math.cos(i*1.7)))
            if collision<1 and u>collision:
                hit=source+axis*collision+lane;v=(u-collision)*axis.length
                o.location=hit+Vector((v*.12,v*math.sin(i*2.399),v*math.cos(i*2.399)))
            else:o.location=source+axis*u+lane
            depth=max(.05,(o.location-self.camera.location).dot(self.camera.rotation_euler.to_quaternion()@Vector((0,0,-1))))
            screen_limit=.0035*depth*self.camera.data.sensor_width/self.camera.data.lens/.055
            o.scale=(st['particles']*min(1.,screen_limit),)*3
        q=st['graph'];self.graph_root.location=(0,0,-2)
        # Perspective camera changes are absorbed by the HUD scale so graph
        # screen position/size is stable through the city-to-section movement.
        scale=(2*math.tan(self.camera.data.angle_x/2)*2)/1.6
        self.graph_root.scale=(scale*max(q,.000001),)*3
        for o in self.graph_fonts:o.hide_render=q<.99 or transition['kind']=='lamp_to_sun'
        tau=min(5,st['tau']);self.graph_point.location=(self.gx+self.gw*tau/5,self.gy+self.gh*math.exp(-tau),.005)
        self.graph_curve.data.bevel_factor_end=max(.00001,tau/5)
        return entry,self.animated

    def graph_text_state(self):
        self.scene.view_layers[0].update();rows=[]
        for o in self.graph_fonts:
            if o.hide_render:continue
            points=[world_to_camera_view(self.scene,self.camera,o.matrix_world@Vector(v)) for v in o.bound_box]
            rows.append(dict(text=o.data.body,object=o.name,rect=[min(p.x for p in points),1-max(p.y for p in points),max(p.x for p in points),1-min(p.y for p in points)]))
        return rows

    def extra_state(self):return dict(self.state)

    def bake(self):
        from bpy_extras import anim_utils
        self.sample(0)
        for obj in self.animated:
            for prop in ('location','rotation_euler','scale','hide_render'):obj.keyframe_insert(data_path=prop,frame=1)
        self.camera.data.keyframe_insert(data_path='lens',frame=1)
        for socket in self.sockets:socket.keyframe_insert(data_path='default_value',frame=1)
        owners=[*self.animated,self.camera.data,*self.extra_owners]
        if not self.sun_mode:self.graph_curve.data.keyframe_insert(data_path='bevel_factor_end',frame=1);owners.append(self.graph_curve.data)
        channels=[]
        for owner in dict.fromkeys(owners):
            ad=getattr(owner,'animation_data',None)
            if not ad or not ad.action:continue
            bag=anim_utils.action_get_channelbag_for_slot(ad.action,ad.action_slot)
            for curve in bag.fcurves:
                value=owner.path_resolve(curve.data_path);channels.append((curve,owner,curve.data_path,curve.array_index,hasattr(value,'__len__')))
        columns=[array('f') for _ in channels];count=self.job['duration_frames']
        for frame in range(count):
            self.sample(frame)
            for (_,owner,path,index,vector),column in zip(channels,columns):
                value=owner.path_resolve(path);column.append(float(value[index] if vector else value))
        for (curve,*_),values in zip(channels,columns):
            if min(values)==max(values):continue
            points=curve.keyframe_points;points.add(count-len(points));co=array('f',[0.])*(2*count);co[0::2]=array('f',range(1,count+1));co[1::2]=values;points.foreach_set('co',co)
            for p in points:p.interpolation='LINEAR'
            curve.update()
        self.scene.frame_set(1);bpy.ops.file.pack_all()
