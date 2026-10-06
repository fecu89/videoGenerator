"""Continuous Blender film for the approved 22-part vorticity narration.

Subjects sit in the middle of the frame and the scene carries no words:
narration and burned-in subtitles carry them. The one exception is the plan's
formula callout beside the vorticity bars. Scenes change by following one subject into the next: the westerly
wave on the globe opens into the flat flow, the flow's rotations close in,
one rotation becomes the ferris wheel, and the globe returns before the
flow opens again.
"""
import math
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
from vorticity import VorticityGallery, PINK
from scene import CYAN, GOLD
from animated_materials import fade_all_materials, animated_sockets
from callout import CalloutLayer, labels_from_job
from callout_math import fade_amount
from vorticity_story_math import (story_state, phase, westerly_point, westerly_state,
                                  WESTERLY_PANEL, WESTERLY_TILT, WESTERLY_LOBES)

# Formula callouts use the user's BM HANNA 11yrs font with a dark outline;
# the font maps ζ to an empty glyph, so that symbol comes from Arial Black.
FONT_FILE = Path.home()/'Library'/'Fonts'/'배민 한나는 11살 폰트.ttf'
FALLBACK_FONT = '/System/Library/Fonts/Supplemental/Arial Black.ttf'
FALLBACK_CHARS = set('ζ→·')
OUTLINE = (.004, .01, .025)
OUTLINE_WIDTH = .06
BAR_LENGTH = 3.4
WHEEL_SPEED = .25          # counterclockwise, like Earth seen from the north
RING_RADIUS = .85
# Scene 4 lines the two rotations up side by side and enlarges them.
RING_GROWTH = 1.6
NEG_FLOW, POS_FLOW = Vector((-6, 1.5, .2)), Vector((-1, -1.5, .2))
NEG_SIDE, POS_SIDE = Vector((-6.1, 0, .2)), Vector((-.9, 0, .2))
WAVE_RADIUS = 3.07
# The flat flow x in [-9, 1] is one wavelength; x+6 is its phase from the
# crest. The same phase on the globe sits (x+6)*pi/25 east of a crest.
FLAT_X = [-9+i/18 for i in range(181)]
DETACH_SECONDS = 2.0
FLOW_VIEW = (-4.0, 0.0, 16.0)
RINGS_VIEW = (-3.5, 0.0, 9.5)
EARTH_VIEW = (28.0, 0.0, 19.0)
MIGRATION_VIEW = (29.8, 2.6, 10.5)
EARTH_WAVE_VIEW = (28.0, 0.0, 16.0)
FLOW48_VIEW = (44.0, 0.0, 16.0)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def camera_matrix(view):
    x, y, ortho = view
    return Matrix.Translation((x, y, 0)) @ Matrix.Diagonal((ortho/16, ortho/16, 1, 1))


def screen_blend(start, end, t):
    """Blend two screen-space placements: translation, turn and log scale."""
    ts, rs, ss = start.decompose()
    te, re, se = end.decompose()
    scale = [a * (b/a)**t for a, b in zip(ss, se)]
    return (Matrix.Translation(ts.lerp(te, t)) @ rs.slerp(re, t).to_matrix().to_4x4()
            @ Matrix.Diagonal((*scale, 1)))


