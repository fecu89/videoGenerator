"""Native Blender classroom/globe explanation of conservative poleward transport.

Uses the supplied Classroom/Earth assets and the Roman Coins textures via the
existing classroom importer. Asset-derived solid coin discs stay countable.
The educational flow width is an idealized integral, not measured transport.
"""
import math
from pathlib import Path
import bpy
import bmesh
from mathutils import Matrix,Vector
from transfer_equation_story import TransferEquationStoryGallery
from callout import CalloutLayer,labels_from_job
import energy_transport_math as em


class EnergyTransportGallery(TransferEquationStoryGallery):
    def import_flat(self,filename,scale=1.):
        # Respect this run's immutable asset copies, including their attribution.
        before=set(self.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(Path(self.job['style']['asset_root'])/filename))
        self.scene.view_layers[0].update()
        imported=[o for o in self.scene.objects if o not in before]
        meshes=[o for o in imported if o.type=='MESH']
        for obj in meshes:
            data=obj.data.copy()
            data.transform(Matrix.Scale(scale,4)@obj.matrix_world)
            obj.parent=None;obj.data=data;obj.matrix_world=Matrix.Identity(4)
        for obj in imported:
            if obj not in meshes:bpy.data.objects.remove(obj,do_unlink=True)
        return meshes

    def solid(self,name,color,metal=0.):
        mat=bpy.data.materials.new(name);mat.use_nodes=True
        bs=mat.node_tree.nodes['Principled BSDF']
        bs.inputs['Base Color'].default_value=(*color,1)
        bs.inputs['Metallic'].default_value=metal
        bs.inputs['Roughness'].default_value=.44
        return mat

    def ball(self,name,position,scale,material):
        bm=bmesh.new();bmesh.ops.create_uvsphere(bm,u_segments=20,v_segments=12,radius=1)
        data=bpy.data.meshes.new(name);bm.to_mesh(data);bm.free()
        data.materials.append(material)
        for p in data.polygons:p.use_smooth=True
        obj=self.link(name,data);obj.location=position;obj.scale=scale
        return obj

    def rod(self,name,a,b,r,mat):
        a,b=Vector(a),Vector(b)
        obj=self.cylinder(name,r,(b-a).length,mat,(a+b)/2,vertices=16)
        obj.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler()
        return obj

    def curve(self,name,points,r,mat):
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D'
        data.bevel_depth=r;data.bevel_resolution=2
        p=data.splines.new('POLY');p.points.add(len(points)-1)
        for v,co in zip(p.points,points):v.co=(*co,1)
        obj=self.link(name,data);data.materials.append(mat)
        return obj

    def build(self):
        self.scene.name='Midlatitude energy transport'
        self.scene.eevee.shadow_pool_size='2048'
        self.scene.eevee.taa_render_samples=32
        self.scene.view_settings.view_transform='AgX'
        self.scene.view_settings.look='AgX - Medium High Contrast'
        for o in list(self.scene.objects):
            if o.type=='LIGHT':bpy.data.objects.remove(o,do_unlink=True)
        self.camera.name='EnergyCamera'
        self.camera.data.type='PERSP';self.camera.data.clip_start=.03;self.camera.data.clip_end=150
        self.scene.world.use_nodes=True
        self.bg=self.scene.world.node_tree.nodes['Background']
        self.bg.inputs['Color'].default_value=(.12,.17,.25,1)
        self.bg.inputs['Strength'].default_value=.25
        self.story=em.Story(self.job['timeline'],self.job['canonical_fps'],self.job.get('camera_transition_seconds',.4))
        self.room_objects=[];self.room_lights=[];self.fade_sockets=[]
        self.build_coin_proto()
        self.build_classroom()
        # Keep one row of five desks; the last receives the four remaining coins.
        remove=[o for o in self.room_objects if o.get('lane_b') or o in [self.compare_desk,self.compare_chair,*self.desks[5:],*self.chairs[5:]]]
        for o in remove:
            self.room_objects.remove(o);bpy.data.objects.remove(o,do_unlink=True)
        self.desks=self.desks[:5];self.chairs=self.chairs[:5]
        for i,(desk,chair) in enumerate(zip(self.desks,self.chairs)):
            delta=chair.location-desk.location
            desk.location=(0,em.DESK_Y[i],0);chair.location=desk.location+delta
            desk.name=f'Desk{i}';chair.name=f'Chair{i}'
        # Scanned god-rays are baked presentation effects, not geometry used in
        # the explanation, and can obscure the coin count in close views.
        for o in list(self.room_objects):
            if o.get('godray'):
                self.room_objects.remove(o);bpy.data.objects.remove(o,do_unlink=True)
        bowl=self.solid('Spent-coin bowl',(.075,.12,.17),.4)
        self.bowls=[]
        for i,y in enumerate(em.DESK_Y):
            o=self.cylinder(f'SpentBowl{i}',.135,.025,bowl,(.43,y+.29,em.DESK_TOP+.003))
            self.bowls.append(o);self.room_objects.append(o)
        self.coins=[self.coin(f'Coin{i}','bronze') for i in range(9)]
        for o in self.coins:
            o.hide_render=False
            # Increase actual disc geometry as a single consistent teaching scale.
        self.coin_mesh.transform(Matrix.Scale(1.4,4))
        self.room_objects+=self.coins
        self.trace_material=self.emission('Transport trace',(1.,.55,.07),1.6,alpha=False)
        self.traces=[]
        for i,n in enumerate((3,5,6,4)):
            a=(-.72,em.DESK_Y[i],.85);b=(-.72,em.DESK_Y[i+1],.85)
            trace=self.rod(f'PassedAmount{i}',a,b,.014*n,self.trace_material)
            self.traces.append(trace);self.room_objects.append(trace)
        self.space_objects=[]
        self.build_globe()
        self.space_lights=[]
        for name,pos,energy,size in [('EarthKey',(-6,15,11),1700,6),('EarthFill',(5,15,5),900,5)]:
            light=bpy.data.lights.new(name,'AREA');light.energy=energy;light.size=size
            obj=self.link(name,light);obj.location=pos
            obj.rotation_euler=(Vector(em.EARTH_CENTER)-obj.location).to_track_quat('-Z','Y').to_euler()
            self.space_lights.append((light,energy))
        self.animated=[self.camera,*self.coins,*self.particles,self.earth]
        self.callouts=CalloutLayer(self);self.callouts.bind(labels_from_job(self.job),{o.name:o for o in self.scene.objects})
        self.sample(0)
        for image in bpy.data.images:
            if image.source=='FILE' and not image.packed_file:image.pack()

    @staticmethod
    def globe_point(lat,lon=0,radius=2.13):
        p,l=math.radians(lat),math.radians(lon)
        return (radius*math.cos(p)*math.sin(l),22-radius*math.cos(p)*math.cos(l),3+radius*math.sin(p))

    def build_globe(self):
        meshes=self.import_flat('earth.glb',.02)
        self.earth=meshes[0];self.earth.name='Earth';self.earth.location=em.EARTH_CENTER
        self.space_objects+=meshes
        for f in self.earth.data.polygons:f.use_smooth=True
        gold=self.emission('Poleward energy',(1.,.52,.035),2.,alpha=False)
        ringmat=self.emission('Maximum latitude',(1.,.83,.34),2.,alpha=False)
        faint=self.emission('Equator',(.36,.64,.80),.6,alpha=False)
        self.equator=self.curve('Equator',[self.globe_point(0,lon) for lon in range(0,361,3)],.012,faint)
        self.space_objects.append(self.equator)
        self.rings=[];self.ribbons=[]
        maximum=em.transport(em.PEAK_LATITUDE)
        for sign in (-1,1):
            pts=[self.globe_point(sign*em.PEAK_LATITUDE,lon) for lon in range(0,361,3)]
            ring=self.curve(f'PeakRing{sign}',pts,.023,ringmat)
            self.rings.append(ring);self.space_objects.append(ring)
            verts=[];faces=[]
            for lat in range(0,90):
                half=7*abs(em.transport(lat))/maximum
                for lon in (-half,half):verts.append(self.globe_point(sign*lat,lon,2.16))
            for i in range(89):faces.append((2*i,2*i+1,2*i+3,2*i+2))
            mesh=bpy.data.meshes.new('Transport ribbon');mesh.from_pydata(verts,[],faces);mesh.materials.append(gold)
            rib=self.link(f'EnergyRibbon{sign}',mesh);rib.visible_shadow=False
            self.ribbons.append(rib);self.space_objects.append(rib)
        white=self.emission('Moving energy packets',(1.,.94,.66),3.,alpha=False)
        self.particles=[]
        for sign in (-1,1):
            for j in range(12):
                o=self.ball(f'EnergyPacket{sign}_{j}',self.globe_point(sign*(j*7+1)),(.045,)*3,white)
                o.visible_shadow=False;self.particles.append(o);self.space_objects.append(o)
        # Both fluxes decrease poleward on the same geometric scale; absorbed
        # sunlight decreases faster, so the local budget changes sign.
        self.radiation=[]
        yellow=self.emission('Absorbed sunlight',(1.,.78,.12),1.6,alpha=False)
        red=self.emission('Energy emitted to space',(1.,.24,.075),1.2,alpha=False)
        for lat in (12,60):
            inc,out=em.radiation_fluxes(lat)
            p=Vector(self.globe_point(lat,-10))
            for kind,length,mat,dz in [('Incoming',inc,yellow,-.20),('Outgoing',out,red,.20)]:
                near=p+Vector((-.05,0,dz));far=near+Vector((-length,0,0))
                a,b=(far,near) if kind=='Incoming' else (near,far)
                direction=(b-a).normalized();end=b-direction*.23
                shaft=self.rod(f'{kind}{lat}',a,end,.035,mat)
                bpy.ops.mesh.primitive_cone_add(vertices=20,radius1=.10,radius2=0,depth=.23,location=end+direction*.115)
                head=bpy.context.object;head.name=f'{kind}Head{lat}';head.data.materials.append(mat)
                head.rotation_euler=direction.to_track_quat('Z','Y').to_euler()
                self.radiation += [shaft,head];self.space_objects += [shaft,head]

    def sample(self,frame):
        st=self.story.state(frame);room=st['classroom']
        for o in self.room_objects:o.hide_render=not room
        for o in self.space_objects:o.hide_render=room
        for light,energy in self.room_lights:light.energy=energy if room else 0.
        for light,energy in self.space_lights:light.energy=0. if room else energy
        self.bg.inputs['Strength'].default_value=.55 if room else .045
        for o,p in zip(self.coins,st['coins']):o.location=p;o.scale=(1.,1.,1.)
        for i,o in enumerate(self.traces):o.hide_render=not room or st['transferred'][i]<.98
        for o in self.radiation:
            o.hide_render=room or st['scene_id']<13
        for o in self.rings:o.hide_render=room or st['peak_reveal']<.01
        for index,o in enumerate(self.particles):
            sign=-1 if index<12 else 1
            lat=2+((index%12)*7+st['time']*8)%84
            o.location=self.globe_point(sign*lat,0,2.21)
            # The stream narrows approaching the pole, matching the budget integral.
            r=.025+.032*abs(em.transport(lat))/em.transport(em.PEAK_LATITUDE)
            o.scale=(r,r,r)
        eye,look,lens=st['camera'];self.camera.location=eye
        self.camera.rotation_euler=(Vector(look)-Vector(eye)).to_track_quat('-Z','Y').to_euler()
        self.camera.data.lens=lens
        self.scene.view_layers[0].update();self.state=st
        return self.job['canonical_state_cache'][frame],self.animated

    def extra_state(self):
        return dict(scene_id=self.state['scene_id'],coin_desks=self.state['coin_desks'],spent=self.state['spent'],
                    shadow_pool_mb=int(self.scene.eevee.shadow_pool_size),model='idealized conservative energy budget')

    def bake(self):
        # Include every canonical frame: editable native scene and render sampling
        # share the exact same object state, including the two intentional cuts.
        from array import array
        from bpy_extras import anim_utils
        self.sample(0)
        for obj in self.animated:
            for prop in ('location','rotation_euler','scale'):obj.keyframe_insert(data_path=prop,frame=1)
        visibility=list(dict.fromkeys(self.room_objects+self.space_objects))
        for obj in visibility:obj.keyframe_insert(data_path='hide_render',frame=1)
        self.camera.data.keyframe_insert(data_path='lens',frame=1)
        for light,_ in self.room_lights+self.space_lights:light.keyframe_insert(data_path='energy',frame=1)
        self.bg.inputs['Strength'].keyframe_insert(data_path='default_value',frame=1)
        owners=[*self.animated,*visibility,self.camera.data,self.scene.world.node_tree,*[x for x,_ in self.room_lights+self.space_lights]]
        channels=[]
        for owner in dict.fromkeys(owners):
            ad=owner.animation_data
            if not ad or not ad.action:continue
            bag=anim_utils.action_get_channelbag_for_slot(ad.action,ad.action_slot)
            for curve in bag.fcurves:
                value=owner.path_resolve(curve.data_path)
                channels.append((curve,owner,curve.data_path,curve.array_index,hasattr(value,'__len__')))
        values=[array('f') for _ in channels]
        count=self.job['duration_frames']
        for frame in range(count):
            self.sample(frame)
            for (_,owner,path,index,vec),column in zip(channels,values):
                v=owner.path_resolve(path);column.append(float(v[index] if vec else v))
        for (curve,_,path,_,_),column in zip(channels,values):
            if min(column)==max(column):continue
            points=curve.keyframe_points;points.add(count-len(points))
            co=array('f',[0.])*(2*count);co[0::2]=array('f',range(1,count+1));co[1::2]=column
            points.foreach_set('co',co)
            for p in points:p.interpolation='CONSTANT' if path=='hide_render' else 'LINEAR'
            curve.update()
        self.scene.frame_set(1);self.sample(0);bpy.ops.file.pack_all()
