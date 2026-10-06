"""Directed revision: one arriving ray and one escaping ray, with real camera orbits."""
import math
import random
import bpy
from mathutils import Vector, Matrix, Quaternion
try:
    from .optics_journey import OpticsJourney, H_NM, spectral_color, lerp
    from .distance_flight import DistanceFlight
    from .animated_materials import fade_material, fade_all_materials
    from .directed_motion import atmosphere_ray_length, atmosphere_absorption, orbit_angle, incoming_ray_head
    from .spectra import smooth
except ImportError:
    from optics_journey import OpticsJourney, H_NM, spectral_color, lerp
    from distance_flight import DistanceFlight
    from animated_materials import fade_material, fade_all_materials
    from directed_motion import atmosphere_ray_length, atmosphere_absorption, orbit_angle, incoming_ray_head
    from spectra import smooth


def space_camera_rotation(position,target):
    forward=(Vector(target)-Vector(position)).normalized()
    right=forward.cross(Vector((0,1,0))).normalized()
    up=right.cross(forward).normalized()
    return Matrix((right,up,-forward)).transposed().to_euler()


def children(root):
    yield root
    for obj in root.children:yield from children(obj)


def fade_tree(root,exclude=()):
    sockets=[]
    for obj in children(root):
        if obj not in exclude and getattr(obj.data,'materials',None):sockets.extend(fade_all_materials(obj))
    return sockets


def set_opacity(sockets,amount):
    for socket in sockets:socket.default_value=amount


class EarthPrismShot:
    def __init__(self,owner):
        self.o=owner;self.g=owner.g
        self.flight=DistanceFlight(self.g,0,'rapid');self.camera=self.flight.camera
        self.label_opacity=fade_material(self.flight.label)
        self.center=Vector((10000,0,2335))
        self.prism=owner.empty('Near-Earth prism assembly');self.prism.location=self.center
        vertices=[(x,y,z) for y in (-1.6,1.6) for x,z in [(-2.6,-2),(2.6,-2),(0,2.7)]]
        mesh=bpy.data.meshes.new('Near-Earth solid prism');mesh.from_pydata(vertices,[],[(0,2,1),(3,4,5),(0,1,4,3),(1,2,5,4),(2,0,3,5)])
        glass=self.g.link('Near-Earth glass',mesh);glass.parent=self.prism
        mesh.materials.append(owner.transparent('Near-Earth glass material',(.2,.65,.9),.14));owner.objects.append(glass)
        for a,b in [(0,1),(1,2),(2,0),(3,4),(4,5),(5,3),(0,3),(1,4),(2,5)]:
            owner.path('Near-Earth prism edge',[vertices[a],vertices[b]],(.25,.67,.92),.025,self.prism)
        self.prism_label=owner.label('프리즘',0,-2.8,.48,self.prism);self.prism_label.location.z=1.7
        self.prism_label.rotation_euler=space_camera_rotation((9987,12,2355),(10003,-1,2337))
        self.prism_opacity=fade_tree(self.prism)
        self.entry=self.center+Vector((0,0,-2));self.exit=self.center+Vector((1.35,0,.3))
        source=Vector((10000,0,0))
        self.ray=owner.path('Single white ray from distant star',[source,self.entry,self.exit],(.92,.96,1),.085)
        self.ray.data.bevel_factor_mapping_end='SPLINE';self.ray.data.use_fill_caps=True;self.ray['animate_curve_reveal']=True
        self.ray_length=(self.entry-source).length+(self.exit-self.entry).length
        self.screen,self.lines=owner.make_spectrum('Near-Earth absorption spectrum',12,1.4,H_NM)
        self.screen.location=(10008,-3.8,2339)
        self.screen.rotation_euler=space_camera_rotation((9987,12,2355),(10003,-1,2337))
        owner.label('스펙트럼',0,1.35,.48,self.screen)
        owner.label('흡수선',0,-1.4,.42,self.screen,color=(1,.66,.2))
        for line in self.lines:self.g.line_strength(line,.94)
        self.screen_opacity=fade_tree(self.screen)
        self.g.scene.view_layers[0].update()
        # A continuous fan, with reduced intensity at the same selected wavelengths.
        verts=[];faces=[];materials=[];steps=84
        rotation=self.screen.rotation_euler.to_quaternion()
        for i in range(steps):
            u0=i/steps;u1=(i+1)/steps;u=(u0+u1)/2
            a=self.screen.location+rotation@Vector((12*(u0-.5),.86,.4))
            b=self.screen.location+rotation@Vector((12*(u1-.5),.86,.4))
            index=len(verts);verts += [(0,0,0),tuple(a-self.exit),tuple(b-self.exit)];faces.append((index,index+1,index+2))
            dim=.12 if min(abs(u-(nm-400)/300) for nm in H_NM)<.009 else 1
            materials.append(owner.transparent(f'Dispersed wavelength band {i}',spectral_color(u),.24*dim))
        data=bpy.data.meshes.new('Continuous dispersed spectrum fan');data.from_pydata(verts,[],faces)
        for mat in materials:data.materials.append(mat)
        for i,poly in enumerate(data.polygons):poly.material_index=i
        self.fan=self.g.link('Continuous dispersed spectrum fan',data);self.fan.location=self.exit;owner.objects.append(self.fan)

    def sample(self,p,time):
        tracked=self.flight.sample(1,time)
        q=smooth((p-.05)/.49)
        self.camera.location=lerp((9994,-5,2400),(9987,12,2355),q)
        target=lerp((9994,-5,2335),(10003,-1,2337),q)
        self.camera.rotation_euler=space_camera_rotation(self.camera.location,target)
        self.camera.data.lens=35+7*smooth((p-.55)/.30)
        set_opacity(self.prism_opacity,smooth((p-.12)/.20))
        self.label_opacity.default_value=1-smooth((p-.12)/.18)
        if p<=.365:distance=incoming_ray_head(p)
        else:distance=2333+(self.ray_length-2333)*smooth((p-.365)/.075)
        self.ray.data.bevel_factor_end=max(0,min(1,distance/self.ray_length))
        self.fan.scale=(smooth((p-.43)/.16),)*3
        set_opacity(self.screen_opacity,smooth((p-.52)/.12))
        return tracked+self.o.objects

    def hide(self):
        self.label_opacity.default_value=0
        self.flight.label.scale=(0,0,0)
        # These objects live far outside the local optics gallery's clipping range.
        set_opacity(self.prism_opacity,0);set_opacity(self.screen_opacity,0)
        self.ray.data.bevel_factor_end=0;self.fan.scale=(0,0,0)