class VorticityStoryGallery(VorticityGallery):
    def group_root(self, name):
        root = self.link(name+'Root', None)
        for obj in self.groups[name]:
            if obj.parent is None:
                world = obj.matrix_world.copy()
                obj.parent = root
                obj.matrix_world = world
        return root

    def normalized(self, meshes, size):
        self.scene.view_layers[0].update()
        pts=[o.matrix_world@Vector(v) for o in meshes for v in o.bound_box]
        lo=Vector([min(v[i] for v in pts) for i in range(3)])
        hi=Vector([max(v[i] for v in pts) for i in range(3)])
        return Matrix.Rotation(-math.pi/2,4,'X')@Matrix.Scale(size/max(hi-lo),4)@Matrix.Translation(-(lo+hi)/2)

    def wave(self, name, parent):
        # The ribbon rides just above the surface so the globe never hides it.
        ribbon=self.path(name+'Wave',[westerly_point(math.tau*i/360,WAVE_RADIUS) for i in range(361)],CYAN,.07)
        dots=[self.marker(name+'Parcel%02d'%i,(0,0),GOLD,.13) for i in range(15)]
        for obj in (ribbon,*dots):
            obj.parent=parent;obj.matrix_parent_inverse=Matrix.Identity(4)
            obj.location=(0,0,0)
        return ribbon,dots

    def build_westerly(self):
        imported, meshes = self.import_meshes('earth.glb')
        # Same normalization as the later Earth: radius 3 and north on +Y.
        norm=self.normalized(meshes,6)
        self.westerly=self.link('WesterlyEarth',None)
        for o in meshes:
            local=norm@o.matrix_world.copy()
            o.parent=None;o.animation_data_clear();o.rotation_mode='XYZ'
            o.parent=self.westerly;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=local
            o.name='WesterlyGlobe'
        for o in imported:
            if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
        self.westerly_ribbon,self.westerly_dots=self.wave('Westerly',self.westerly)
        # Keep the historical QA name for the tracked opening parcel.
        for i,obj in enumerate(self.westerly_dots):obj.name='WesterlyParcel%02d'%i

    def build_wheel(self):
        imported, meshes = self.import_meshes('wheel_of_brisbane_ferris_wheel_low-poly_free.glb')
        def ground(o):
            while o:
                if 'ground' in o.name.lower(): return True
                o=o.parent
            return False
        subjects=[o for o in meshes if not ground(o)]
        self.scene.frame_set(1)
        norm=Matrix.Translation((-4,0,0))@self.normalized(subjects,8)
        rest={o:norm@o.matrix_world.copy() for o in subjects}
        for o in imported:o.animation_data_clear()
        for o in subjects:
            o.parent=None;o.rotation_mode='XYZ';o.matrix_world=rest[o]
        for o in imported:
            if o not in subjects:bpy.data.objects.remove(o,do_unlink=True)
        # The GLB loop is ~4 degrees short of a turn, so a looping clip makes
        # cabins jump. Rotate the rim analytically and translate the cabins.
        hub=next(o for o in subjects if o.name.startswith('Circle.003'))
        self.wheel_hub=rest[hub].translation.copy()
        self.wheel_rest=rest
        self.wheel_kind={o:'spin' if o.name.startswith(('Circle.003','Pipe')) else
                         'cabin' if o.name.startswith('Pla_k52m5y_') else 'static' for o in subjects}
        self.wheel_meshes=subjects
        self.cabin_direction=self.path('CabinDirection',[(0,-.23,.05),(0,.42,.05)],GOLD,.055)

    def choose_cabin(self):
        # Track the cabin that passes the bottom of the rim mid-way through
        # Scene 6, where the close-up has open space below it.
        b=self.beats[6];t=(b['start_frame']+b['end_frame'])/2/self.fps
        def bottom_error(o):
            d=self.wheel_rest[o].translation-self.wheel_hub
            angle=math.atan2(d.y,d.x)+WHEEL_SPEED*t
            return abs(math.remainder(angle+math.pi/2,math.tau))
        cabins=[o for o,k in self.wheel_kind.items() if k=='cabin']
        self.wheel_cabin=min(cabins,key=bottom_error)
        self.wheel_cabin.name='WheelCabin'

    def build_earth_wave(self):
        self.earth_wave=self.link('EarthWave',None)
        self.earth_wave_ribbon,self.earth_wave_dots=self.wave('EarthWave',self.earth_wave)

    def text(self, body, x, y, size=.55, color=(.92,.95,1), align='CENTER'):
        obj=super().text(body,x,y,size,color,align)
        if FALLBACK_CHARS & set(body):
            obj.data.font_bold=self.fallback_font
            for i,ch in enumerate(body):
                obj.data.body_format[i].use_bold=ch in FALLBACK_CHARS
        edge=obj.data.copy();edge.offset=OUTLINE_WIDTH*obj.data.size
        edge.materials.clear();edge.materials.append(self.material(OUTLINE))
        outline=self.link(body+' outline',edge)
        outline.parent=obj;outline.location=(0,0,-.01)
        obj.visible_shadow=outline.visible_shadow=False
        self.outlines[obj]=outline
        return obj

    def build(self):
        if not FONT_FILE.is_file():
            raise FileNotFoundError(f'required font missing: {FONT_FILE}')
        self.font=bpy.data.fonts.load(str(FONT_FILE),check_existing=True)
        self.fallback_font=bpy.data.fonts.load(FALLBACK_FONT,check_existing=True)
        self.outlines={}
        self.fps=self.job['canonical_fps']
        self.beats={b['controller_options']['scene_number']:b for b in self.job['timeline']}
        self.group('westerly', self.build_westerly)
        self.group('flow', self.build_flow)
        # Three collinear points expose both halves of each arrow shaft to
        # the existing path-direction continuity check without changing shape.
        for shaft in (self.south[0],self.north[0]):
            points=shaft.data.splines[0].points
            start,end=Vector(points[0].co),Vector(points[1].co)
            points.add(1)
            points[1].co=(start+end)/2
            points[2].co=end
        self.group('wheel', self.build_wheel)
        self.choose_cabin()
        def earth():
            self.build_earth();self.build_earth_wave()
        self.group('earth', earth)
        self.roots = {name:self.group_root(name) for name in ('flow','wheel','earth')}
        self.cabin_direction.parent=self.roots['wheel']
        # The ferris wheel's hub logo is a glyph; subtitle films show no text.
        for obj in self.wheel_meshes:
            if obj.name.startswith('7logo'):
                self.wheel_kind[obj]='hidden';obj.hide_render=obj.hide_viewport=True
        self.bar_f = self.rect('PlanetaryContribution',0,0,1,.24,CYAN)
        self.bar_z = self.rect('RelativeContribution',0,0,1,.24,PINK)
        # The formula callout anchors on a hidden square at the bars' centre,
        # so the formula (and ζ's descender) clears the bars.
        self.bar_sum=self.rect('VorticitySum',0,0,1.2,1.2,CYAN)
        self.bar_sum.hide_render=self.bar_sum.hide_viewport=True
        for bar in (self.bar_f,self.bar_z):bar.parent=self.bar_sum
        def fading(objects):
            sockets=[]
            for obj in objects:
                if obj.type in {'MESH','CURVE','FONT'} and obj.data.materials:
                    sockets+=fade_all_materials(obj)
                    # A fading globe must not reveal its own far side.
                    for mat in obj.data.materials:
                        mat.use_backface_culling=True
                        if hasattr(mat,'use_transparency_overlap'):mat.use_transparency_overlap=False
            return list(objects),sockets
        self.fades={
            'westerly':fading([*self.westerly.children]),
            'flow_ribbon':fading([self.flow]),
            'flow_dots':fading(self.dots),
            'neg':fading(self.neg.children),
            'pos':fading(self.pos.children),
            'wheel_focus':fading([self.wheel_cabin,self.cabin_direction]),
            'wheel_rest':fading([o for o in self.wheel_meshes if o is not self.wheel_cabin and self.wheel_kind[o]!='hidden']),
            'globe':fading([o for o,_ in self.earth_meshes]),
            'air':fading([self.axis,self.local_axis,*self.air.children]),
            'earth_wave':fading(self.earth_wave.children),
            'bars':fading([self.bar_f,self.bar_z]),
        }
        # Only the globes may shade: typography, bars and diagrams are overlays.
        for obj in self.scene.objects:
            if obj.type in {'FONT','CURVE'} or obj in (self.bar_f,self.bar_z,self.bar_sum) or obj in self.dots \
               or obj.name.endswith(('Dot','Heading','Ring')) or 'Parcel' in obj.name:
                obj.visible_shadow=False
        self.track = list(self.scene.objects)
        # Bound after tracking so the callout's own glyphs are not subjects.
        self.callouts=FormulaCallouts(self)
        self.callouts.bind(labels_from_job(self.job),{o.name:o for o in self.scene.objects})
        self.states = [story_state(f,self.job['timeline'],self.fps)
                       for f in range(self.job['duration_frames'])]
        self.spin = [0.0]
        for state in self.states[:-1]:
            self.spin.append(self.spin[-1] + state['relative']*.6/self.fps)
        self.light = next(obj for obj in self.scene.objects if obj.type=='LIGHT')
        self.detach_a=self.t('e2')-self.sec(.6)
        self.detach_b=self.t('s18')+self.sec(5.6)
        self.crest_a=self.pick_crest(self.westerly_world,self.detach_a)
        self.crest_b=self.pick_crest(self.earth_wave_world,self.detach_b)
        # The globe keeps the rest of its ring; the one wavelength that will
        # lift off is drawn by the flat flow's own ribbon from the start.
        for ribbon,crest in ((self.westerly_ribbon,self.crest_a),(self.earth_wave_ribbon,self.crest_b)):
            start=crest+7*math.pi/25;span=math.tau-10*math.pi/25
            for i,point in enumerate(ribbon.data.splines[0].points):
                point.co=(*westerly_point(start+span*i/(len(ribbon.data.splines[0].points)-1),WAVE_RADIUS),1)

    # ----- timing helpers -------------------------------------------------
    def sec(self, seconds):
        return round(seconds*self.fps)

    def t(self, key):
        edge='start_frame' if key[0]=='s' else 'end_frame'
        return self.beats[int(key[1:])][edge]

    def show(self, objects, visible):
        for obj in objects:
            obj.hide_render = obj.hide_viewport = not visible

    def set_fade(self, key, value):
        objects,sockets=self.fades[key]
        for socket in sockets:socket.default_value=max(0.,min(1.,value))
        self.show(objects,value>.001)

    # ----- subject placement ----------------------------------------------
    def westerly_world(self, frame):
        spin=westerly_state(frame/self.fps)['spin']
        return (Matrix.Translation((WESTERLY_PANEL-4,0,0))
                @Matrix.Rotation(WESTERLY_TILT,4,'X')@Matrix.Rotation(spin,4,'Y'))

    def earth_wave_world(self, frame):
        s=self.states[frame]
        return Matrix.Translation((28,0,0))@Matrix.Rotation(s['tilt'],4,'X')@Matrix.Rotation(s['angle'],4,'Y')

    def pick_crest(self, world, frame):
        # Choose the northward crest whose eastward half-wave runs along the
        # bottom of the disk, where north is up and east is right on screen.
        matrix=world(frame)
        step=math.tau/WESTERLY_LOBES
        def middle(k):return (matrix@Vector(westerly_point(k*step+2*math.pi/25,WAVE_RADIUS))).y
        return min(range(WESTERLY_LOBES),key=middle)*step

    def segment_world(self, world, crest, x, radius=WAVE_RADIUS):
        return world@Vector(westerly_point(crest+(x+6)*math.pi/25,radius))

    def segment_zoom(self, world, crest, frame):
        """Frame the one wavelength of the globe wave that will lift off."""
        matrix=world(frame)
        points=[self.segment_world(matrix,crest,x).xy for x in FLAT_X[::10]]
        lo=Vector((min(q.x for q in points),min(q.y for q in points)))
        hi=Vector((max(q.x for q in points),max(q.y for q in points)))
        ortho=max((hi.x-lo.x)*1.35,(hi.y-lo.y)*1.35*16/9,1.)
        return ((lo.x+hi.x)/2,(lo.y+hi.y)/2,ortho)

    def detach(self, frame):
        """Which globe the flat flow's wavelength belongs to, and how far it has lifted."""
        if frame<self.t('s7'):
            return self.westerly_world,self.crest_a,Vector((0,0,0)),FLOW_VIEW,self.detach_a
        return self.earth_wave_world,self.crest_b,Vector((48,0,0)),FLOW48_VIEW,self.detach_b

    def wheel_view(self):
        # Centre the whole model (rim and legs), between the edge labels.
        return (self.wheel_hub.x+16,0.,20.)

    def cabin_world(self, frame):
        return self.wheel_pose(frame)[self.wheel_cabin].translation+Vector((16,0,0))

    def wheel_pose(self, frame):
        angle=WHEEL_SPEED*frame/self.fps
        turn=(Matrix.Translation(self.wheel_hub)@Matrix.Rotation(angle,4,'Z')
              @Matrix.Translation(-self.wheel_hub))
        pose={}
        for o,rest in self.wheel_rest.items():
            kind=self.wheel_kind[o]
            if kind=='spin':pose[o]=turn@rest
            elif kind=='cabin':
                # Cabins hang upright while their hinge follows the rim.
                pose[o]=Matrix.Translation(turn@rest.translation-rest.translation)@rest
            else:pose[o]=rest
        return pose

    def camera_view(self, frame):
        f=frame;S=self.sec;T=self.t
        view=(WESTERLY_PANEL-4,0.,16.)
        zoom_a=self.segment_zoom(self.westerly_world,self.crest_a,f)
        view=lerp(view,zoom_a,phase(f,T('e2')-S(2.2),self.detach_a))
        view=lerp(view,FLOW_VIEW,phase(f,self.detach_a,self.detach_a+S(DETACH_SECONDS)))
        view=lerp(view,RINGS_VIEW,phase(f,T('s4'),T('s4')+S(1.5)))
        view=lerp(view,self.wheel_view(),phase(f,T('e4')+S(.1),T('e4')+S(2.0)))
        cabin=self.cabin_world(f)
        view=lerp(view,(cabin.x,cabin.y+1.3,9.),phase(f,T('s6'),T('s6')+S(1.2)))
        view=lerp(view,EARTH_VIEW,phase(f,T('e6')-S(1.4),T('e6')+S(.6)))
        view=lerp(view,MIGRATION_VIEW,phase(f,T('s13'),T('s13')+S(1)))
        view=lerp(view,EARTH_WAVE_VIEW,phase(f,T('e17')-S(1.4),T('e17')+S(.6)))
        zoom_b=self.segment_zoom(self.earth_wave_world,self.crest_b,f)
        view=lerp(view,zoom_b,phase(f,T('s18')+S(4.0),self.detach_b))
        view=lerp(view,FLOW48_VIEW,phase(f,self.detach_b,self.detach_b+S(DETACH_SECONDS)))
        return view

    def flow_points(self, frame, xs, lift, radius):
        """Flat-flow positions (flow-root local) as they lift off the globe.

        Each point keeps its wave phase: before lifting it lies on the globe
        wave, while lifting it moves on screen from there to its flat place,
        and afterwards it is the flat flow.
        """
        world,crest,offset,final,start=self.detach(frame)
        p=phase(frame,start,start+self.sec(DETACH_SECONDS))
        flats=[Vector((x,1.5*math.cos((x+6)*math.pi/5),lift)) for x in xs]
        if p>=1:return flats
        matrix=world(frame)
        globes=[self.segment_world(matrix,crest,x,radius) for x in xs]
        if p<=0:return [g-offset for g in globes]
        zoom=self.segment_zoom(world,crest,frame);cam=self.camera_view(frame)
        def screen(view,point):return (point.xy-Vector(view[:2]))*16/view[2]
        result=[]
        for g,flat in zip(globes,flats):
            q=screen(zoom,g).lerp(screen(final,flat+offset),p)
            w=Vector(cam[:2])+q*cam[2]/16
            # Rise off the surface first so the fading globe never covers it.
            z=g.z*(1-p)+lift*p+3.5*math.sin(math.pi*p)
            result.append(Vector((w.x,w.y,z))-offset)
        return result

    def wheel_root(self, frame):
        """The wheel starts as the size of the counterclockwise ring."""
        f=frame;S=self.sec;T=self.t
        end=Matrix.Translation((16,0,0))
        ring=POS_SIDE.xy.to_3d()  # PositiveRotor after Scene 4 lines it up
        start=(Matrix.Translation(ring)@Matrix.Scale(RING_RADIUS*RING_GROWTH/4,4)
               @Matrix.Translation(-self.wheel_hub))
        p=phase(f,T('e4')+S(.1),T('e4')+S(2.0))
        if f<T('e4')+S(.1):return start
        if p>=1:return end
        c0,c1=camera_matrix(RINGS_VIEW),camera_matrix(self.wheel_view())
        screen=screen_blend(c0.inverted()@start,c1.inverted()@end,p)
        return camera_matrix(self.camera_view(f))@screen

    # ----- frame evaluation ------------------------------------------------
    def bars_alpha(self, frame):
        """The vorticity bars accompany Scenes 11-17 and leave before the pan."""
        T=self.t
        return max(0.,min(1.,(frame-T('s11'))/(.3*self.fps),(self.bars_end()-1-frame)/(.3*self.fps)))

    def bars_end(self):
        return self.t('e17')-self.sec(1.0)

    def sample(self, frame):
        state = self.states[frame]
        n = state['scene_number']
        fps = self.fps; t=frame/fps; S=self.sec; T=self.t
        for root in self.roots.values():root.matrix_world=Matrix.Identity(4)

        # Opening globe: north pole tipped toward the camera, so eastward
        # motion is counterclockwise on screen around the pole.
        west=westerly_state(t)
        self.westerly.matrix_world=self.westerly_world(frame)
        for i,obj in enumerate(self.westerly_dots):
            longitude=west['parcel_longitude']+i*math.tau/len(self.westerly_dots)
            obj.location=westerly_point(longitude,3.13)
            # Local +X faces the parcel's longitude for the eastward QA check.
            obj.rotation_euler=(0,longitude,0)
        lift_a,lift_b=self.detach_a,self.detach_b
        self.set_fade('westerly',1-phase(frame,lift_a,lift_a+S(1.0)))

        # Flat flow: one wavelength of the globe wave that lifts off, then
        # the setting of the two rotations.
        self.roots['flow'].matrix_world=Matrix.Identity(4) if frame<T('s7') else Matrix.Translation((48,0,0))
        for point,co in zip(self.flow.data.splines[0].points,self.flow_points(frame,FLAT_X,0.,WAVE_RADIUS)):
            point.co=(*co,1)
        self.flow['animate_points']=True
        xs=[-9+(i*.625+t*.75)%10 for i in range(len(self.dots))]
        for obj,co in zip(self.dots,self.flow_points(frame,xs,.25,3.13)):obj.location=co
        leave=1-phase(frame,T('s4')+S(.3),T('s4')+S(1.5))
        if frame<T('s7'):
            ribbon,dots=leave,phase(frame,lift_a,lift_a+S(.8))*leave
        else:
            ribbon,dots=phase(frame,T('s18')+S(.3),T('s18')+S(1.5)),phase(frame,lift_b,lift_b+S(.8))
        self.set_fade('flow_ribbon',ribbon)
        self.set_fade('flow_dots',dots)
        self.neg.rotation_euler.z=-t*.6
        self.pos.rotation_euler.z=t*.6
        opening=lift_a+S(DETACH_SECONDS+.2)
        self.set_fade('neg',(1-phase(frame,T('e4')-S(1.6),T('e4')-S(.8))) if n<=5 else float(n>=19))
        self.set_fade('pos',(1-phase(frame,T('e4')-S(.8),T('e4')+S(.2))) if n<=5 else float(n>=20))
        side=phase(frame,T('s4'),T('s4')+S(1.5)) if frame<T('s7') else 0
        for rotor,start,flow_at,side_at in ((self.neg,opening if n<=5 else T('s19'),NEG_FLOW,NEG_SIDE),
                                            (self.pos,opening if n<=5 else T('s20'),POS_FLOW,POS_SIDE)):
            rotor.location=flow_at.lerp(side_at,side)
            rotor.scale=(max(.001,phase(frame,start,start+fps))*(1+(RING_GROWTH-1)*side),)*3
        self.show([self.neg,self.pos],True)
        self.show(self.south,n>=19)
        self.show(self.north,n>=20)
        self.show([self.latitude,self.parcel,*self.parcel.children,
                   self.comparison_start,*self.comparison_start.children,
                   self.comparison_north,*self.comparison_north.children],False)
        for obj in [*self.south,*self.north]:
            number=19 if obj in self.south else 20
            obj.data.bevel_factor_end=phase(frame,T('s%d'%number),T('s%d'%number)+fps)
            obj['animate_curve_reveal']=True

        # Ferris wheel, rotating counterclockwise without loop jumps.
        for obj,matrix in self.wheel_pose(frame).items():
            obj.matrix_world=matrix
        self.cabin_direction.location=self.wheel_cabin.matrix_world.translation+Vector((0,0,.25))
        self.roots['wheel'].matrix_world=self.wheel_root(frame)
        wheel=phase(frame,T('e4')-S(1.2),T('e4')-S(.2)) if frame<T('e6') else 1-phase(frame,T('e6')+S(.2),T('e6')+S(.6))
        # In the cabin close-up the rest of the wheel steps back.
        close=phase(frame,T('s6'),T('s6')+S(1.2))*(1-phase(frame,T('e6')-S(1.4),T('e6')-S(.4)))
        self.set_fade('wheel_focus',wheel)
        self.set_fade('wheel_rest',wheel*(1-.7*close))

        # Earth, the migrating air parcel, and the returning westerly wave.
        self.set_earth_pose({**state,'latitude':math.radians(state['latitude'])})
        self.air.rotation_euler.rotate_axis('Z',self.spin[frame])
        self.earth_wave.matrix_world=(Matrix.Translation(self.earth_origin)@self.earth_tilt
                                      @Matrix.Rotation(state['physical_angle'],4,'Y'))
        for i,obj in enumerate(self.earth_wave_dots):
            longitude=.3*t+i*math.tau/len(self.earth_wave_dots)
            obj.location=westerly_point(longitude,3.13)
            obj.rotation_euler=(0,longitude,0)
        # Physical rotation stays in the state; ground-relative observation is
        # a change of coordinates applied to this whole group.
        view=self.earth_tilt@Matrix.Rotation(state['observer_angle'],4,'Y')@Matrix.Rotation(-state['tilt'],4,'X')
        center=Vector((-4,0,0))
        self.roots['earth'].matrix_world=(Matrix.Translation((32,0,0))@
            Matrix.Translation(center)@view.inverted()@Matrix.Translation(-center))
        globe=float(T('e6')-S(1.4)<=frame)*(1-phase(frame,lift_b,lift_b+S(1.0)))
        self.set_fade('globe',globe)
        self.set_fade('air',float(frame>=T('e6')-S(1.4))*(1-phase(frame,T('e17')-S(1.4),T('e17')-S(.5))))
        self.set_fade('earth_wave',phase(frame,T('s18')+S(.3),T('s18')+S(1.5))*(1-phase(frame,lift_b,lift_b+S(1.0))))

        # Camera and light follow the subject in the middle of the frame.
        cx,cy,ortho=self.camera_view(frame)
        # Globe waves keep the flat flow's on-screen thickness while zoomed,
        # so the crossfade compares like with like.
        k=ortho/16
        for ribbon,dots in ((self.westerly_ribbon,self.westerly_dots),(self.earth_wave_ribbon,self.earth_wave_dots)):
            ribbon.data.bevel_depth=.09*k;ribbon['animate_bevel']=True
            for obj in dots:obj.scale=(k,k,k)
        # The lifting wavelength keeps the same on-screen thickness as the ring.
        lifting=frame<lift_a+S(DETACH_SECONDS) or T('s18')<=frame<lift_b+S(DETACH_SECONDS)
        k_flow=k if lifting else 1
        self.flow.data.bevel_depth=.09*k_flow;self.flow['animate_bevel']=True
        for obj in self.dots:obj.scale=(k_flow,)*3
        self.camera.location=(cx,cy,25)
        self.camera.rotation_euler=(0,0,0)
        self.camera.data.ortho_scale=ortho
        self.light.location=(cx+2,cy+5,12)
        lighting=self.job.get('variant_profile',{}).get('lighting_profile','base')
        self.light.data.energy={'base':1800,'clear':2200,'cinematic':1300}.get(lighting,1800)
        self.light.rotation_euler=(Vector((cx,cy,0))-self.light.location).to_track_quat('-Z','Y').to_euler()

        # The vorticity bars sit in the lower-right corner at a constant
        # on-screen size; they are shapes, not text.
        u=ortho/16
        self.set_fade('bars',self.bars_alpha(frame))
        length_f=BAR_LENGTH*state['planetary']/state['absolute']
        length_z=BAR_LENGTH-length_f
        self.bar_sum.location=(cx+(3.9+BAR_LENGTH/2)*u,cy-3.55*u,8)
        self.bar_sum.scale=(u,u,1)
        self.bar_f.location=(-BAR_LENGTH/2+length_f/2,0,0)
        self.bar_z.location=(-BAR_LENGTH/2+length_f+length_z/2,0,0)
        self.bar_f.scale=(length_f,.8,1)
        self.bar_z.scale=(max(.0001,length_z),.8,1)
        self.scene.view_layers[0].update()
        return self.job['canonical_state_cache'][frame], self.track

    def insert_keys(self, objects, frame):
        for obj in objects:
            for prop in ('location','rotation_euler','scale','hide_render','hide_viewport'):
                obj.keyframe_insert(data_path=prop,frame=frame)
            if obj.get('animate_points'):
                for point in obj.data.splines[0].points:point.keyframe_insert(data_path='co',frame=frame)
            if obj.get('animate_curve_reveal'):
                obj.data.keyframe_insert(data_path='bevel_factor_end',frame=frame)
            if obj.get('animate_bevel'):
                obj.data.keyframe_insert(data_path='bevel_depth',frame=frame)
            for socket in animated_sockets(obj):socket.keyframe_insert(data_path='default_value',frame=frame)
        self.camera.data.keyframe_insert(data_path='ortho_scale',frame=frame)

    def bake(self):
        """Store every frame as editable keys, written in bulk.

        Inserting keys one by one copies each growing curve, which made the
        full film's bake quadratic. The first frame creates the channels with
        ordinary inserts; every later value is collected and written at once.
        """
        from array import array
        from bpy_extras import anim_utils
        frames=self.job['duration_frames']
        _,objects=self.sample(0)
        self.insert_keys(objects,1)
        owners=[*bpy.data.objects,*bpy.data.curves,*bpy.data.cameras,
                *(m.node_tree for m in bpy.data.materials if m.node_tree)]
        channels=[]
        for owner in owners:
            data=getattr(owner,'animation_data',None)
            if not data or not data.action:continue
            bag=anim_utils.action_get_channelbag_for_slot(data.action,data.action_slot)
            for curve in bag.fcurves:
                value=owner.path_resolve(curve.data_path)
                channels.append((curve,owner,curve.data_path,curve.array_index,hasattr(value,'__len__')))
        values=[array('f') for _ in channels]
        for frame in range(frames):
            self.sample(frame)
            for (curve,owner,path,index,vector),column in zip(channels,values):
                value=owner.path_resolve(path)
                column.append(float(value[index] if vector else value))
        for (curve,*_),column in zip(channels,values):
            points=curve.keyframe_points
            points.add(frames-len(points))
            co=array('f',[0.])*(2*frames)
            co[0::2]=array('f',range(1,frames+1));co[1::2]=column
            points.foreach_set('co',co)
            curve.update()
        self.scene.frame_set(1);self.font.pack();self.fallback_font.pack();bpy.ops.file.pack_all()

    def extra_state(self):
        frame=max(0,min(self.job['duration_frames']-1,self.scene.frame_current-1))
        return {'story':self.states[frame],'size_multiplier':24/self.camera.data.ortho_scale,
                'visible':[obj.name for obj in self.track if not obj.hide_render]}


class FormulaCallouts(CalloutLayer):
    """One formula held across consecutive beats instead of blinking per beat."""

    def update(self, frame, amounts=None):
        g=self.g;fps=g.job['canonical_fps']
        if amounts is None:
            amounts=[]
            for item in self.items:
                key=(item['label']['text'],item['label']['anchor'])
                run=[i['beat'] for i in self.items if (i['label']['text'],i['label']['anchor'])==key]
                start=min(b['start_frame'] for b in run)
                end=min(max(b['end_frame'] for b in run),g.bars_end())
                beat=item['beat']
                inside=beat['start_frame']<=frame<beat['end_frame']
                amounts.append(fade_amount(frame,start,end,fps) if inside else 0.)
        super().update(frame,amounts)
        for item in self.items:
            outline=g.outlines[item['text']]
            outline.hide_render=outline.hide_viewport=item['text'].hide_render
            # A formula sits right beside its bars; a leader stub would only float
            # between them. Its geometry is still recorded for the text gate.
            item['leader'].hide_render=item['leader'].hide_viewport=True
