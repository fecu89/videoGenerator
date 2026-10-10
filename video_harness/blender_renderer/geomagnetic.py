"""Native Blender concept film with immutable source GLBs and one common clock.

The opened hemisphere and flow/current tracers are explanatory geometry.
They do not claim a resolved MHD solution or an exact observed flow pattern.
"""
import math
from pathlib import Path
from array import array
import bpy
import bmesh
from mathutils import Vector,Matrix
try:
    from .scene import SpectralGallery
    from .geomagnetic_math import Story,field_path,bar_field_path,magnetosphere_path,solar_wind_point,flow_point,parcel_state,wire_field_point,FLOW_PERIOD
    from .animated_materials import fade_material,animated_sockets
    from .callout import CalloutLayer,labels_from_job
except ImportError:
    from scene import SpectralGallery
    from geomagnetic_math import Story,field_path,bar_field_path,magnetosphere_path,solar_wind_point,flow_point,parcel_state,wire_field_point,FLOW_PERIOD
    from animated_materials import fade_material,animated_sockets
    from callout import CalloutLayer,labels_from_job


class GeomagneticGallery(SpectralGallery):
    def configure(self):
        super().configure()
        self.scene.name='Earth geodynamo — concept model'
        self.scene.eevee.taa_render_samples=16
        self.scene.world.use_nodes=True
        bg=self.scene.world.node_tree.nodes['Background']
        bg.inputs['Color'].default_value=(.075,.12,.19,1)
        bg.inputs['Strength'].default_value=.48
        self.camera.data.clip_end=150
        for obj in self.scene.objects:
            if obj.type=='LIGHT':
                obj.location=(-5,-9,9);obj.data.energy=1600;obj.data.size=8
        light=bpy.data.lights.new('Cool rim','AREA');light.energy=1200;light.size=6
        obj=self.link('Cool rim',light);obj.location=(5,2,7)
        obj.rotation_euler=(Vector((0,0,0))-obj.location).to_track_quat('-Z','Y').to_euler()

    def solid(self,name,color,metallic=0.):
        mat=bpy.data.materials.new(name);mat.use_nodes=True
        bs=mat.node_tree.nodes['Principled BSDF']
        bs.inputs['Base Color'].default_value=(*color,1)
        bs.inputs['Metallic'].default_value=metallic;bs.inputs['Roughness'].default_value=.35
        return mat

    def ball(self,name,r,mat):
        bm=bmesh.new();bmesh.ops.create_uvsphere(bm,u_segments=20,v_segments=12,radius=r)
        mesh=bpy.data.meshes.new(name);bm.to_mesh(mesh);bm.free()
        mesh.materials.append(mat)
        for p in mesh.polygons:p.use_smooth=True
        return self.link(name,mesh)

    def curve(self,name,points,r,mat):
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.bevel_depth=r;data.bevel_resolution=2
        spline=data.splines.new('POLY');spline.points.add(len(points)-1)
        for p,xyz in zip(spline.points,points):p.co=(*xyz,1)
        data.materials.append(mat)
        return self.link(name,data)

    def arrow(self,name,mat,size=.12):
        bm=bmesh.new()
        bmesh.ops.create_cone(bm,cap_ends=True,cap_tris=True,segments=12,
                              radius1=size*.44,radius2=0.,depth=size)
        mesh=bpy.data.meshes.new(name);bm.to_mesh(mesh);bm.free();mesh.materials.append(mat)
        return self.link(name,mesh)

    def flatten_asset(self,filename):
        before=set(self.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(Path(self.job['style']['asset_root'])/filename))
        self.scene.view_layers[0].update()
        imported=[o for o in self.scene.objects if o not in before]
        meshes=[]
        for o in imported:
            if o.type=='MESH':
                mesh=o.data.copy();mesh.transform(o.matrix_world)
                o.parent=None;o.data=mesh;o.rotation_mode='XYZ';o.matrix_world=Matrix.Identity(4);meshes.append(o)
        for o in imported:
            if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
        return meshes

    @staticmethod
    def clip_mesh(mesh,front):
        bm=bmesh.new();bm.from_mesh(mesh)
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-5,
                              plane_co=(0,0,0),plane_no=(0,1,0),clear_inner=not front,clear_outer=front)
        bm.to_mesh(mesh);bm.free();mesh.update()

    def annulus(self,name,inner,outer,mat,y=-.015):
        verts=[];faces=[]
        for i in range(129):
            a=math.tau*i/128
            verts.extend([(inner*math.cos(a),y,inner*math.sin(a)),(outer*math.cos(a),y,outer*math.sin(a))])
        for i in range(128):faces.append((2*i,2*i+1,2*i+3,2*i+2))
        mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.materials.append(mat)
        return self.link(name,mesh)

    def build(self):
        self.story=Story(self.job['timeline'],self.job['canonical_fps'],self.job.get('camera_transition_seconds',.4))
        self.fades=[];self.tracked=[];self.color_sockets=[];self.field_shapes=[]
        def fade(obj,group):
            if not obj.data.materials:raise ValueError('missing material')
            for i in range(len(obj.data.materials)):
                socket=fade_material(obj,i);self.fades.append((socket,group))
            self.tracked.append(obj);return obj
        self.fade=fade
        self.earth_rig=self.link('EarthRig',None)
        earth=self.flatten_asset('earth.glb')[0]
        earth.data.transform(Matrix.Scale(.03,4))
        self.earth_back=earth;earth.name='Earth'
        self.rotating_surface=self.link('RotatingSurface',earth.data.copy())
        fade(self.rotating_surface,'surface')
        front=self.link('EarthFront',earth.data.copy())
        self.clip_mesh(earth.data,False);self.clip_mesh(front.data,True)
        self.earth_front=front
        fade(earth,'earth');fade(front,'front')
        # Assemble the source's actual mantle/outer-core/inner-core geometry,
        # with its original textures and colors. Only the source presentation
        # card and its exploded offsets are removed.
        parts=self.flatten_asset('earth_core_v2.glb')
        keep={prefix:next(o for o in parts if o.name.startswith(prefix))
              for prefix in ('Material_005','Material_006','Material_007','Material_009','Material_010','Material_012','Material_013')}
        for o in parts:
            if o not in keep.values():bpy.data.objects.remove(o,do_unlink=True)
        self.outer_core=self.link('OuterCoreRig',None)
        self.inner_core=keep['Material_013'];self.inner_core.name='InnerCore'
        for prefix,o in keep.items():
            if prefix=='Material_013':
                lo=min(v.co.y for v in o.data.vertices);hi=max(v.co.y for v in o.data.vertices)
                shift=-(lo+hi)/2
            elif prefix in ('Material_009','Material_010','Material_012'):
                shift=.872;o.parent=self.outer_core
            else:shift=.489
            o.data.transform(Matrix.Scale(3.,4)@Matrix.Translation((0,shift,0)))
            if prefix=='Material_005':o.name='Mantle'
            if prefix=='Material_009':o.name='OuterCore'
            fade(o,'cut')
        # Feedback chose removal of the supplied photogrammetry model instead
        # of painting a replacement dial over it. Use one clean compass diagram;
        # there is no imported casing, lid, or baked arrow behind this dial.
        self.compass=self.link('Compass',None);self.compass.location=(-4,-3,0)
        self.tracked.append(self.compass)
        dialmat=self.solid('Ivory compass dial',(.91,.93,.84))
        rim=self.solid('Brass compass rim',(.62,.39,.10),.7)
        dial=self.annulus('CompassDial',.0,1.18,dialmat,y=-.70);dial.parent=self.compass;fade(dial,'compass')
        outer=self.annulus('CompassRim',1.18,1.30,rim,y=-.69);outer.parent=self.compass;fade(outer,'compass')
        self.needle=self.link('CompassNeedle',None);self.needle.parent=self.compass;self.needle.location=(0,-.79,0)
        for name,sign,color in [('NorthNeedle',1,(.95,.12,.075)),('SouthNeedle',-1,(.73,.79,.86))]:
            mesh=bpy.data.meshes.new(name)
            mesh.from_pydata([(-.14,0,0),(.14,0,0),(0,0,sign*.94)],[],[(0,1,2)])
            mesh.materials.append(self.solid(name,color,.25))
            o=self.link(name,mesh);o.parent=self.needle;fade(o,'compass')
        hub=self.ball('NeedlePivot',.085,rim);hub.parent=self.needle;hub.location=(0,-.04,0);fade(hub,'compass')
        self.tracked.append(self.needle)
        # Geographic reference is an unlettered long radial mark, revealed in
        # scene 3. A small offset makes declination visible without false precision.
        mark=self.curve('TrueNorthMark',[(0,-.73,1.02),(0,-.73,1.14)],.022,self.material((.14,.23,.30)))
        mark.parent=self.compass;fade(mark,'compass')
        # Tangent to the equatorial surface. The enlarged compass is one
        # explanatory diagram; its needle and the local field arrows agree.
        localmat=self.material((.83,.97,1.),1.5)
        local=self.curve('LocalHorizontalField',[(1.6,-3.20,-.95),(1.79,-3.20,.95)],.02,localmat)
        fade(local,'local_field')
        for i,z in enumerate((-.65,.0,.65)):
            arrow=self.arrow(f'LocalFieldDirection{i}',localmat,.22)
            arrow.location=(1.695+.1*z,-3.20,z)
            arrow.rotation_euler=Vector((math.sin(.10),0,math.cos(.10))).to_track_quat('Z','Y').to_euler()
            fade(arrow,'local_field')
        # One supplied magnet, scaled to the explanatory stage; licensing stays
        # in the GLB source metadata for upload-text.
        magnet=self.flatten_asset('alnico_cylindrical_bar_magnet.glb')[0]
        low=Vector(tuple(min(v.co[i] for v in magnet.data.vertices) for i in range(3)))
        high=Vector(tuple(max(v.co[i] for v in magnet.data.vertices) for i in range(3)))
        magnet.data.transform(Matrix.Scale(3./max(high-low),4)@Matrix.Translation(-(low+high)/2))
        axis=max(range(3),key=lambda i:high[i]-low[i])
        magnet.name='BarMagnet'
        magnet.rotation_euler=({0:(0,math.pi/2,0),1:(math.pi/2,0,0),2:(0,0,0)}[axis])
        self.magnet=magnet;fade(magnet,'magnet')
        blue=self.material((.12,.73,1.),1.3)
        gold=self.material((1.,.70,.09),1.25)
        white=self.material((.75,.94,1.),1.25)
        self.flow=[];self.flow_paths=[]
        for lane in range(8):
            path=self.curve(f'FlowPath{lane}',[flow_point(lane,FLOW_PERIOD*i/96) for i in range(97)],.010,blue)
            fade(path,'flow');self.flow_paths.append(path)
            for j in range(2):
                o=self.ball(f'FlowTracer{lane}_{j}',.057,blue);fade(o,'flow');self.flow.append((o,lane,j/2))
        parcelmat=self.solid('Parcel temperature', (1.,.15,.04))
        parcelmat.node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value=.25
        parcelmat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.65
        self.parcel=self.ball('SingleFluidParcel',.17,parcelmat);fade(self.parcel,'single')
        self.parcel_shader=self.parcel.data.materials[0].node_tree.nodes['Principled BSDF']
        self.color_sockets=[self.parcel_shader.inputs['Base Color'],self.parcel_shader.inputs['Emission Color']]
        self.parcel_path=self.curve('SingleParcelPath',[parcel_state(i/96)[0] for i in range(97)],.008,self.material((.68,.70,.74),.15))
        fade(self.parcel_path,'single')
        self.seed=[]
        for x in (-.70,0,.70):
            o=self.curve(f'SeedField{x}',[(x,-.84,-1.30),(x,-.84,0),(x,-.84,1.30)],.013,blue)
            fade(o,'seed');self.seed.append(o)
        self.currents=[];self.charges=[]
        for i,z in enumerate((-.55,.15,.75)):
            radius=math.sqrt(max(.1,1.25**2-z*z))
            pts=[(radius*math.cos(a*math.tau/96),radius*math.sin(a*math.tau/96),z) for a in range(97)]
            o=self.curve(f'CurrentLoop{i}',pts,.019,gold);fade(o,'current');self.currents.append(o)
            for j in range(4):
                o=self.ball(f'CurrentPulse{i}_{j}',.043,gold);fade(o,'current')
                self.charges.append((o,radius,z,j/4))
        self.field=[];self.field_dots=[]
        for side in range(8):
            azimuth=side*math.tau/8
            for n,L in enumerate((3.9,5.05,6.2)):
                pts=field_path(L,azimuth)
                o=self.curve(f'FieldLine{side}_{n}',pts,.011,blue);fade(o,'field');self.field.append(o)
                o.shape_key_add(name='Dipole')
                key=o.shape_key_add(name='SolarWindTail')
                for point,p in zip(key.data,magnetosphere_path(pts,1)):point.co=p
                self.field_shapes.append(key)
                o=self.arrow(f'FieldDirection{side}_{n}',white,.16);fade(o,'field')
                self.field_dots.append((o,pts,(side*.12+n*.19)%1,True))
        self.magnet_fields=[];self.magnet_dots=[]
        for side in range(8):
            azimuth=side*math.tau/8
            for n,L in enumerate((3.9,5.05,6.2)):
                pts=field_path(L,azimuth)
                o=self.curve(f'EarthComparisonField{side}_{n}',pts,.011,blue);fade(o,'compare')
                o=self.arrow(f'EarthComparisonDirection{side}_{n}',white,.14);fade(o,'compare')
                self.field_dots.append((o,pts,side*.15+n*.20,False))
        for side,azimuth in enumerate((0,math.pi)):
            for n,L in enumerate((1.65,2.1,2.6)):
                pts=bar_field_path(L,azimuth)
                o=self.curve(f'MagnetField{side}_{n}',pts,.014,blue);fade(o,'compare');self.magnet_fields.append(o)
                o=self.arrow(f'MagnetFieldDirection{side}_{n}',white,.14);fade(o,'compare');self.magnet_dots.append((o,pts,side*.15+n*.20))
        self.wire_root=self.link('WireDemo',None)
        self.wire=self.curve('CurrentWire',[(0,0,z) for z in (-1.15,0,1.15)],.045,self.solid('Copper wire',(.66,.27,.07),.65))
        self.wire.parent=self.wire_root;fade(self.wire,'wire')
        self.wire_arrows=[]
        for i,z in enumerate((-.7,0,.7)):
            pts=[wire_field_point(a/64,z) for a in range(65)]
            o=self.curve(f'WireField{i}',pts,.015,blue);o.parent=self.wire_root;fade(o,'wire')
            o=self.arrow(f'WireFieldArrow{i}',white,.18);o.parent=self.wire_root;fade(o,'wire');self.wire_arrows.append((o,z,i/3))
        self.wire_pulses=[]
        for i in range(3):
            o=self.ball(f'WirePulse{i}',.066,gold);o.parent=self.wire_root;fade(o,'wire');self.wire_pulses.append(o)
        self.heat=[]
        orange=self.material((1.,.26,.05),1.4)
        for i in range(6):
            o=self.ball(f'WireHeatOut{i}',.075,orange);o.parent=self.wire_root;fade(o,'heat');self.heat.append(o)
        self.energy=[]
        for i in range(8):
            o=self.ball(f'BuoyancyEnergy{i}',.055,orange);fade(o,'energy');self.energy.append(o)
        self.sun=self.flatten_asset('sun.glb')[0];self.sun.name='Sun'
        low=Vector(tuple(min(v.co[i] for v in self.sun.data.vertices) for i in range(3)))
        high=Vector(tuple(max(v.co[i] for v in self.sun.data.vertices) for i in range(3)))
        self.sun.data.transform(Matrix.Scale(8./max(high-low),4)@Matrix.Translation(-(low+high)/2))
        for material in self.sun.data.materials:
            shader=material.node_tree.nodes.get('Principled BSDF')
            if shader:
                base=shader.inputs['Base Color']
                if base.is_linked:material.node_tree.links.new(base.links[0].from_socket,shader.inputs['Emission Color'])
                shader.inputs['Emission Strength'].default_value=1.1
        fade(self.sun,'sun');self.sun.location=(-12,2,0)
        self.wind=[]
        for lane in range(6):
            for j in range(3):
                o=self.arrow(f'SolarWindParticle{lane}_{j}',orange,.20);fade(o,'solar_wind')
                self.wind.append((o,lane,j/3))
        self.stars=[]
        for i in range(28):
            o=self.ball(f'BackgroundStar{i}',.023+(i%3)*.009,localmat)
            o.location=(-20+(i*7.3)%43,14,-8+(i*3.7)%17)
            fade(o,'sun');self.stars.append(o)
        # Keep all Earth-related objects in the same persistent rig. Moving the
        # comparison stage moves the complete field and core, not the planet
        # separately from its own paths.
        excluded={self.compass,self.needle,self.magnet,self.wire_root,self.sun,*self.stars,*[o for o,_,_ in self.wind],*self.magnet_fields,*[o for o,_,_ in self.magnet_dots]}
        for o in self.tracked:
            if o not in excluded and o.parent is None:o.parent=self.earth_rig
        self.outer_core.parent=self.earth_rig
        self.animated=list(dict.fromkeys([self.camera,self.earth_rig,self.outer_core,self.compass,self.needle,self.magnet,self.wire_root,*self.tracked]))
        self.callouts=CalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job),{o.name:o for o in self.scene.objects})
        self.sample(0)
        for image in bpy.data.images:
            if image.source=='FILE' and not image.packed_file:image.pack()

    def sample(self,frame):
        st=self.story.state(frame);cut=st['cutaway'];t=st['time']
        compare=st['compare'];hypothesis=st['hypothesis']
        show_cut=cut*(1-compare);surface=st['full_surface']*(1-compare)
        outer_view=max(0.,min(1.,(st['camera'][2]-9.)/4.))
        outer_view=outer_view*outer_view*(3-2*outer_view)
        values=dict(earth=(1.-.70*hypothesis)*(1-surface),front=((1-cut)*(1-.70*hypothesis)+compare*cut)*(1-surface),
                    cut=show_cut*(1-.80*hypothesis),flow=show_cut*st['flow'],seed=show_cut*st['seed']*.55,
                    current=show_cut*st['current'],field=st['field']*(1-compare)*outer_view,magnet=st['magnet'],wire=st['wire'],
                    energy=show_cut*st['energy'],compass=st['compass'],compare=compare,single=show_cut*st['single'],heat=st['wire_heat'],surface=max(.35*st['rotation'],surface),
                    local_field=st['local_field']*st['compass'],sun=st['sun'],solar_wind=st['solar_wind'])
        for socket,group in self.fades:socket.default_value=values[group]
        self.compass.rotation_euler.y=st['body_turn']
        self.needle.rotation_euler.y=st['needle_angle']-st['body_turn']+.10
        self.compass.location=(0,-2.5,0);self.compass.scale=(.8,)*3
        self.earth_rig.location=(-3.7*compare,0,0)
        self.earth_rig.scale=(1.-.30*compare,)*3
        self.magnet.location=(3.8*compare,-.9*(1-compare),0)
        self.magnet.scale=(.8,)*3
        for o in self.magnet_fields:o.location=(3.8,0,0)
        self.wire_root.location=(8.5,-.6,0);self.wire_root.scale=(1.35,)*3
        explode=st['explode']
        self.outer_core.location=(1.8*explode,-.1*explode,0)
        self.inner_core.location=(-1.8*explode,-.3*explode,0)
        self.inner_core.rotation_euler.z=t*.035
        # A complete translucent source surface rotates without moving the
        # cut plane or dragging the explanatory flow paths with the camera.
        self.rotating_surface.rotation_euler.z=t*.18
        for o,lane,offset in self.flow:o.location=flow_point(lane,t,offset)
        for o,r,z,offset in self.charges:
            a=-math.tau*(t/7+offset);o.location=(r*math.cos(a),r*math.sin(a),z)
        for key in self.field_shapes:key.value=st['magnetosphere']
        for o,points,offset,deform in self.field_dots:
            q=(t/11+offset)%1;u=q*(len(points)-1);i=min(len(points)-2,int(u));a=u-i
            p1,p2=points[i:i+2]
            if deform:p1,p2=magnetosphere_path([p1,p2],st['magnetosphere'])
            o.location=Vector(p1).lerp(Vector(p2),a)
            o.rotation_euler=(Vector(p2)-Vector(p1)).to_track_quat('Z','Y').to_euler()
        for o,points,offset in self.magnet_dots:
            u=((t/7+offset)%1)*(len(points)-1);i=min(len(points)-2,int(u));a=u-i
            o.location=Vector((3.8,0,0))+Vector(points[i]).lerp(Vector(points[i+1]),a)
            o.rotation_euler=(Vector(points[i+1])-Vector(points[i])).to_track_quat('Z','Y').to_euler()
        a,z=self.story.spans[10];q=(frame-a)/max(1,z-a-1)
        p,temp=parcel_state(q);self.parcel.location=p
        color=(.08+.92*temp,.35-.20*temp,.96-.92*temp,1)
        for socket in self.color_sockets:socket.default_value=color
        for i,o in enumerate(self.wire_pulses):o.location=(0,0,-1.05+((t*.36+i*.7)%2.1))
        for o,z,offset in self.wire_arrows:
            p=wire_field_point(t/5+offset,z);o.location=p
            o.rotation_euler=Vector((-p[1],p[0],0)).to_track_quat('Z','Y').to_euler()
        for i,o in enumerate(self.heat):
            q=(t/2+i/6)%1;a=i*math.tau/6;r=.12+q*1.25
            o.location=(r*math.cos(a),r*math.sin(a),-.8+i*.32)
            o.scale=(.65+q*.7,)*3
        for i,o in enumerate(self.energy):
            q=(t/5+i/8)%1;phi=-math.pi+.15+i*(math.pi-.3)/7
            r=1.02+q*.48;o.location=(r*math.cos(phi),r*math.sin(phi),-.3+.6*q)
        self.sun.rotation_euler.z=t*.025
        for o,lane,offset in self.wind:
            q=(t/7+offset+lane*.08)%1
            o.location=solar_wind_point(q,lane)
            a=Vector(solar_wind_point(max(0,q-.002),lane));b=Vector(solar_wind_point(min(1,q+.002),lane))
            o.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler()
        eye,look,scale=st['camera'];self.camera.location=eye
        self.camera.rotation_euler=(Vector(look)-Vector(eye)).to_track_quat('-Z','Y').to_euler()
        profile=self.job.get('variant_profile',{})
        self.camera.data.ortho_scale=scale*({'wide':1.08,'close':.95,'restrained':1.03}.get(profile.get('camera_profile'),1))
        self.last_state=st
        entry=self.job['canonical_state_cache'][frame]
        return entry,self.animated

    def extra_state(self):
        return self.last_state

    def graph_text_state(self):
        return []

    def bake(self):
        from bpy_extras import anim_utils
        self.sample(0)
        for obj in self.animated:
            for prop in ('location','rotation_euler','scale'):obj.keyframe_insert(data_path=prop,frame=1)
        self.camera.data.keyframe_insert(data_path='ortho_scale',frame=1)
        owners=[*self.animated,self.camera.data]
        for key in self.field_shapes:
            key.keyframe_insert(data_path='value',frame=1);owners.append(key.id_data)
        for obj in self.tracked:
            for socket in animated_sockets(obj):
                socket.keyframe_insert(data_path='default_value',frame=1)
            if obj.type in {'MESH','CURVE'}:
                owners.extend(mat.node_tree for mat in obj.data.materials if mat.use_nodes)
        for socket in self.color_sockets:socket.keyframe_insert(data_path='default_value',frame=1)
        channels=[]
        for owner in dict.fromkeys(owners):
            ad=owner.animation_data
            if not ad or not ad.action:continue
            bag=anim_utils.action_get_channelbag_for_slot(ad.action,ad.action_slot)
            if bag is None:continue
            for curve in bag.fcurves:
                value=owner.path_resolve(curve.data_path)
                channels.append((curve,owner,curve.data_path,curve.array_index,hasattr(value,'__len__')))
        values=[array('f') for _ in channels];count=self.job['duration_frames']
        for frame in range(count):
            self.sample(frame)
            for (_,owner,path,index,vec),column in zip(channels,values):
                v=owner.path_resolve(path);column.append(float(v[index] if vec else v))
        for (curve,_,_,_,_),column in zip(channels,values):
            if min(column)==max(column):continue
            points=curve.keyframe_points;points.add(count-len(points))
            co=array('f',[0.])*(2*count);co[0::2]=array('f',range(1,count+1));co[1::2]=column
            points.foreach_set('co',co)
            for p in points:p.interpolation='LINEAR'
            curve.update()
        self.scene.frame_set(1);self.sample(0);bpy.ops.file.pack_all()
