"""Continuous native 3D journey: dispersion, diagnosis, atmosphere, atoms.

Spectral intensities, atmosphere thickness and atom sizes are illustrative.
Wavelengths use selected NIST H I / He I lines (air), rounded to 0.1 nm.
The prism separates wavelengths; the stellar atmosphere causes absorption.
"""
import math
import random
import bpy
from mathutils import Vector
try:
    from .spectra import smooth
    from .animated_materials import fade_material
except ImportError:
    from spectra import smooth
    from animated_materials import fade_material

H_NM=(410.2,434.0,486.1,656.3)
HE_NM=(447.1,587.6,667.8)
COLORS=[(.30,.04,.7),(.15,.15,1),(.025,.6,1),(.04,.85,.4),(.85,.9,.015),(1,.43,.015),(.87,.025,.01)]


def lerp(a,b,p):
    return Vector(a).lerp(Vector(b),p)


def spectral_color(u):
    t=max(0,min(1,u))*6;i=min(5,int(t));f=t-i
    return tuple(COLORS[i][k]*(1-f)+COLORS[i+1][k]*f for k in range(3))


class OpticsJourney:
    controllers=('spectra-dispersion','spectra-temperature-question','spectra-atmosphere','spectra-elements')

    def __init__(self,g):
        self.g=g;self.objects=[];self.rng=random.Random(5026)
        data=bpy.data.cameras.new('Optics journey camera');data.type='PERSP';data.lens=42;data.clip_end=500
        self.camera=g.link('Optics journey camera',data)
        marker=g.scene.timeline_markers.new('Optical journey',frame=1);marker.camera=self.camera
        g.scene.world.use_nodes=True;g.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.002,.006,.017,1)
        self.star=g.star('Optical journey star',-8,1.2,2.15,(.83,.9,1))
        self.halo=bpy.data.objects.get('Optical journey star glow')
        n=self.star.data.materials[0].node_tree.nodes;l=self.star.data.materials[0].node_tree.links
        emission=n['Emission'];source=emission.inputs['Strength'].links[0].from_socket
        twinkle=n.new('ShaderNodeMath');twinkle.operation='MULTIPLY';twinkle.name='Animated twinkle';twinkle.inputs[1].default_value=1
        l.new(source,twinkle.inputs[0]);l.new(twinkle.outputs[0],emission.inputs['Strength'])
        self.star['animated_socket']='Animated twinkle';self.star['animated_input']=1
        self.twinkle=twinkle.inputs[1]
        self.objects += [self.star,self.halo]
        self.optics=self.empty('Prism and beam assembly')
        self.build_prism()
        self.spectrum,self.lines=self.make_spectrum('Observed spectrum',9,1.6,H_NM)
        self.spec_label=self.label('스펙트럼',0,1.45,.52,parent=self.spectrum)
        self.abs_label=self.label('흡수선',0,-1.6,.48,parent=self.spectrum,color=(1,.66,.2))
        self.abs_opacity=fade_material(self.abs_label)
        self.question=self.label('흡수선은 어디에서 생겼을까?',0,-5.1,.65)
        self.question_opacity=fade_material(self.question)
        self.star_label=self.label('별빛',-8,4,.48)
        self.star_label_opacity=fade_material(self.star_label)
        self.build_atmosphere()
        self.build_atoms()
        self.build_diagnostic_traces()
        # Sparse depth points, independent of all explanatory objects.
        for i in range(75):
            x=self.rng.uniform(-30,30);y=self.rng.uniform(-18,18);z=self.rng.uniform(-14,-9)
            o=g.star('Optical background point',x,y,.014,(.12,.21,.34));o.location.z=z
        self.objects += [self.camera,self.optics,self.spectrum,self.question,self.star_label,self.abs_label]

    def empty(self,name):
        obj=self.g.link(name,None);self.objects.append(obj);return obj

    def label(self,body,x,y,size=.5,parent=None,color=(.72,.84,1)):
        obj=self.g.text(body,x,y,size,color)
        if parent:obj.parent=parent
        self.objects.append(obj)
        return obj

    def sphere(self,name,position,radius,color,parent=None):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=16,radius=radius,location=position)
        o=bpy.context.object;o.name=name
        for poly in o.data.polygons:poly.use_smooth=True
        if 'nucleus' in name or 'electron' in name:
            mat=bpy.data.materials.new(name+' lit surface');mat.use_nodes=True
            bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(*color,1)
            bsdf.inputs['Roughness'].default_value=.36;bsdf.inputs['Emission Color'].default_value=(*color,1);bsdf.inputs['Emission Strength'].default_value=.2
            o.data.materials.append(mat)
        else:o.data.materials.append(self.g.material(color,1.1))
        if parent:o.parent=parent
        self.objects.append(o);return o

    def path(self,name,points,color,radius=.035,parent=None):
        o=self.g.path(name,points,color,radius)
        if parent:o.parent=parent
        self.objects.append(o);return o

    def transparent(self,name,color,amount=.13):
        mat=bpy.data.materials.new(name);mat.use_nodes=True;mat.surface_render_method='BLENDED'
        n=mat.node_tree.nodes;n.clear();l=mat.node_tree.links
        clear=n.new('ShaderNodeBsdfTransparent');emit=n.new('ShaderNodeEmission');emit.inputs['Color'].default_value=(*color,1)
        mix=n.new('ShaderNodeMixShader');mix.inputs[0].default_value=amount;out=n.new('ShaderNodeOutputMaterial')
        l.new(clear.outputs[0],mix.inputs[1]);l.new(emit.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],out.inputs['Surface'])
        return mat

    def build_prism(self):
        vertices=[v for z in (-1.3,1.3) for v in [(-3.5,-.5,z),(-.5,-.5,z),(-2,3,z)]]
        mesh=bpy.data.meshes.new('Solid triangular prism');mesh.from_pydata(vertices,[],[(0,2,1),(3,4,5),(0,1,4,3),(1,2,5,4),(2,0,3,5)])
        o=self.g.link('Transparent glass prism',mesh);o.parent=self.optics
        mesh.materials.append(self.transparent('Prism glass',(.2,.65,.9),.13))
        for a,b in [(0,1),(1,2),(2,0),(3,4),(4,5),(5,3),(0,3),(1,4),(2,5)]:
            self.path('Prism edge',[vertices[a],vertices[b]],(.25,.65,.9),.026,self.optics)
        self.label('프리즘',-2,-1.4,.45,self.optics)
        self.white_start=Vector((-5.85,1.2,.3));self.white_end=Vector((-2.75,1.2,.3));self.exit=Vector((-1.3,.3,.3))
        self.path('Incident white light',[self.white_start,self.white_end],(.82,.9,1),.06,self.optics)
        self.path('Light inside glass',[self.white_end,self.exit],(.82,.9,1),.045,self.optics)
        self.rays=[]
        for i in range(28):
            u=i/27;end=Vector((.5+9*u,-.97,.43));color=spectral_color(u)
            self.path('Dispersed wavelength',[self.exit,end],tuple(c*.55 for c in color),.023,self.optics)
            photon=self.sphere('Dispersed light packet',self.exit,.055,color,self.optics)
            self.rays.append((photon,end,i/28))
        self.white_packets=[self.sphere('White light packet',self.white_start,.11,(.9,.94,1),self.optics) for _ in range(3)]

    def make_spectrum(self,name,width,height,wavelengths):
        root=self.empty(name+' frame')
        spec,_=self.g.spectrum(name,0,0,width,height,9000,elements='none');spec.parent=root
        self.objects.append(spec)
        # The same physical wavelength always maps to the same horizontal coordinate.
        lines=[]
        for nm in wavelengths:
            u=(nm-400)/300;color=spectral_color(u)
            line=self.g.rect(name+f' {nm:.1f} nm',width*(u-.5),0,.12,height*1.225,color,.54)
            line.parent=root;line.data.materials[0]=line.data.materials[0].copy();line['spectrum_color']=color;line['wavelength_nm']=nm
            self.g.line_strength(line,0);lines.append(line);self.objects.append(line)
        for y in (-height*.66,height*.66):self.path(name+' rail',[(-width/2-.15,y,.3),(width/2+.15,y,.3)],(.09,.23,.34),.024,root)
        return root,lines

    def build_atmosphere(self):
        self.shells=[]
        for radius,amount in [(2.30,.09),(2.57,.035)]:
            bpy.ops.mesh.primitive_uv_sphere_add(segments=72,ring_count=48,radius=radius)
            o=bpy.context.object;o.name='Stellar atmosphere layer';o.data.materials.append(self.transparent(o.name,(.13,.55,.95),amount))
            for face in o.data.polygons:face.use_smooth=True
            self.objects.append(o);self.shells.append(o)
        self.atmosphere_label=self.label('상대적으로 차가운 대기',-1,4.7,.52,color=(.2,.72,1))
        self.atmosphere_opacity=fade_material(self.atmosphere_label)
        self.light_label=self.label('대기를 통과하는 별빛',3,-.7,.48)
        self.light_label.location.z=6
        self.light_opacity=fade_material(self.light_label)
        self.atmosphere_beams=self.empty('Escaping light beams')
        for y in (.1,.85,1.6):
            self.path('Escaping white beam',[(-7,y,6),(6.5,y,6)],(.55,.65,.8),.027,self.atmosphere_beams)
        self.escape_packets=[]
        for i in range(9):
            o=self.sphere('Escaping starlight packet',(0,0,0),.105,(.95,.97,1),self.atmosphere_beams)
            self.escape_packets.append((o,i/9,i%3))
        self.gas=self.empty('Atmospheric gas')
        self.gas_particles=[]
        for i in range(35):
            pos=Vector((self.rng.uniform(-3.6,-.8),self.rng.uniform(-.4,3.2),self.rng.uniform(4.8,6.2)))
            o=self.sphere('Atmospheric atom',pos,.065,(.18,.49,.7),self.gas);self.gas_particles.append((o,pos,i))

    def build_atoms(self):
        self.atom_roots=[];self.electrons=[];self.orbits=[]
        for row,(label,count,color) in enumerate([('수소 · H',1,(.18,.72,1)),('헬륨 · He',2,(1,.61,.18))]):
            root=self.empty(label+' atom');self.atom_roots.append(root)
            for k in range(1 if count==1 else 4):
                self.sphere(label+' nucleus',(math.cos(k*2.4)*.17,math.sin(k*2.4)*.17,0),.24,color,root)
            for k in range(count):
                points=[(1.13*math.cos(a*math.tau/96),.82*math.sin(a*math.tau/96),.6*math.sin(a*math.tau/96+k)) for a in range(97)]
                self.path(label+' orbital guide',points,tuple(c*.45 for c in color),.021,root)
                electron=self.sphere(label+' electron',(1.1,0,0),.095,(.78,.9,1),root)
                self.electrons.append((electron,k,row))
            self.label(label,0,-1.55,.48,root,color)
        self.he_spectrum,self.he_lines=self.make_spectrum('Helium absorption spectrum',9,1.6,HE_NM)
        self.he_label=self.label('헬륨의 흡수선',0,1.15,.42,self.he_spectrum,color=(1,.67,.25))
        self.h_label=self.label('수소의 흡수선',0,1.15,.42,self.spectrum,color=(.2,.75,1));self.h_opacity=fade_material(self.h_label)
        self.atom_photons=[]
        for row in range(2):
            for k in range(3):
                o=self.sphere('Atom incoming selected wavelength',(0,0,0),.09,spectral_color(((H_NM if row==0 else HE_NM)[k]-400)/300));self.atom_photons.append((o,row,k))
        self.element_title=self.label('원자마다 흡수하는 파장이 다르다',0,5.4,.63)
        self.element_opacity=fade_material(self.element_title)

    def build_diagnostic_traces(self):
        self.traces=self.empty('Trace absorption back to stellar atmosphere')
        self.trace_packets=[]
        for i,line in enumerate(self.lines):
            start=Vector((5+line.location.x,0,2));end=Vector((-3.3,.3,1.5))
            bend=Vector((1,-1.9-i*.3,2.2))
            points=[]
            for k in range(41):
                q=k/40;points.append(tuple((1-q)**2*start+2*(1-q)*q*bend+q*q*end))
            self.path('Absorption diagnostic guide',points,(.19,.30,.42),.018,self.traces)
            obj=self.sphere('Diagnostic tracing point',start,.095,(1,.68,.2),self.traces)
            self.trace_packets.append((obj,start,bend,end,i))

    def aim(self,position,target):
        self.camera.location=position;self.camera.rotation_euler=(Vector(target)-self.camera.location).to_track_quat('-Z','Y').to_euler()

    def sample(self,controller,p,time):
        # Absolute states make random access and baked .blend playback deterministic.
        stage=self.controllers.index(controller)
        self.optics.scale=(0,0,0);self.traces.scale=(0,0,0)
        self.atmosphere_beams.scale=(0,0,0);self.gas.scale=(0,0,0)
        self.he_spectrum.scale=(0,0,0)
        for o in self.atom_roots:o.scale=(0,0,0)
        for o,_,_ in self.atom_photons:o.scale=(0,0,0)
        for o in self.shells:o.scale=(0,0,0)
        self.question_opacity.default_value=0;self.star_label_opacity.default_value=0
        self.abs_opacity.default_value=0;self.atmosphere_opacity.default_value=0;self.light_opacity.default_value=0
        self.h_opacity.default_value=0;self.element_opacity.default_value=0
        self.spec_label.scale=(1,1,1)
        self.star.rotation_euler.y=.105*time
        self.twinkle.default_value=.96+.065*math.sin(time*3.2)+.025*math.sin(time*7.1)
        self.star.scale=(1,1,1);self.star.location=(-8,1.2,0)
        self.spectrum.location=(5,-2,0);self.spectrum.rotation_euler=(0,0,0);self.spectrum.scale=(1,1,1)
        if stage==0:
            self.aim((1,-6+1.1*smooth(p),30.5),(0,0,0))
            self.optics.scale=(1,1,1);self.star_label_opacity.default_value=1
            reveal=smooth((p-.37)/.28)
            for line in self.lines:self.g.line_strength(line,.92*reveal)
            self.abs_opacity.default_value=smooth((p-.57)/.16)
        elif stage==1:
            q=smooth(p/.21)
            self.aim(lerp((1,-4.9,30.5),(0,-2,29),q),(0,0,0))
            self.star.location=lerp((-8,1.2,0),(-6,0,0),q);self.star.scale=(1+.58*q,)*3
            self.spectrum.location=lerp((5,-2,0),(5,0,1),q)
            self.spectrum.rotation_euler.y=-.23*smooth((p-.23)/.35)
            self.optics.scale=(1-q,)*3;self.abs_opacity.default_value=1
            for line in self.lines:self.g.line_strength(line,.92)
            self.question_opacity.default_value=smooth((p-.17)/.15)
            self.traces.scale=(smooth((p-.35)/.16),)*3
        elif stage==2:
            q=smooth(p/.22)
            self.aim(lerp((0,-2,29),(0,-2,23.5),q),(0,0,0))
            self.star.location=lerp((-6,0,0),(-16.3,0,-4),q);self.star.scale=(1.58+(5.2-1.58)*q,)*3
            self.spectrum.location=lerp((5,0,1),(0,-3.1,5.2),q)
            self.spectrum.scale=(1+.12*q,)*3;self.spectrum.rotation_euler.y=-.23*(1-q)
            self.abs_opacity.default_value=1-q
            self.question_opacity.default_value=1-q
            self.traces.scale=(1-q,)*3
            shell=smooth((p-.10)/.14)
            for o in self.shells:o.location=self.star.location;o.scale=tuple(s*shell for s in self.star.scale)
            a=smooth((p-.20)/.12);self.atmosphere_beams.scale=(a,)*3;self.gas.scale=(a,)*3
            self.atmosphere_opacity.default_value=a;self.light_opacity.default_value=a
            strength=.92*(1-q)+.94*smooth((p-.30)/.50)
            for line in self.lines:self.g.line_strength(line,min(.94,strength))
        else:
            q=smooth(p/.19)
            self.aim(lerp((0,-2,23.5),(0,-1,27),q),(0,0,0))
            self.star.location=lerp((-16.3,0,-4),(-35,0,-8),q);self.star.scale=(5.2,)*3
            for o in self.shells:o.location=self.star.location;o.scale=(5.2*(1-q),)*3
            self.spectrum.location=lerp((0,-3.1,5.2),(3.5,2.35,1),q);self.spectrum.scale=(1.12,)*3
            self.atmosphere_beams.scale=(1-q,)*3;self.gas.scale=(1-q,)*3
            self.atmosphere_opacity.default_value=1-q;self.light_opacity.default_value=1-q
            self.spec_label.scale=(1-q,)*3
            self.h_opacity.default_value=q;self.element_opacity.default_value=q
            self.he_spectrum.location=(3.5,-2.6,1);self.he_spectrum.scale=(1.12*q,)*3
            for row,root in enumerate(self.atom_roots):
                root.location=lerp((-2,.7,5.5),(-6,2.35-row*4.95,1),q);root.scale=(1.25*q,)*3
            for line in self.lines:self.g.line_strength(line,.94*(1-q)+.94*smooth((p-.18)/.23))
            for line in self.he_lines:self.g.line_strength(line,.94*smooth((p-.36)/.24))
            for o,row,k in self.atom_photons:
                u=(time*.36+k/3)%1;o.location=(-9.2+3.15*u,2.35-row*4.95,1.3);o.scale=(q*(1-smooth((u-.85)/.15)),)*3
        for o,start,bend,end,i in self.trace_packets:
            u=(time*.35+i*.21)%1;o.location=(1-u)**2*start+2*(1-u)*u*bend+u*u*end
        for i,o in enumerate(self.white_packets):o.location=self.white_start.lerp(self.white_end,(time*.9+i/3)%1)
        for o,end,offset in self.rays:o.location=self.exit.lerp(end,(time*.6+offset)%1)
        for o,offset,row in self.escape_packets:
            u=(time*.27+offset)%1;o.location=(-7+13.5*u,.1+.75*row,6)
        for o,pos,i in self.gas_particles:o.location=pos+Vector((.03*math.sin(time+i),.05*math.sin(time*.8+i),.06*math.cos(time+i)))
        for o,k,row in self.electrons:
            a=time*(1.1+.12*row)+k*math.pi;o.location=(1.13*math.cos(a),.82*math.sin(a),.6*math.sin(a+k))
        # Halo follows the actual star and faces the moving camera.
        normal=(self.camera.location-self.star.location).normalized()
        self.halo.location=self.star.location-normal*1.2*self.star.scale.x
        self.halo.rotation_euler=normal.to_track_quat('Z','Y').to_euler();self.halo.scale=self.star.scale
        return list(dict.fromkeys(self.objects))
