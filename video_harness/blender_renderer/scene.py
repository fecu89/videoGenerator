"""An editable, continuous 3D spectral teaching gallery built with native bpy.

The spectrum swatches and line-strength graph are qualitative teaching models.
Their provenance is recorded in the project documents, outside the picture.
All panels persist in one scene; the camera travels between explanations.
"""
import math
import random
from pathlib import Path
import bpy

try:
    from .spectra import HYDROGEN_POSITIONS, line_strengths, smooth, camera_transition_progress
except ImportError:  # Standalone Blender --python entrypoint.
    from spectra import HYDROGEN_POSITIONS, line_strengths, smooth, camera_transition_progress

INK = (0.72, 0.84, 1.0)
CYAN = (0.07, 0.66, 0.9)
GOLD = (1.0, 0.55, 0.1)
BACK = (0.005, 0.012, 0.027)
STAGES = ['spectra-compare','spectra-absorption','spectra-hydrogen','spectra-atom',
          'spectra-hot','spectra-cool','spectra-disambiguate','spectra-classify',
          'spectra-subtype','spectra-sun']
TEMPERATURES = [35000,15000,9000,6700,5800,4500,3200]
COLORS = [(0.28,0.48,1),(0.55,0.72,1),(0.91,0.94,1),(1,.94,.77),
          (1,.84,.4),(1,.52,.14),(1,.24,.08)]