class SurfaceOrbitShot:
    def __init__(self,owner):
        self.o=owner;self.g=owner.g
        self.radius=2.15*1.58;self.center=Vector((-6,0,0));self.source=self.center+Vector((0,0,self.radius))
        self.ray=owner.path('One ray escaping stellar atmosphere',[(0,0,0),(0,0,1)],(.94,.97,1),.025)
        self.ray.location=self.source;self.ray.data.use_fill_caps=True
        self.ray['single_escape_ray']=True
        self.hud,self.lines=owner.make_spectrum('Transit spectrum',12,.78,H_NM)
        owner.label('스펙트럼',0,.91,.43,self.hud)
        plate=self.g.rect('Spectrum backdrop',0,.2,12.4,2.0,(.002,.006,.017),.10);plate.parent=self.hud;owner.objects.append(plate)
        self.hud_opacity=fade_tree(self.hud,exclude=self.lines)
        self.line_opacities=[]
        for line in self.lines:
            line.data.materials[0].node_tree.nodes['Emission'].inputs['Color'].default_value=(.003,.006,.012,1)
            self.line_opacities.append(fade_material(line))
        self.gas=owner.empty('Gas along the single outgoing ray');self.atoms=[]
        rng=random.Random(7705)
        for i in range(18):
            pos=self.source+Vector((rng.uniform(-.85,.85),rng.uniform(-.85,.85),rng.uniform(.25,1.6)))
            atom=owner.sphere('Atmospheric gas particle',pos,.035,(.16,.49,.76),self.gas);self.atoms.append((atom,pos,i))
        self.caption=owner.label('별의 대기',0,0,.34,color=(.2,.72,1));self.caption_opacity=fade_material(self.caption)

    def hide(self):
        self.ray.scale=(0,0,0);self.gas.scale=(0,0,0)
        set_opacity(self.hud_opacity,0);set_opacity(self.line_opacities,0);self.caption_opacity.default_value=0

    def sample(self,p,time):
        o=self.o;camera=o.camera
        q=smooth(p/.18)
        focus=self.source+Vector((0,0,.90))
        angle=orbit_angle(p);azimuth=math.radians(-50)
        radial=Vector((math.sin(angle)*math.cos(azimuth),math.sin(angle)*math.sin(azimuth),math.cos(angle)))
        position=focus+radial*9.8
        camera.location=lerp((0,-2,29),position,q)
        target=lerp((0,0,0),focus,q)
        rotation=(target-camera.location).to_track_quat('-Z','Y')
        roll=Quaternion((0,0,1),math.radians(-14)*smooth((p-.18)/.26))
        camera.rotation_euler=(rotation@roll).to_euler()
        o.star.location=self.center;o.star.scale=(1.58,)*3
        o.spectrum.scale=(1-q,)*3;o.question_opacity.default_value=1-q;o.abs_opacity.default_value=1-q
        a=smooth((p-.10)/.15)
        for shell,original_radius,radius in zip(o.shells,(2.3,2.57),(self.radius+.35,self.radius+1.60)):
            shell.location=self.center;shell.scale=(a*radius/original_radius,)*3
        self.ray.scale=(smooth((p-.11)/.10),smooth((p-.11)/.10),atmosphere_ray_length(p)*smooth((p-.11)/.10))
        self.gas.scale=(a,)*3
        for atom,pos,i in self.atoms:atom.location=pos+Vector((.022*math.sin(time+i),.024*math.cos(time*.8+i),.02*math.sin(time*.5+i)))
        # The spectrum stays at the bottom of the picture while the camera orbits.
        rotation=camera.rotation_euler.to_quaternion()
        self.hud.location=camera.location+rotation@Vector((0,-1.63/3,-3))
        self.hud.rotation_euler=camera.rotation_euler;self.hud.scale=(.55/3,)*3
        visible=smooth((p-.16)/.10);set_opacity(self.hud_opacity,visible)
        set_opacity(self.line_opacities,visible*atmosphere_absorption(p))
        self.caption.location=camera.location+rotation@Vector((2.0/3,1.68/3,-3));self.caption.rotation_euler=camera.rotation_euler;self.caption.scale=(1/3,)*3
        self.caption_opacity.default_value=a


