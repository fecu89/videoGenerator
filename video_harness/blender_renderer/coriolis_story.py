"""Continuous Blender film for the approved 23-beat Coriolis narration.

One globe and one plane carry the whole story. The camera never cuts: the
observer switches between the inertial view (globe turns) and the ground
view (globe held still) through the view root, as described in
coriolis_story_math. No words are drawn; narration and subtitles carry them.
"""
import math
import bmesh
import bpy
from mathutils import Matrix, Vector
from vorticity import VorticityGallery, PINK
from scene import CYAN, GOLD
from animated_materials import fade_all_materials, animated_sockets
from callout import CalloutLayer, labels_from_job
import coriolis_story_math as cm

WHITE = (.93, .95, 1.0)
PALE = (1.0, .86, .45)
RED = (1.0, .25, .25)
VIOLET = (.68, .5, 1.0)   # spin axis and spin direction, distinct from the gold path
TRACK_R = cm.R + .035


def frame_matrix(position, x_axis, z_axis):
    z = Vector(z_axis).normalized()
    x = (Vector(x_axis) - z * Vector(x_axis).dot(z)).normalized()
    y = z.cross(x)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = Vector(position)
    return m


class CoriolisStoryGallery(VorticityGallery):
    # ----- construction helpers ------------------------------------------
    def attach(self, obj, parent):
        obj.parent = parent
        obj.matrix_parent_inverse = Matrix.Identity(4)
        return obj

    def empty(self, name, parent=None):
        obj = self.link(name, None)
        if parent is not None:
            self.attach(obj, parent)
        return obj

    def mesh(self, name, build, color=None, material=None, parent=None):
        bm = bmesh.new()
        build(bm)
        data = bpy.data.meshes.new(name)
        bm.to_mesh(data)
        bm.free()
        for poly in data.polygons:
            poly.use_smooth = True
        obj = self.link(name, data)
        data.materials.append(material or self.material(color))
        if parent is not None:
            self.attach(obj, parent)
        return obj

    def sphere(self, name, radius, color, parent=None, location=(0, 0, 0)):
        def build(bm):
            bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=radius,
                                      matrix=Matrix.Translation(location))
        return self.mesh(name, build, color, parent=parent)

    def cone(self, name, radius, depth, color, parent=None):
        """Tip along local +X with its point at the origin."""
        def build(bm):
            m = (Matrix.Translation((-depth / 2, 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, 'Y'))
            bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=radius, radius2=0,
                                  depth=depth, matrix=m)
        return self.mesh(name, build, color, parent=parent)

    def curve(self, name, points, color, radius, parent):
        obj = self.path(name, [tuple(p) for p in points], color, radius)
        return self.attach(obj, parent)

    def surface_arrow(self, name, points, color, radius, parent, tip=.2):
        shaft = self.curve(name, points, color, radius, parent)
        head = self.cone(name + 'Tip', radius * 3.2, tip, color, parent)
        a, b = Vector(points[-2]), Vector(points[-1])
        head.matrix_basis = frame_matrix(b, b - a, b)
        shaft['tip'] = head.name
        return shaft, head

    def flat_arrow(self, name, length, color, radius, parent):
        """Arrow along local +X from the origin, for per-frame placement."""
        root = self.empty(name, parent)
        tip = .22
        self.curve(name + 'Shaft', [(0, 0, 0), (length - tip * .6, 0, 0)], color, radius, root)
        head = self.cone(name + 'Tip', radius * 3.2, tip, color, root)
        head.location = (length, 0, 0)
        return root

    def arc(self, lat0, lon0, heading, length, turn, r=TRACK_R, steps=40, offset=.0):
        """Track on the sphere from (lat0, lon0): initial heading (deg from north,
        clockwise) and total turn (deg; + is to the right)."""
        p = Vector(cm.point(lat0, lon0, 1))
        e, n = Vector(cm.east(lat0, lon0)), Vector(cm.north(lat0, lon0))
        k = math.radians(turn) / length if abs(turn) > 1e-9 else 0
        h0 = math.radians(heading)
        pts = []
        for i in range(steps + 1):
            s = offset + (length - offset) * i / steps
            if k:
                xe = (math.cos(h0) - math.cos(h0 + k * s)) / k
                xn = (math.sin(h0 + k * s) - math.sin(h0)) / k
            else:
                xe, xn = math.sin(h0) * s, math.cos(h0) * s
            q = p * cm.R + e * xe + n * xn
            pts.append(q.normalized() * r)
        return pts

    def marks(self, track, points, color, fade_key, reveal_key):
        """One arrowhead that rides the leading end of a revealed track."""
        head = self.cone(track.name + 'Head', .15, .34, color, track)
        fade_all_materials(head)
        head.visible_shadow = False
        self.direction_marks.append((head, [Vector(p) for p in points], fade_key, reveal_key))

    def build_plane(self):
        white = bpy.data.materials.new('Plane paint')
        white.use_nodes = True
        bsdf = white.node_tree.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (.95, .96, 1, 1)
        bsdf.inputs['Roughness'].default_value = .35
        bsdf.inputs['Emission Color'].default_value = (.95, .96, 1, 1)
        bsdf.inputs['Emission Strength'].default_value = .35

        def build(bm):
            def box(sx, sy, sz, at):
                bmesh.ops.create_cube(bm, size=1, matrix=Matrix.Translation(at) @ Matrix.Diagonal((sx, sy, sz, 1)))
            bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=.05, radius2=.05, depth=.48,
                                  matrix=Matrix.Rotation(math.pi / 2, 4, 'Y'))
            bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=.05, radius2=.004, depth=.12,
                                  matrix=Matrix.Translation((.3, 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, 'Y'))
            box(.13, .58, .014, (.02, 0, 0))
            box(.06, .2, .012, (-.21, 0, .01))
            box(.07, .012, .1, (-.21, 0, .06))
        self.plane = self.empty('Plane', self.inertial)
        body = self.mesh('PlaneBody', build, material=white, parent=self.plane)
        body.scale = (1.75, 1.75, 1.75)

    # ----- build -----------------------------------------------------------
    def build(self):
        self.fps = self.job['canonical_fps']
        self.story = cm.Story(self.job['timeline'], self.fps)
        self.view = self.empty('ViewRoot')
        self.earth = self.empty('CoriolisEarth', self.view)
        self.inertial = self.empty('InertialSpace', self.view)
        imported, meshes = self.import_meshes('earth.glb')
        self.scene.view_layers[0].update()
        pts = [o.matrix_world @ Vector(v) for o in meshes for v in o.bound_box]
        lo = Vector([min(v[i] for v in pts) for i in range(3)])
        hi = Vector([max(v[i] for v in pts) for i in range(3)])
        norm = Matrix.Rotation(-math.pi / 2, 4, 'X') @ Matrix.Scale(2 * cm.R / max(hi - lo), 4) @ Matrix.Translation(-(lo + hi) / 2)
        for o in meshes:
            local = norm @ o.matrix_world.copy()
            o.parent = None
            o.animation_data_clear()
            o.rotation_mode = 'XYZ'
            self.attach(o, self.earth)
            o.matrix_basis = local
            o.name = 'Globe'
        for o in imported:
            if o not in meshes:
                bpy.data.objects.remove(o, do_unlink=True)
        E, I = self.earth, self.inertial
        S = cm.SEOUL
        fades = {}

        # Opening: Seoul, the aim line and the inertial path.
        self.seoul = self.empty('SeoulPin', E)
        self.seoul.matrix_basis = frame_matrix(cm.point(*S), cm.east(*S), cm.up(*S))
        pin = [self.curve('SeoulPinStick', [(0, 0, 0), (0, 0, .2)], WHITE, .02, self.seoul),
               self.sphere('SeoulPinHead', .1, RED, self.seoul, (0, 0, .24))]
        fades['seoul'] = pin
        meridian = lambda r: [cm.point(90 - (90 - S[0]) * i / 60, 0, r) for i in range(61)]
        self.aim = self.curve('AimLine', meridian(TRACK_R), GOLD, .03, I)
        self.inertial_track = self.curve('InertialTrack', meridian(cm.R + cm.PLANE_ALT), GOLD, .05, I)
        self.axis = self.curve('SpinAxis', [(0, -4.4, 0), (0, 4.4, 0)], VIOLET, .05, I)
        # Eastward turn seen from the north: increasing longitude about +Y.
        spin = [(.85 * math.cos(math.radians(a)), 4.05, -.85 * math.sin(math.radians(a))) for a in range(20, 301, 5)]
        fades['spin_arrow'] = list(self.surface_arrow('SpinArrow', spin, VIOLET, .045, I, tip=.3))
        fades.update(aim=[self.aim], inertial=[self.inertial_track], axis=[self.axis])
        arrival = cm.ARRIVAL
        ring = []
        c, e, n = Vector(cm.point(*arrival, 1)), Vector(cm.east(*arrival)), Vector(cm.north(*arrival))
        for i in range(49):
            a = math.tau * i / 48
            ring.append((c * cm.R + (e * math.cos(a) + n * math.sin(a)) * .24).normalized() * TRACK_R)
        fades['arrival'] = [self.curve('ArrivalMark', ring, WHITE, .025, E)]
        # The route first aimed at: the straight line from the pole to Seoul.
        route = [cm.point(90 - (90 - S[0]) * i / 60, S[1], TRACK_R + .01) for i in range(61)]
        self.route = self.surface_arrow('SeoulRoute', route, GOLD, .04, E, tip=.3)
        fades['route'] = list(self.route)

        # Ground track of the first flight and the moving apparent-force arrow.
        self.track1_pts = [Vector(cm.point(*cm.track1(i / 120), TRACK_R)) for i in range(121)]
        self.track1 = self.curve('GroundTrack', self.track1_pts, CYAN, .05, E)
        self.direction_marks = []
        self.marks(self.inertial_track, meridian(cm.R + cm.PLANE_ALT), GOLD, 'inertial', 'flight1')
        self.marks(self.track1, self.track1_pts, CYAN, 'track1', 'track1')
        fades['track1'] = [self.track1]
        self.marker = self.sphere('TrackMarker', .09, WHITE, E)
        self.coriolis_arrow = self.flat_arrow('CoriolisArrow', .75, PINK, .035, E)
        fades['marker'] = [self.marker, self.coriolis_arrow, *self.coriolis_arrow.children]

        self.build_plane()
        fades['plane'] = [self.plane.children[0]]

        # Second flight from the equator.
        eq = cm.EQUATOR_START
        fades['aim2'] = [self.curve('AimLine2', [cm.point(eq[0] + (90 - eq[0]) * i / 60, eq[1], TRACK_R) for i in range(61)], GOLD, .03, E)]
        speeds = []
        for k, lat in enumerate((0, 20, 40, 60)):
            length = 1.6 * math.cos(math.radians(lat))
            span = math.degrees(length / (cm.R * math.cos(math.radians(lat))))
            start = eq[1] + 3
            pts = [cm.point(lat, start + span * i / 24, cm.R + .06) for i in range(25)]
            speeds.append(self.surface_arrow('GroundSpeed%02d' % lat, pts, WHITE, .035, E))
        self.ground_speed = speeds
        fades.update({'ground_speed%d' % k: list(a) for k, a in enumerate(speeds)})
        self.plane_east = self.flat_arrow('PlaneEastArrow', 1.6, GOLD, .035, E)
        fades['plane_east'] = [self.plane_east, *self.plane_east.children]
        self.track2 = self.curve('EquatorTrack', [cm.point(*self.story.track2(i / 120), TRACK_R) for i in range(121)], CYAN, .05, E)
        fades['track2'] = [self.track2]
        self.marks(self.track2, [Vector(cm.point(*self.story.track2(i / 120), TRACK_R)) for i in range(121)], CYAN, 'track2', 'track2')
        self.plane_arrow = self.flat_arrow('CoriolisArrowPlane', .75, PINK, .035, E)
        fades['plane_arrow'] = [self.plane_arrow, *self.plane_arrow.children]
        pair = []
        for key, pts in (('A', self.track1_pts), ('B', [Vector(cm.point(*self.story.track2(i / 120), TRACK_R)) for i in range(121)])):
            idx = 60 if key == 'A' else 72
            p, q = pts[idx], pts[idx + 1]
            upv = p.normalized()
            right = (q - p).normalized().cross(upv)
            arrow = self.flat_arrow('CoriolisArrow' + key, .75, PINK, .035, E)
            arrow.matrix_basis = frame_matrix(p + upv * .03, right, upv)
            fades['pair_' + key.lower()] = [arrow, *arrow.children]

        # Directions and latitudes.
        compass_lon = self.states_probe('compass_lon')
        lat_lon = self.states_probe('latitude_lon')
        self.compass = {}
        for key, lat, turn in (('n', 40.0, 75.0), ('s', -40.0, -75.0)):
            arrows = []
            for i, heading in enumerate((0, 90, 180, 270)):
                pts = self.arc(lat, compass_lon, heading, 1.15, turn, offset=.18)
                arrows.append(self.surface_arrow('Compass%s%02d' % (key.upper(), i), pts, CYAN, .04, E))
            self.compass[key] = arrows
            fades['compass_' + key] = [o for a in arrows for o in a]
        # Strength: one northward path on the centre meridian, and the
        # apparent force to its right with length proportional to sin(latitude).
        north_path = [cm.point(82 * i / 60, lat_lon, cm.R + .05) for i in range(61)]
        self.northward = self.surface_arrow('NorthwardPath', north_path, CYAN, .05, E, tip=.3)
        fades['latitudes'] = list(self.northward)
        self.forces = []
        for lat in (20, 40, 60, 80):
            base = Vector(cm.point(lat, lat_lon, cm.R + .07))
            arrow = self.flat_arrow('Force%02d' % lat, 1.3 * math.sin(math.radians(lat)), PINK, .045, E)
            self.forces.append((arrow, frame_matrix(base, cm.east(lat, lat_lon), base)))
        zero = self.sphere('ForceZero', .08, PINK, E, cm.point(0, lat_lon, cm.R + .07))
        fades['forces'] = [o for a, _ in self.forces for o in (a, *a.children)] + [zero]
        verticals, components = [], []
        for lat in (90, 60, 30, 0):
            # On the right-hand limb meridian so each bar is seen in profile.
            base = Vector(cm.point(lat, lat_lon + 90))
            upv = base.normalized()
            verticals.append(self.curve('LocalVertical%02d' % lat, [base, base + upv * 1.3], WHITE, .035, E))
            comp = self.curve('VerticalComponent%02d' % lat,
                              [base, base + upv * max(.001, 1.3 * math.sin(math.radians(lat)))], CYAN, .075, E)
            components.append(comp)
        self.components = components
        fades.update(verticals=verticals, components=components)

        # Low pressure: inflow deflected right, the swirl, the equator band.
        def spiral(lat, lon, alpha0, k, r0=1.05, r1=.26, steps=40):
            c = Vector(cm.point(lat, lon, 1))
            e, n = Vector(cm.east(lat, lon)), Vector(cm.north(lat, lon))
            pts = []
            for i in range(steps + 1):
                r = r0 * (r1 / r0) ** (i / steps)
                a = alpha0 + k * math.log(r0 / r)
                pts.append((c * cm.R + (e * math.cos(a) + n * math.sin(a)) * r).normalized() * (cm.R + .06))
            return pts
        self.inflow = [self.surface_arrow('Inflow%02d' % i, spiral(*cm.TYPHOON, math.tau * i / 8, .95), WHITE, .035, E)
                       for i in range(8)]
        fades['inflow'] = [o for a in self.inflow for o in a]
        self.equator_inflow = [self.surface_arrow('EquatorInflow%02d' % i, spiral(*cm.EQUATOR_LOW, math.tau * i / 8, 0.0, .95, .2), WHITE, .035, E)
                               for i in range(8)]
        fades['equator_inflow'] = [o for a in self.equator_inflow for o in a]
        self.swirl = self.empty('TyphoonSwirl', E)
        arms = []
        for i in range(3):
            pts = []
            for j in range(41):
                r = .12 + .72 * j / 40
                a = math.tau * i / 3 + 2.4 * (1 - j / 40)
                pts.append((r * math.cos(a), r * math.sin(a), .08 + r * r / (2 * cm.R)))
            arms.append(self.curve('SwirlArm%d' % i, pts, WHITE, .045, self.swirl))
        arms.append(self.sphere('SwirlEye', .09, (.6, .8, 1), self.swirl, (0, 0, .1)))
        fades['swirl'] = arms
        self.swirl_base = frame_matrix(cm.point(*cm.TYPHOON, cm.R + .02), cm.east(*cm.TYPHOON), cm.up(*cm.TYPHOON))

        def band(bm):
            verts = {}
            for i in range(97):
                for j, lat in enumerate((-4, 4)):
                    verts[i, j] = bm.verts.new(cm.point(lat, 360 * i / 96, cm.R + .02))
            for i in range(96):
                bm.faces.new((verts[i, 0], verts[i + 1, 0], verts[i + 1, 1], verts[i, 1]))
        fades['band'] = [self.mesh('EquatorBand', band, PALE, parent=E)]

        # Only the globe and the plane are shaded; diagrams are overlays.
        for obj in self.scene.objects:
            if obj.type == 'CURVE' or obj.name.startswith(('Swirl', 'Track', 'SeoulPin', 'Equator')):
                obj.visible_shadow = False
        self.fades = {}
        for key, objects in fades.items():
            sockets = []
            for obj in objects:
                if obj.type in {'MESH', 'CURVE'} and obj.data.materials:
                    sockets += fade_all_materials(obj)
            self.fades[key] = (objects, sockets)
        for obj in self.scene.objects:
            if obj.type == 'CURVE' and obj.name in {'AimLine', 'InertialTrack', 'GroundTrack', 'EquatorTrack'} or \
               obj.name.startswith(('Compass', 'NorthwardPath', 'SeoulRoute', 'VerticalComponent', 'Inflow', 'EquatorInflow')) and obj.type == 'CURVE':
                obj['animate_curve_reveal'] = True
        self.axis['animate_bevel'] = True
        self.track = list(self.scene.objects)
        # Subtitle films declare no labels; the layer stays bound but empty.
        self.callouts = CalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job), {o.name: o for o in self.scene.objects})
        self.light = next(obj for obj in self.scene.objects if obj.type == 'LIGHT')
        self.states = [self.story.state(f) for f in range(self.job['duration_frames'])]

    def states_probe(self, key):
        return self.story.state(0)[key]

    # ----- per-frame ---------------------------------------------------------
    def show(self, objects, visible):
        for obj in objects:
            obj.hide_render = obj.hide_viewport = not visible

    def set_fade(self, key, value):
        objects, sockets = self.fades[key]
        for socket in sockets:
            socket.default_value = max(0., min(1., value))
        self.show(objects, value > .001)

    def reveal(self, shaft_and_tip, value, fade_key_value):
        shaft, tip = shaft_and_tip
        shaft.data.bevel_factor_end = max(.0005, min(1., value))
        amount = fade_key_value * cm.smooth((value - .9) / .1)
        for socket in animated_sockets(tip):
            socket.default_value = max(0., min(1., amount))
        self.show([tip], amount > .001)

    def sample(self, frame):
        st = self.states[frame]
        rad = math.radians
        self.view.matrix_world = Matrix.Rotation(rad(st['tilt']), 4, 'X') @ Matrix.Rotation(rad(-st['psi']), 4, 'Y')
        self.earth.matrix_basis = Matrix.Rotation(rad(st['phi']), 4, 'Y')
        self.aim.matrix_basis = Matrix.Rotation(rad(st['aim_lon']), 4, 'Y')
        self.inertial_track.matrix_basis = Matrix.Rotation(rad(st['inertial_lon']), 4, 'Y')
        self.inertial_track.data.bevel_factor_end = max(.0005, st['flight1'])
        self.axis.data.bevel_depth = .05 * st['axis_width']
        fd, rv = st['fades'], st['reveals']
        for key in ('aim', 'inertial', 'seoul', 'axis', 'spin_arrow', 'arrival', 'track1', 'marker', 'plane', 'aim2',
                    'plane_east', 'track2', 'plane_arrow', 'pair_a', 'pair_b', 'verticals', 'components',
                    'swirl', 'band'):
            self.set_fade(key, fd[key])
        for k, value in enumerate(fd['ground_speed']):
            self.set_fade('ground_speed%d' % k, value)
        for key in ('compass_n', 'compass_s', 'latitudes', 'forces', 'route', 'inflow', 'equator_inflow'):
            self.set_fade(key, fd[key])
        self.track1.data.bevel_factor_end = max(.0005, rv['track1'])
        progress = dict(rv, flight1=st['flight1'])
        for obj, pts, fade_key, reveal_key in self.direction_marks:
            value = max(0., min(1., progress[reveal_key]))
            x = value * (len(pts) - 1)
            i = min(len(pts) - 2, int(x))
            tip = pts[i].lerp(pts[i + 1], x - i)
            obj.matrix_basis = frame_matrix(tip + tip.normalized() * .01, pts[i + 1] - pts[i], tip)
            amount = fd[fade_key] * cm.smooth(value / .03)
            for socket in animated_sockets(obj):
                socket.default_value = max(0., min(1., amount))
            self.show([obj], amount > .001)
        self.track2.data.bevel_factor_end = max(.0005, rv['track2'])
        for key in ('n', 's'):
            for arrow in self.compass[key]:
                self.reveal(arrow, rv['compass_' + key], fd['compass_' + key])
        self.reveal(self.northward, rv['latitudes'], fd['latitudes'])
        grow = max(.001, rv['forces'])
        for arrow, base in self.forces:
            arrow.matrix_basis = base @ Matrix.Diagonal((grow, 1, 1, 1))
        self.reveal(self.route, rv['route'], fd['route'])
        for arrow in self.inflow:
            self.reveal(arrow, rv['inflow'], fd['inflow'])
        for arrow in self.equator_inflow:
            self.reveal(arrow, rv['equator_inflow'], fd['equator_inflow'])
        for comp in self.components:
            comp.data.bevel_factor_end = max(.0005, rv['components'])

        # Marker and apparent-force arrow along the first ground track.
        u = st['marker'] * 119.999
        i = int(u)
        p = self.track1_pts[i].lerp(self.track1_pts[i + 1], u - i)
        d = self.track1_pts[i + 1] - self.track1_pts[i]
        upv = p.normalized()
        self.marker.location = p + upv * .04
        self.coriolis_arrow.matrix_basis = frame_matrix(p + upv * .05, d.normalized().cross(upv), upv)

        # The plane lives in inertial space; ground-attached arrows follow it.
        pos, head = Vector(st['plane_pos']), Vector(st['plane_head'])
        self.plane.matrix_basis = frame_matrix(pos, head, pos.normalized())
        ground = Matrix.Rotation(rad(-st['phi']), 4, 'Y')
        gpos, ghead = ground @ pos, (ground.to_3x3() @ head)
        gup = gpos.normalized()
        lat = math.degrees(math.asin(max(-1, min(1, gup.y))))
        lon = math.degrees(math.atan2(-gup.z, gup.x))
        self.plane_east.matrix_basis = frame_matrix(gpos, cm.east(lat, lon), gup)
        self.plane_arrow.matrix_basis = frame_matrix(gpos, ghead.normalized().cross(gup), gup)

        spin = Matrix.Rotation(rad(st['swirl']), 4, 'Z')
        self.swirl.matrix_basis = self.swirl_base @ spin

        # Camera and light.
        cx, cy = st['center']
        ortho = st['ortho']
        profile = self.job.get('variant_profile', {}) or {}
        ortho *= {'close': .9, 'restrained': 1.04}.get(profile.get('camera_profile'), 1.0)
        self.camera.location = (cx, cy, 25)
        self.camera.rotation_euler = (0, 0, 0)
        self.camera.data.ortho_scale = ortho
        self.light.location = (cx - 5, cy + 6, 14)
        self.light.data.energy = {'clear': 2600, 'cinematic': 1600}.get(profile.get('lighting_profile'), 2100)
        self.light.data.size = 16
        self.light.rotation_euler = (Vector((cx, cy, 0)) - self.light.location).to_track_quat('-Z', 'Y').to_euler()
        self.scene.view_layers[0].update()
        return self.job['canonical_state_cache'][frame], self.track

    # ----- editable keys (bulk, as in the vorticity story) -------------------
    def insert_keys(self, objects, frame):
        for obj in objects:
            for prop in ('location', 'rotation_euler', 'scale', 'hide_render', 'hide_viewport'):
                obj.keyframe_insert(data_path=prop, frame=frame)
            if obj.get('animate_curve_reveal'):
                obj.data.keyframe_insert(data_path='bevel_factor_end', frame=frame)
            if obj.get('animate_bevel'):
                obj.data.keyframe_insert(data_path='bevel_depth', frame=frame)
            for socket in animated_sockets(obj):
                socket.keyframe_insert(data_path='default_value', frame=frame)
        self.camera.data.keyframe_insert(data_path='ortho_scale', frame=frame)

    def bake(self):
        from array import array
        from bpy_extras import anim_utils
        frames = self.job['duration_frames']
        _, objects = self.sample(0)
        self.insert_keys(objects, 1)
        owners = [*bpy.data.objects, *bpy.data.curves, *bpy.data.cameras,
                  *(m.node_tree for m in bpy.data.materials if m.node_tree)]
        channels = []
        for owner in owners:
            data = getattr(owner, 'animation_data', None)
            if not data or not data.action:
                continue
            bag = anim_utils.action_get_channelbag_for_slot(data.action, data.action_slot)
            for curve in bag.fcurves:
                value = owner.path_resolve(curve.data_path)
                channels.append((curve, owner, curve.data_path, curve.array_index, hasattr(value, '__len__')))
        values = [array('f') for _ in channels]
        for frame in range(frames):
            self.sample(frame)
            for (curve, owner, path, index, vector), column in zip(channels, values):
                value = owner.path_resolve(path)
                column.append(float(value[index] if vector else value))
        for (curve, *_), column in zip(channels, values):
            points = curve.keyframe_points
            points.add(frames - len(points))
            co = array('f', [0.]) * (2 * frames)
            co[0::2] = array('f', range(1, frames + 1))
            co[1::2] = column
            points.foreach_set('co', co)
            curve.update()
        self.scene.frame_set(1)
        bpy.ops.file.pack_all()

    def extra_state(self):
        frame = max(0, min(self.job['duration_frames'] - 1, self.scene.frame_current - 1))
        st = self.states[frame]
        return {'beat': st['beat'], 'phi': st['phi'], 'psi': st['psi'], 'tilt': st['tilt'],
                'flight1': st['flight1'], 'flight2': st['flight2'],
                'visible': [obj.name for obj in self.track if not obj.hide_render]}