class SpectralGallery:
    def __init__(self, job):
        self.job=job
        self.scene=bpy.data.scenes.new('Stellar Spectra')
        if bpy.context.window:
            bpy.context.window.scene=self.scene
        self.materials={}
        self.animated=[]
        self.panels=[]
        self.font=bpy.data.fonts.load('/System/Library/Fonts/Supplemental/AppleGothic.ttf')
        self.configure()
        self.base_camera=self.camera
        self.flight=None
        self.optics=None
        self.continuous_opening=False
        self.build()

    def configure(self):
        scene=self.scene
        scene.render.engine='BLENDER_EEVEE'
        # Emissive teaching diagrams need edge antialiasing, without costly
        # indirect-light sampling. Compared at 1080p against 64 samples.
        scene.eevee.taa_render_samples=8
        scene.render.resolution_x=self.job['output']['width']
        scene.render.resolution_y=self.job['output']['height']
        scene.render.resolution_percentage=100
        scene.render.image_settings.file_format='PNG'
        scene.render.image_settings.color_mode='RGB'
        scene.render.image_settings.compression=15
        scene.render.fps=self.job['canonical_fps']
        scene.frame_start=1
        scene.frame_end=self.job['duration_frames']
        scene.world=bpy.data.worlds.new('Spectral Navy')
        scene.world.color=BACK
        scene.view_settings.view_transform='Standard'
        scene.view_settings.look='None'
        camera=bpy.data.cameras.new('Spectral Camera')
        camera.type='ORTHO'; camera.ortho_scale=28.444
        self.camera=bpy.data.objects.new('Spectral Camera',camera)
        scene.collection.objects.link(self.camera)
        self.camera.location=(0,0,25)
        scene.camera=self.camera
        # Soft highlights on spheres; the teaching diagrams remain unshadowed.
        light=bpy.data.lights.new('Softbox','AREA'); light.energy=1800; light.shape='DISK'; light.size=14
        obj=bpy.data.objects.new('Softbox',light); scene.collection.objects.link(obj)
        obj.location=(0,3,12)

    def material(self,color,strength=1):
        key=(*color,strength)
        if key in self.materials:return self.materials[key]
        mat=bpy.data.materials.new('Spectrum emission'); mat.use_nodes=True
        nodes=mat.node_tree.nodes; nodes.clear()
        emit=nodes.new('ShaderNodeEmission'); emit.inputs['Color'].default_value=(*color,1)
        emit.inputs['Strength'].default_value=strength
        out=nodes.new('ShaderNodeOutputMaterial'); mat.node_tree.links.new(emit.outputs[0],out.inputs['Surface'])
        self.materials[key]=mat
        return mat

    def link(self,name,data):
        obj=bpy.data.objects.new(name,data); self.scene.collection.objects.link(obj)
        return obj

    def rect(self,name,x,y,w,h,color,z=0):
        mesh=bpy.data.meshes.new(name)
        mesh.from_pydata([(-w/2,-h/2,0),(w/2,-h/2,0),(w/2,h/2,0),(-w/2,h/2,0)],[],[(0,1,2,3)])
        obj=self.link(name,mesh); obj.location=(x,y,z); mesh.materials.append(self.material(color))
        return obj

    def text(self,body,x,y,size=.55,color=INK,align='CENTER'):
        curve=bpy.data.curves.new(body,'FONT'); curve.body=body; curve.font=self.font
        curve.align_x=align; curve.size=size*1.12
        obj=self.link(body,curve); obj.location=(x,y,1.2); curve.materials.append(self.material(color))
        return obj

    def path(self,name,points,color=CYAN,radius=.025):
        curve=bpy.data.curves.new(name,'CURVE');curve.dimensions='3D';curve.bevel_depth=radius;curve.bevel_resolution=2
        spline=curve.splines.new('POLY');spline.points.add(len(points)-1)
        for p,xyz in zip(spline.points,points):p.co=(*xyz,1)
        obj=self.link(name,curve);curve.materials.append(self.material(color));return obj

    def ring(self,name,x,y,r,color=CYAN):
        return self.path(name,[(x+r*math.cos(a*math.tau/96),y+r*math.sin(a*math.tau/96),.25) for a in range(97)],color,.035)

    def star(self,name,x,y,r,color):
        # Small diagram markers stay cheap; actual stars carry a packed image.
        detailed = r >= .7
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96 if detailed else 24,
            ring_count=64 if detailed else 12,radius=r,location=(x,y,.1))
        obj=bpy.context.object;obj.name=name
        for face in obj.data.polygons:face.use_smooth=True
        if not detailed:
            obj.data.materials.append(self.material(color))
            return obj
        mat=bpy.data.materials.new(name+' surface');mat.use_nodes=True
        nodes=mat.node_tree.nodes;nodes.clear()
        tex=nodes.new('ShaderNodeTexImage')
        tex.image=bpy.data.images.load(str(Path(__file__).parent/'assets'/'stellar-photosphere-v2.png'),check_existing=True)
        tex.image.pack()
        ramp=nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position=.08
        ramp.color_ramp.elements[0].color=(*(c*.16 for c in color),1)
        ramp.color_ramp.elements[1].position=.82
        ramp.color_ramp.elements[1].color=(*color,1)
        emit=nodes.new('ShaderNodeEmission')
        layer=nodes.new('ShaderNodeLayerWeight')
        mult=nodes.new('ShaderNodeMath');mult.operation='MULTIPLY_ADD';mult.inputs[1].default_value=-.65;mult.inputs[2].default_value=1.25
        out=nodes.new('ShaderNodeOutputMaterial')
        links=mat.node_tree.links
        links.new(tex.outputs['Color'],ramp.inputs[0]);links.new(ramp.outputs[0],emit.inputs['Color'])
        links.new(layer.outputs['Facing'],mult.inputs[0]);links.new(mult.outputs[0],emit.inputs['Strength'])
        links.new(emit.outputs[0],out.inputs['Surface']);obj.data.materials.append(mat)
        # UV pole points away from the camera, so the visible disk has no pinch.
        obj.rotation_euler.x=math.pi/2
        # A soft radial halo behind the disk conveys emission without obscuring
        # the texture or applying a bloom filter to the educational labels.
        halo=self.rect(name+' glow',x,y,r*2.6,r*2.6,color,-1)
        glow=bpy.data.materials.new(name+' soft glow');glow.use_nodes=True
        glow.surface_render_method='BLENDED'
        nodes=glow.node_tree.nodes;nodes.clear();links=glow.node_tree.links
        coords=nodes.new('ShaderNodeTexCoord')
        distance=nodes.new('ShaderNodeVectorMath');distance.operation='DISTANCE'
        distance.inputs[1].default_value=(.5,.5,.5)
        fade=nodes.new('ShaderNodeValToRGB')
        fade.color_ramp.elements[0].position=.37;fade.color_ramp.elements[0].color=(.10,.10,.10,1)
        fade.color_ramp.elements[1].position=.50;fade.color_ramp.elements[1].color=(0,0,0,1)
        transparent=nodes.new('ShaderNodeBsdfTransparent')
        emission=nodes.new('ShaderNodeEmission');emission.inputs['Color'].default_value=(*color,1)
        mix=nodes.new('ShaderNodeMixShader');out=nodes.new('ShaderNodeOutputMaterial')
        links.new(coords.outputs['Generated'],distance.inputs[0]);links.new(distance.outputs['Value'],fade.inputs[0])
        links.new(fade.outputs['Color'],mix.inputs[0]);links.new(transparent.outputs[0],mix.inputs[1])
        links.new(emission.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs['Surface'])
        halo.data.materials[0]=glow
        return obj

    def spectrum(self,name,x,y,width=17,height=.65,temperature=9000,elements='all'):
        height*=1.25
        colors=[(.3,.06,.65),(.16,.2,1),(.06,.65,1),(.04,.82,.44),(.75,.9,.02),(1,.5,.015),(.82,.04,.025)]
        vertices=[];faces=[];indices=[]
        mesh=bpy.data.meshes.new(name)
        for i in range(84):
            u=i/83*(len(colors)-1);j=min(int(u),len(colors)-2);f=u-j
            color=tuple(colors[j][k]*(1-f)+colors[j+1][k]*f for k in range(3))
            left=-width/2+width*i/84;right=-width/2+width*(i+1)/84
            base=len(vertices);vertices.extend([(left,-height/2,0),(right,-height/2,0),(right,height/2,0),(left,height/2,0)])
            faces.append((base,base+1,base+2,base+3));indices.append(i)
            mesh.materials.append(self.material(color))
        mesh.from_pydata(vertices,[],faces)
        for polygon,i in zip(mesh.polygons,indices):polygon.material_index=i
        obj=self.link(name,mesh);obj.location=(x,y,.4)
        strengths=line_strengths(temperature)
        def absorption(label,pos,line_width,strength):
            u=pos*(len(colors)-1);j=min(int(u),len(colors)-2);f=u-j
            base=tuple(colors[j][k]*(1-f)+colors[j+1][k]*f for k in range(3))
            line=self.rect(label,x-width/2+width*pos,y,line_width,height*.98,base,.53)
            line.data.materials[0]=line.data.materials[0].copy()
            line['spectrum_color']=base
            self.line_strength(line,strength)
            return line
        lines=[]
        if elements in ('all','hydrogen'):
            for i,pos in enumerate(HYDROGEN_POSITIONS):
                lines.append(absorption(name+f' H{i}',pos,.13,strengths['hydrogen']))
        if elements in ('all','helium'):
            for i,pos in enumerate((.23,.54,.74)):
                line=absorption(name+f' He{i}',pos,.11,strengths['helium_ionized'])
                if elements=='helium':lines.append(line)
        if elements=='all':
            for i,pos in enumerate((.11,.26,.39,.46,.61,.79,.83,.96)):
                absorption(name+f' metal{i}',pos,.06,strengths['metals'])
            for i,pos in enumerate((.56,.69,.82)):
                absorption(name+f' molecule{i}',pos,.43,strengths['molecules'])
        return obj,lines

    def line_strength(self,obj,strength):
        color=obj['spectrum_color']
        socket=obj.data.materials[0].node_tree.nodes.get('Emission').inputs['Color']
        socket.default_value=(*(color[i]*(1-strength)+BACK[i]*strength for i in range(3)),1)

    def plot(self,x):
        self.path('temperature axis',[(x-9,-3.8,.2),(x+9,-3.8,.2)],INK)
        self.path('strength axis',[(x-9,-3.8,.2),(x-9,3.5,.2)],INK)
        points=[]
        for i in range(181):
            temp=40000*(3000/40000)**(i/180)
            points.append((x-9+i*.1,-3.5+7*line_strengths(temp)['hydrogen'],.3))
        self.path('hydrogen strength curve',points,GOLD,.06)
        self.text('수소 흡수선의 상대 세기',x,4.5,.6)
        for label,temp in [('O',35000),('B',15000),('A',9000),('F',6700),('G',5800),('K',4500),('M',3200)]:
            px=x-9+18*math.log(temp/40000)/math.log(3000/40000)
            self.text(label,px,-4.7,.58,GOLD if label=='A' else INK)
        self.text('고온',x-10,-5.8,.5,CYAN);self.text('저온',x+10,-5.8,.5,GOLD)
        return self.star('curve marker',x,0,.25,(1,.88,.36))

    def build(self):
        controllers=list(dict.fromkeys(item['controller'] for item in self.job['timeline']))
        self.controller_indices={name:i for i,name in enumerate(controllers)}
        rng=random.Random(self.job.get('style',{}).get('seed',20260915))
        if any(b.get('controller_options',{}).get('continuous_intro_flight') for b in self.job['timeline']):
            try:
                from .distance_flight import DistanceFlight
            except ImportError:
                from distance_flight import DistanceFlight
            self.flight=DistanceFlight(self,0,next((b.get('controller_options',{}).get('flight_profile','original') for b in self.job['timeline'] if b['controller']=='spectra-distance'),'original'))
            self.flight.add_intro_labels()
            self.continuous_opening=True
        if any(b.get('controller_options',{}).get('optics_journey') for b in self.job['timeline']):
            try:
                from .optics_journey import OpticsJourney
            except ImportError:
                from optics_journey import OpticsJourney
            if any(b.get('controller_options',{}).get('directed_optics') for b in self.job['timeline']):
                try:
                    from .directed_optics import DirectedOptics
                except ImportError:
                    from directed_optics import DirectedOptics
                self.optics=DirectedOptics(self)
            else:self.optics=OpticsJourney(self)
        for index,controller in enumerate(controllers):
            x=index*32
            if (self.continuous_opening and controller in ('spectra-intro','spectra-distance')) or (self.optics and controller in self.optics.controllers):
                self.panels.append((controller,x,{}))
                continue
            flight_beat=next((b for b in self.job['timeline'] if b['controller']==controller and b.get('controller_options',{}).get('distance_flight')),None)
            if controller=='spectra-distance' and flight_beat:
                try:
                    from .distance_flight import DistanceFlight
                except ImportError:
                    from distance_flight import DistanceFlight
                self.flight=DistanceFlight(self,flight_beat['start_frame'],flight_beat.get('controller_options',{}).get('flight_profile','original'))
                if flight_beat['start_frame']>0:
                    marker=self.scene.timeline_markers.new('Opening camera',frame=1);marker.camera=self.base_camera
                self.panels.append((controller,x,{}))
                continue
            self.rect('navy field',x,0,32,22,BACK,-4)
            for _ in range(28):
                px=x+rng.uniform(-15,15);py=rng.uniform(-7.5,7.5)
                self.rect('distant starlight',px,py,.018,.018,(.11,.19,.3),-3)
            objects={}
            if controller=='spectra-intro':
                objects['star']=self.star('10000 K white star',x-4,0,4.2,(.83,.9,1))
                self.text('10,000 K',x+5,1.1,1.45,INK)
                self.text('어떻게 알았을까?',x+5,-1.25,.7,GOLD)
                self.text('별의 표면 온도',x+5,3.2,.55,CYAN)
            elif controller=='spectra-distance':
                objects['star']=self.star('distant white star',x-8,1.4,1.65,(.83,.9,1))
                self.text('먼 별',x-8,-1.25,.7)
                self.path('long light path',[(x-6,1.4,.3),(x+6.1,1.4,.3)],(.18,.34,.49),.035)
                for dx in (-.4,.4):
                    self.path('distance break',[(x+dx-.25,2,.7),(x+dx+.25,.8,.7)],INK,.08)
                self.rect('telescope tube',x+7.5,1.4,2.6,1.05,(.12,.29,.4))
                self.path('telescope lens',[(x+6.2,.75,.5),(x+6.2,2.05,.5)],CYAN,.13)
                self.path('telescope tripod',[(x+8.3,-1.2,.4),(x+7.5,.9,.4),(x+6.7,-1.2,.4)],INK,.055)
                self.text('관측자',x+7.5,-2.15,.7)
                self.text('도착한 빛으로 온도를 읽는다',x,-4.6,.76,GOLD)
                objects['photon']=self.star('travelling starlight',x-5,1.4,.23,(.85,.94,1))
            elif controller=='spectra-dispersion':
                objects['star']=self.star('light source star',x-8,1.4,2.5,(.86,.92,1))
                self.path('unsplit white beam',[(x-5.4,1.4,.4),(x-2.5,1.4,.4)],(.9,.94,1),.10)
                self.path('large prism',[(x-2.5,-.3,.5),(x-1,3.6,.5),(x+.5,-.3,.5),(x-2.5,-.3,.5)],CYAN,.10)
                for i,c in enumerate(COLORS):
                    self.path('separated wavelength',[(x-.45,1.4,.3),(x+2.4,3.4-i*.62,.3)],c,.05)
                self.spectrum('revealed spectrum',x+6.8,1.4,8.2,3.1,9000)
                self.text('별빛',x-8,-2,.75)
                self.text('분광기',x-1,-1.55,.65,CYAN)
                self.text('흡수선',x+6.8,-2,.95,GOLD)
                self.text('빛을 파장별로 나누면',x,-4.8,.72)
                objects['photon']=self.star('incoming light',x-5,1.4,.22,(1,1,1))
            elif controller=='spectra-temperature-question':
                self.text('흡수선',x-6,3.3,1.0,CYAN)
                self.text('온도',x+6,3.3,1.0,GOLD)
                self.text('?',x,3.1,1.5,INK)
                self.spectrum('question spectrum',x,0,21,2.15,9000)
                self.text('답은 흡수선이 만들어지는 과정에',x,-4,.75)
                objects['scan']=self.rect('line inspection',x-10,0,.075,3.5,GOLD,.8)
            elif controller=='spectra-atmosphere':
                objects['star']=self.star('stellar photosphere',x-7.8,.6,2.65,(1,.78,.3))
                self.ring('cool absorbing atmosphere',x-7.8,.6,3.2,CYAN)
                self.text('상대적으로 차가운 대기',x-7.4,4.8,.60,CYAN)
                self.text('광구',x-7.8,-3.5,.65,GOLD)
                self.path('outgoing starlight',[(x-4.6,.6,.3),(x-2.6,.6,.3)],INK,.08)
                self.text('통과 전',x+4,4.35,.65)
                self.spectrum('before absorption',x+4,2.65,13,1.35,9000,elements='none')
                self.text('통과 후',x+4,-.65,.65)
                _,objects['lines']=self.spectrum('after absorption',x+4,-2.5,13,1.35,9000,elements='hydrogen')
                objects['photon']=self.star('escaping photon',x-5,.6,.23,(1,.95,.6))
                self.text('특정 파장의 빛이 약해진다',x+3.5,-5,.65,GOLD)
            elif controller=='spectra-elements':
                for y,name in ((3.25,'hydrogen sample 1'),(1.1,'hydrogen sample 2')):
                    self.text('H',x-10.5,y-.3,.92,CYAN)
                    _,objects['lines1' if y>2 else 'lines2']=self.spectrum(name,x+1,y,18,1.05,9000,elements='hydrogen')
                for pos in HYDROGEN_POSITIONS:
                    px=x-8+18*pos
                    self.path('aligned hydrogen wavelengths',[(px,.2,.2),(px,4.15,.2)],(.14,.4,.55),.025)
                self.text('He',x-10.5,-2.5,.87,GOLD)
                _,objects['helium']=self.spectrum('helium wavelengths',x+1,-2.15,18,1.05,35000,elements='helium')
                self.text('같은 원소의 선은 같은 파장에',x,-5,.76)
            elif controller=='spectra-compare':
                objects['star1']=self.star('white star A',x-6,2,1.7,(.86,.91,1))
                objects['star2']=self.star('white star B',x+6,2,1.7,(.93,.91,.88))
                self.text('?',x,2,1.3,GOLD)
                objects['spec1'],objects['lines1']=self.spectrum('spectrum A',x-6,-2.5,9,.8,9800)
                objects['spec2'],objects['lines2']=self.spectrum('spectrum B',x+6,-2.5,9,.8,7800)
            elif controller=='spectra-absorption':
                objects['star']=self.star('photosphere',x-8,0,2.0,(1,.83,.42))
                self.ring('cooler atmosphere',x-8,0,2.45,CYAN)
                self.text('별의 대기',x-8,3.2,.6,CYAN)
                self.path('white beam',[(x-5.5,0,0),(x-1.5,0,0)],(.85,.86,.75),.065)
                self.path('spectrometer prism',[(x-1.3,-.9,.2),(x-.1,1.2,.2),(x+1.1,-.9,.2),(x-1.3,-.9,.2)],CYAN,.055)
                self.text('분광기',x-.1,-2,.5)
                _,objects['lines']=self.spectrum('absorbed spectrum',x+7,0,9,1.9,9000)
                objects['photon']=self.star('light packet',x-5,0,.13,(1,1,.9))
                self.text('흡수선',x+7,-2,.7,GOLD)
            elif controller=='spectra-hydrogen':
                self.text('같은 수소',x,4.5,.8)
                _,objects['lines1']=self.spectrum('strong hydrogen',x,1.9,19,1.2,9000)
                _,objects['lines2']=self.spectrum('weak hydrogen',x,-2,19,1.2,16000)
                for pos in HYDROGEN_POSITIONS:
                    px=x-9.5+19*pos
                    self.path('same wavelength',[(px,-3,.15),(px,3,.15)],(.12,.27,.36),.012)
            elif controller=='spectra-atom':
                for r in (1.2,2.15,3.15): self.ring('energy level',x-4,0,r,(.12,.26,.36))
                self.star('nucleus',x-4,0,.3,GOLD)
                objects['electron']=self.star('electron',x-2.8,0,.19,CYAN)
                self.text('들뜸',x-6,-4,.7,CYAN);self.text('이온화',x+5,-4,.7,GOLD)
                self.path('energy input',[(x-10,0,.3),(x-7.4,0,.3)],GOLD,.045)
                _,objects['lines']=self.spectrum('changing hydrogen',x+7,0,7,1.1,9000)
            elif controller in ('spectra-hot','spectra-cool'):
                objects['marker']=self.plot(x)
                self.text('이온화' if controller=='spectra-hot' else '들뜬 수소 감소',x+7,3,.6,CYAN)
            elif controller=='spectra-disambiguate':
                objects['star1']=self.star('hot star',x-6,2.4,2.2,COLORS[0])
                objects['star2']=self.star('cool star',x+6,2.4,2.2,COLORS[-1])
                self.text('O · He II',x-6,-.75,.86,CYAN)
                self.text('M · 분자',x+6,-.75,.86,GOLD)
                self.spectrum('hot diagnostic',x-6,-3,10,1.5,35000)
                self.spectrum('cool diagnostic',x+6,-3,10,1.5,3200)
                objects['scan']=self.rect('comparison guide',x-11,-3,.07,2.3,(1,.88,.4),.8)
            elif controller=='spectra-classify':
                for i,(letter,temp,color) in enumerate(zip('OBAFGKM',TEMPERATURES,COLORS)):
                    y=4.5-i*1.4
                    self.text(letter,x-10,y-.2,.85,color)
                    self.spectrum('standard '+letter,x+1,y,17,.68,temp)
                objects['selection']=self.path('standard selection',[(-9,-.55,.8),(10,-.55,.8),(10,.55,.8),(-9,.55,.8),(-9,-.55,.8)],GOLD,.025)
                objects['selection'].location.x=x
            elif controller=='spectra-subtype':
                self.text('G',x,3.3,1.5,GOLD)
                self.spectrum('G standard',x,1.5,19,1,5800)
                self.path('subtype ruler',[(x-10,-1.3,.2),(x+10,-1.3,.2)],INK)
                for i in range(10):
                    px=x-10+20*i/9
                    self.path('subtype tick',[(px,-1.3,.2),(px,-1.8,.2)],INK)
                    self.text('G'+str(i),px,-3,.66)
                objects['marker']=self.star('subtype marker',x-10,-1.3,.18,GOLD)
                self.text('고온',x-10,-4.5,.5,CYAN);self.text('저온',x+10,-4.5,.5,GOLD)
            elif controller=='spectra-sun':
                objects['star']=self.star('Sun',x-5,1,4.1,(1,.73,.2))
                self.text('태양',x-5,-3.8,.7,GOLD)
                self.text('G2',x+5,1.5,2.7,INK)
                self.text('약 5800 K',x+5,-.7,.95,GOLD)
                self.spectrum('Sun spectrum',x,-4.9,21,.95,5800)
            self.panels.append((controller,x,objects))

    def sample(self,canonical_frame):
        entry=self.job['canonical_state_cache'][canonical_frame]
        beats={t['beat_id']:t for t in self.job['timeline']}
        item=max((beats[i] for i in entry['active_beat_ids']),key=lambda t:(t.get('priority',0),t['beat_id']))
        current=self.controller_indices[item['controller']]
        progress=(canonical_frame-item['start_frame'])/max(1,item['end_frame']-item['start_frame']-1)
        elapsed=(canonical_frame-item['start_frame'])/self.job['canonical_fps']
        if self.optics and item['controller'] in self.optics.controllers:
            tracked=self.optics.sample(item['controller'],progress,entry['simulation_time'])
            self.camera=self.optics.camera;self.scene.camera=self.camera
            return entry,tracked
        if item['controller']=='spectra-intro' and self.continuous_opening:
            self.camera=self.flight.camera;self.scene.camera=self.camera
            return entry,self.flight.sample_intro(elapsed,entry['simulation_time'])
        if item['controller']=='spectra-distance' and self.flight:
            self.camera=self.flight.camera;self.scene.camera=self.camera
            return entry,self.flight.sample(progress,entry['simulation_time'])
        self.camera=self.base_camera;self.scene.camera=self.camera
        camera_blend=camera_transition_progress(self.job, elapsed)
        previous=max(0,current-1)
        x=32*(previous+(current-previous)*camera_blend)
        # Slow, meaningful push toward the diagnostic pattern after the move.
        profile=self.job.get('variant_profile',{})
        zoom={'base':1,'wide':1.08,'close':.96,'restrained':1.025}.get(profile.get('camera_profile','base'),1)
        self.camera.location=(x,0,25)
        # Keep the star large while giving the opening and closing shots a slow reveal.
        scale=(23.2+1.2*smooth(progress)) if item['controller'] in ('spectra-intro','spectra-sun') else (24.4-.6*smooth(progress))
        self.camera.data.ortho_scale=scale*zoom
        tracked=[self.camera]
        for controller,px,objs in self.panels:
            if controller=='spectra-distance' and self.flight:
                continue
            starts=[b['start_frame'] for b in self.job['timeline'] if b['controller']==controller]
            ends=[b['end_frame'] for b in self.job['timeline'] if b['controller']==controller]
            p=max(0,min(1,(canonical_frame-min(starts))/max(1,max(ends)-min(starts)-1)))
            time=entry['simulation_time']
            for key,obj in objs.items():
                if key.startswith('star'):
                    obj.rotation_euler.y=.105*time
                    tracked.append(obj)
            if controller=='spectra-distance':
                objs['photon'].location.x=px-5.6+11.3*((time*.18)%1);tracked.append(objs['photon'])
            elif controller=='spectra-dispersion':
                objs['photon'].location.x=px-5.3+2.7*((time*.65)%1);tracked.append(objs['photon'])
            elif controller=='spectra-temperature-question':
                objs['scan'].location.x=px-10+20*smooth(p);tracked.append(objs['scan'])
            elif controller=='spectra-atmosphere':
                objs['photon'].location.x=px-5.1+2.3*((time*.6)%1);tracked.append(objs['photon'])
                for obj in objs['lines']:self.line_strength(obj,.04+.82*smooth(p));tracked.append(obj)
            elif controller=='spectra-elements':
                for key in ('lines1','lines2','helium'):
                    for obj in objs[key]:self.line_strength(obj,.1+.78*smooth(p*2));tracked.append(obj)
            elif controller=='spectra-compare':
                for key in ('spec1','spec2'):
                    objs[key].scale.y=max(.002,smooth((p-.15)/.55));tracked.append(objs[key])
                for key in ('lines1','lines2'):
                    for obj in objs[key]:obj.scale.y=max(.002,smooth((p-.15)/.55)*.7);tracked.append(obj)
            elif controller=='spectra-absorption':
                objs['photon'].location.x=px-5.4+3.7*((time*.6)%1);tracked.append(objs['photon'])
                for obj in objs['lines']:self.line_strength(obj,.02+.85*smooth(p));tracked.append(obj)
            elif controller=='spectra-hydrogen':
                for obj in objs['lines2']:self.line_strength(obj,.12+.38*(1-smooth(p)));tracked.append(obj)
            elif controller=='spectra-atom':
                q=smooth(p)
                objs['electron'].location=(px-4+1.2+8*q,1.2*math.sin(q*math.pi),.6)
                tracked.append(objs['electron'])
                for obj in objs['lines']:self.line_strength(obj,.1+.75*math.sin(math.pi*q));tracked.append(obj)
            elif controller in ('spectra-hot','spectra-cool'):
                target=35000 if controller=='spectra-hot' else 3200
                temp=9000*(target/9000)**smooth(p)
                objs['marker'].location=(px-9+18*math.log(temp/40000)/math.log(3000/40000),-3.5+7*line_strengths(temp)['hydrogen'],.7)
                tracked.append(objs['marker'])
            elif controller=='spectra-disambiguate':
                objs['scan'].location.x=px-11+22*smooth(p);tracked.append(objs['scan'])
            elif controller=='spectra-classify':
                objs['selection'].location.y=4.5-8.4*smooth(p);tracked.append(objs['selection'])
            elif controller=='spectra-subtype':
                objs['marker'].location.x=px-10+(40/9)*smooth(p);tracked.append(objs['marker'])
        return entry,tracked

    def bake(self):
        # Each canonical frame is keyed; opening the .blend reproduces the same timeline.
        for frame in range(self.job['duration_frames']):
            _,objects=self.sample(frame)
            for obj in objects:
                obj.keyframe_insert(data_path='location',frame=frame+1)
                obj.keyframe_insert(data_path='scale',frame=frame+1)
                obj.keyframe_insert(data_path='rotation_euler',frame=frame+1)
                try:
                    from .animated_materials import animated_sockets
                except ImportError:
                    from animated_materials import animated_sockets
                for socket in animated_sockets(obj):socket.keyframe_insert(data_path='default_value',frame=frame+1)
                if obj.get('animate_curve_reveal'):
                    obj.data.keyframe_insert(data_path='bevel_factor_end',frame=frame+1)
                if 'spectrum_color' in obj:
                    obj.data.materials[0].node_tree.nodes.get('Emission').inputs['Color'].keyframe_insert(data_path='default_value',frame=frame+1)
            self.camera.data.keyframe_insert(data_path='ortho_scale',frame=frame+1)
            self.camera.data.keyframe_insert(data_path='lens',frame=frame+1)
            if self.scene.world.use_nodes:
                self.scene.world.node_tree.nodes['Background'].inputs['Color'].keyframe_insert(data_path='default_value',frame=frame+1)
        self.scene.frame_set(1)
        bpy.ops.file.pack_all()