class DirectedOptics(OpticsJourney):
    def __init__(self,g):
        super().__init__(g)
        self.local_camera=self.camera
        self.observer=EarthPrismShot(self)
        self.surface_orbit=SurfaceOrbitShot(self)
        # Saved .blend playback switches to the same cameras used by the renderer.
        g.scene.timeline_markers.clear()
        for beat in g.job['timeline']:
            marker=g.scene.timeline_markers.new(beat['beat_id'],frame=beat['start_frame']+1)
            marker.camera=self.observer.camera if beat['controller']=='spectra-dispersion' else self.local_camera

    def sample(self,controller,p,time):
        self.surface_orbit.hide()
        if controller=='spectra-dispersion':
            self.camera=self.observer.camera
            self.g.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.005,.012,.027,1)
            return list(dict.fromkeys(self.observer.sample(p,time)))
        self.observer.hide();self.camera=self.local_camera
        self.g.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.002,.006,.017,1)
        if controller=='spectra-temperature-question':tracked=super().sample(controller,max(.21,p),time)
        elif controller=='spectra-atmosphere':
            tracked=super().sample('spectra-temperature-question',1,time)
            self.surface_orbit.sample(p,time)
        else:tracked=super().sample(controller,max(.19,p),time)
        # No diagnostic connectors and no duplicated white beams in this revision.
        self.traces.scale=(0,0,0);self.atmosphere_beams.scale=(0,0,0);self.gas.scale=(0,0,0);self.optics.scale=(0,0,0)
        if controller=='spectra-atmosphere':
            self.atmosphere_opacity.default_value=0;self.light_opacity.default_value=0
        normal=(self.camera.location-self.star.location).normalized()
        self.halo.location=self.star.location-normal*1.2*self.star.scale.x
        self.halo.rotation_euler=normal.to_track_quat('Z','Y').to_euler();self.halo.scale=self.star.scale
        return list(dict.fromkeys(tracked+[self.observer.flight.label]))
