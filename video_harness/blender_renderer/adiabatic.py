"""Native Blender teaching scenes for gas expansion. No rendered text.

World +Z is up, +X right; camera looks from negative Y. Dot size, density and
colour are explanatory encodings. Clouds and particles are not to scale.
"""
import math
import random
import bpy
from mathutils import Vector
try:
    from .scene import SpectralGallery
    from .animated_materials import fade_material
    from .adiabatic_math import state_at, particle_position, elastic_velocities, smooth, sphere_particle
except ImportError:
    from scene import SpectralGallery
    from animated_materials import fade_material
    from adiabatic_math import state_at, particle_position, elastic_velocities, smooth, sphere_particle


class AdiabaticGallery(SpectralGallery):
    def configure(self):
        super().configure()
        self.scene.name = 'Adiabatic expansion'
        self.scene.world.use_nodes = True
        self.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.48,.69,.86,1)
        self.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.7
        self.scene.eevee.taa_render_samples=16
        self.camera.location=(0,-20,7)
        self.camera.data.ortho_scale=12
        self.scene.view_settings.view_transform='Standard'
        self.scene.view_settings.look='None'
        for ob in self.scene.objects:
            if ob.type=='LIGHT':
                ob.location=(-4,-7,10);ob.data.energy=1000;ob.data.size=7

    def surface(self,name,color,metallic=0.):
        mat=bpy.data.materials.new(name);mat.use_nodes=True
        bsdf=mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value=(*color,1)
        bsdf.inputs['Roughness'].default_value=.32
        bsdf.inputs['Metallic'].default_value=metallic
        return mat

    def sphere(self,name,r,mat,loc=(0,0,0)):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,radius=r,location=loc)
        obj=bpy.context.object;obj.name=name;obj.data.materials.append(mat)
        for f in obj.data.polygons:f.use_smooth=True
        return obj

    def box(self,name,loc,scale,mat):
        bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
        obj=bpy.context.object;obj.name=name;obj.scale=scale;obj.data.materials.append(mat)
        bevel=obj.modifiers.new('Soft edges','BEVEL');bevel.width=.08;bevel.segments=3
        obj.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
        return obj

    def cage(self,name,r,color,center=(0,0,0),dashed=False):
        objects=[]
        for plane in range(3):
            for segment in range(12 if dashed else 1):
                begin=segment/12*math.tau if dashed else 0
                end=begin+math.tau/18 if dashed else math.tau
                pts=[]
                for k in range(33):
                    a=begin+(end-begin)*k/32
                    p=[r*math.cos(a),r*math.sin(a),0]
                    if plane==1:p=[p[0],0,p[1]]
                    if plane==2:p=[0,p[0],p[1]]
                    pts.append(tuple(p[i]+center[i] for i in range(3)))
                objects.append(self.path(name+f'-{plane}-{segment}',pts,color,.018 if dashed else .026))
        return objects

    def build(self):
        self.env=self.job['timeline'][0]['controller_options']['environment']
        self.asset_mode=False
        if self.job['timeline'][0]['controller_options'].get('use_assets') and self.env in ('sky','balloon','atmosphere','parcel'):
            try:from . import adiabatic_assets
            except ImportError:import adiabatic_assets
            adiabatic_assets.build(self);return
        self.objects=[]
        self.gasmat=self.surface('Thermal motion warm coral',(.92,.34,.16))
        self.coldmat=self.surface('Water droplets',(.23,.66,.94))
        self.whitemat=self.surface('Cloud white',(.94,.98,1))
        self.darkmat=self.surface('Pressure apparatus',(.065,.15,.23),.4)
        self.goldmat=self.surface('Load brass',(.9,.56,.13),.6)
        self.floor=self.box('Ground',(0,4,-3),(30,25,.2),self.surface('Ground',(.27,.49,.38)))
        self.particles=[];self.boundary=[];self.clouds=[];self.outer=[]
        if self.env=='collision':
            self.ball=self.sphere('ball',.29,self.gasmat)
            self.panel=self.box('panel',(0,0,0),(.22,1.9,2.7),self.darkmat)
            self.wheels=[self.sphere('wheel-'+str(i),.25,self.darkmat,(0,y,-1.6)) for i,y in enumerate((-.7,.7))]
            self.floor.location.z=-1.95
            self.cart=self.box('cart',(0,0,-1.35),(1.2,2.,.18),self.darkmat)
            self.objects=[self.ball,self.panel,self.cart,*self.wheels]
            span=self.job['scene_spans'][0] if 'scene_spans' in self.job else None
            # Scene 16 begins at the third beat of this sequence.
            middle=[b for b in self.job['timeline'] if b['controller_options'].get('collision_impact')]
            self.impact=middle[0]['start_frame']/self.job['canonical_fps']+.8 if middle else 9
        else:
            for i in range(32):
                self.particles.append(self.sphere(f'molecule-{i:02}',.105,self.gasmat))
            if self.env=='piston':
                self.piston=self.box('piston',(0,0,1),(3.8,2.4,.22),self.darkmat)
                self.weight=self.box('weight',(0,0,1.5),(1.2,1.1,.85),self.goldmat)
                self.objects += [self.piston,self.weight]
                for x in (-2,2):
                    self.box('cylinder-wall',(x,0,0),(.12,2.6,5),self.darkmat)
                self.box('cylinder-base',(0,0,-2.5),(4.2,2.7,.2),self.darkmat)
            else:
                self.boundary=self.cage('parcel-guide' if self.env!='balloon' else 'rubber-cutaway',1,(.13,.43,.55),dashed=self.env!='balloon')
                self.objects+=self.boundary
            if self.env=='balloon':
                # A retained rear hemisphere makes the cutaway visibly rubber.
                vertices=[];faces=[]
                for j in range(17):
                    lat=-math.pi/2+j*math.pi/16
                    for k in range(25):
                        a=k*math.pi/24
                        vertices.append((math.cos(lat)*math.cos(a),math.cos(lat)*math.sin(a),math.sin(lat)))
                for j in range(16):
                    for k in range(24):
                        a=j*25+k;faces.append((a,a+1,a+26,a+25))
                mesh=bpy.data.meshes.new('rubber-cutaway-shell');mesh.from_pydata(vertices,[],faces)
                self.rubber=self.link('rubber-shell',mesh)
                mesh.materials.append(self.surface('Rubber turquoise',(.06,.48,.55)))
                for face in mesh.polygons:face.use_smooth=True
                self.boundary.append(self.rubber);self.objects.append(self.rubber)
                self.knot=self.sphere('balloon-knot',.14,self.darkmat);self.objects.append(self.knot)
                # Bottle and balloon share one bench. Camera follows the balloon;
                # the cutaway arcs are the retained rubber, not an atmospheric wall.
                pts=[(-5.5,0,-1.9),(-5.5,0,.5),(-5.05,0,1.05),(-5.05,0,1.6),(-4.35,0,1.6),(-4.35,0,1.05),(-3.9,0,.5),(-3.9,0,-1.9),(-5.5,0,-1.9)]
                self.path('bottle-profile',pts,(.13,.43,.55),.07)
                self.box('bottle-cap',(-4.7,0,1.65),(.85,.55,.25),self.coldmat)
                for i in range(12):
                    p=particle_position(i,0,.6)
                    self.sphere('bottle-air-'+str(i),.08,self.gasmat,(-4.7+p[0],p[1],p[2]-.2))
            if self.env in ('sky','atmosphere','parcel','cloud','balloon'):
                rng=random.Random(41)
                for i in range(36):
                    ob=self.sphere('surrounding-air-'+str(i),.065,self.surface('Surrounding '+str(i),(.19,.44,.64)))
                    self.outer.append((ob,(rng.uniform(-5,5),rng.uniform(-2,3),rng.uniform(-2.3,5))))
                self.objects += [o for o,p in self.outer]
            if self.env in ('sky','parcel','cloud'):
                rng=random.Random(81)
                for i in range(15):
                    p=(rng.uniform(-2.0,2.0),rng.uniform(-.7,.7),rng.uniform(-.75,.9))
                    self.clouds.append((self.sphere('cloud-droplet-cluster-'+str(i),rng.uniform(.85,1.15),self.whitemat),p))
                self.nucleus=self.sphere('condensation-nucleus',.13,self.darkmat)
                self.droplet=self.sphere('water-droplet',.5,self.coldmat)
                self.objects += [self.nucleus,self.droplet,*[o for o,p in self.clouds]]
                self.vapor=[]
                for i in range(9):
                    self.vapor.append(self.sphere('water-vapour-'+str(i),.09,self.coldmat))
                self.objects += self.vapor
                # Sixfold ice crystal is separate from dry-air molecules.
                self.ice=[]
                for i in range(6):
                    a=i*math.tau/6
                    ob=self.path('ice-arm-'+str(i),[(0,0,0),(.65*math.cos(a),0,.65*math.sin(a))],(.68,.9,1),.04)
                    self.ice.append(ob)
                self.objects+=self.ice
            self.objects += self.particles
        self.diagram_fades=[]
        if self.clouds:
            socket=fade_material(self.particles[0]);self.diagram_fades.append(socket)
            self.gasmat=self.particles[0].data.materials[0]
            for ob in self.particles[1:]:ob.data.materials[0]=self.gasmat
            for ob in [*self.boundary,*[o for o,p in self.outer],self.nucleus,self.droplet,*self.ice]:
                self.diagram_fades.append(fade_material(ob))
        self.states=[state_at(self.job,f) for f in range(self.job['duration_frames'])]
        phase=0.;self.phases=[]
        for s in self.states:
            self.phases.append(phase)
            phase+=1.8*s['speed']/s['volume']**(1/3)/self.job['canonical_fps']

    def sample(self,frame):
        result=self.sample_scene(frame)
        try:from .adiabatic_match import apply
        except ImportError:from adiabatic_match import apply
        apply(self,frame)
        return result

    def sample_scene(self,frame):
        if self.asset_mode:
            try:from . import adiabatic_assets
            except ImportError:import adiabatic_assets
            return adiabatic_assets.sample(self,frame)
        s=self.states[frame]; t=frame/self.job['canonical_fps'];self.current=s
        z=s['altitude'];r=1.55*s['volume']**(1/3)
        profile=self.job.get('variant_profile',{})
        zoom={'wide':1.08,'close':.94,'restrained':1.03}.get(profile.get('camera_profile'),1.)
        self.camera.data.ortho_scale=s['camera_scale']*zoom
        target=Vector((s['focus_x'],0,s['focus_z']))
        self.camera.location=target+Vector((7 if self.env=='collision' else 0,-20,2.))
        self.camera.rotation_euler=(target-self.camera.location).to_track_quat('-Z','Y').to_euler()
        if self.env=='collision':
            u=.28;v,w=elastic_velocities(1,4,u,0);dt=t-self.impact
            self.ball.location=(-.4+(u*dt if dt<0 else v*dt),0,0)
            self.panel.location.x=max(0,dt)*w
            self.cart.location.x=self.panel.location.x
            for wheel in self.wheels:
                wheel.location.x=self.panel.location.x;wheel.rotation_euler.y=-max(0,dt)*w/.25
        else:
            if self.env=='balloon':
                r=1.05+.5*s['inflate'];self.knot.location=(0,0,-r-.1)
            for i,ob in enumerate(self.particles):
                p=sphere_particle(i,self.phases[frame]) if self.env=='balloon' else particle_position(i,self.phases[frame],1)
                # Smooth cube-to-ball mapping keeps illustrative particles within
                # the cutaway envelope at every requested frame.
                p=tuple(v/(max(1.,sum(q*q for q in p)**.5)) for v in p)
                if self.env=='piston':
                    h=2.3*s['volume'];ob.location=(p[0]*1.7,p[1],-2.35+(p[2]+1)*.5*(h-.18))
                else:
                    extent=r-.11 if self.env=='balloon' else r*.88
                    ob.location=(p[0]*extent,p[1]*extent,p[2]*extent+z)
            for ob in self.boundary:
                ob.scale=(r,r,r);ob.location.z=z
            if self.env=='piston':
                h=2.3*s['volume'];self.piston.location.z=-2.35+h;self.weight.location.z=self.piston.location.z+.57
            for ob,p in self.outer:
                # Advected surrounding parcels move aside as the tracked parcel grows.
                x,y,zz=p;d=max(.01,(x*x+y*y+(zz-z)**2)**.5)
                push=max(1,(r+.45)/d)
                ob.location=(x*push,y*push,z+(zz-z)*push)
            bsdf=self.gasmat.node_tree.nodes.get('Principled BSDF')
            cold=min(1,max(0,(1-s['temperature'])*3))
            bsdf.inputs['Base Color'].default_value=(.92-.72*cold,.34+.28*cold,.16+.69*cold,1)
            if self.clouds:
                c=s['cloud'];detail=s['detail']
                for socket in self.diagram_fades:socket.default_value=1-smooth((c-.8)/.2)
                for ob,p in self.clouds:
                    size=max(.001,smooth((c-.3)/.7))
                    ob.scale=(size,size,size);ob.location=(p[0],p[1],z+p[2])
                self.nucleus.location=(0,-.4,z);self.nucleus.scale=(max(.001,detail),)*3
                self.droplet.location=(0,-.4,z);self.droplet.scale=(max(.001,detail*c*.95),)*3
                for i,ob in enumerate(self.vapor):
                    a=i*math.tau/len(self.vapor)+t*.14;rad=1.3*(1-smooth(c/.5))+.18
                    ob.location=(rad*math.cos(a),-.4+rad*.25*math.sin(a),z+rad*math.sin(a))
                    ob.scale=(max(.001,detail*(1-smooth(c/.5))),)*3
                for ob in self.ice:
                    ob.location=(2,-.7,z+.5);ob.scale=(max(.001,smooth((c-.65)/.35)),)*3
        return self.job['canonical_state_cache'][frame],[*self.objects,self.camera]

    def extra_state(self):
        return dict(environment=self.env,**self.current)

    def bake(self):
        super().bake()
        if self.env!='collision':
            socket=self.gasmat.node_tree.nodes.get('Principled BSDF').inputs['Base Color']
            for f in range(self.job['duration_frames']):
                self.sample(f);socket.keyframe_insert(data_path='default_value',frame=f+1)
                for extra in getattr(self,'extra_sockets',[]):extra.keyframe_insert(data_path='default_value',frame=f+1)
