"""Continuous Blender film for the approved 17-beat phantom-jam narration.

Car motion comes from phantom_jam_math (an optimal-velocity model integrated
once). This file only builds the world and applies each frame's state. No
words are drawn; narration and subtitles carry them.
"""
import math
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix, Vector
from scene import SpectralGallery
from animated_materials import fade_all_materials, animated_sockets
from callout import CalloutLayer, labels_from_job
import phantom_jam_math as pm

TYPES = ['Sedan Body', 'Hatchback Body', 'SUV Body', 'Compact Body', 'Wagon Body',
         'minivan body', 'Pickup Body', 'Sport body', 'Offroad Body']
SKY = (.55, .74, .97)
GRASS = (.16, .30, .09)
ASPHALT = (.055, .057, .062)
PAINT = (.92, .92, .88)
GOLD = (1.0, .72, .12)
RED = (1.0, .12, .08)
TEAL = (.1, .9, .85)
WHITE = (.95, .96, 1.0)
WHEEL_R = 0.3


def principled(name, color, roughness=.9, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*color, 1)
        bsdf.inputs['Emission Strength'].default_value = emission
    return mat


class PhantomJamGallery(SpectralGallery):
    # ----- construction helpers ------------------------------------------------
    def mesh_object(self, name, build, material, parent=None):
        bm = bmesh.new()
        build(bm)
        data = bpy.data.meshes.new(name)
        bm.to_mesh(data)
        bm.free()
        obj = self.link(name, data)
        data.materials.append(material)
        if parent is not None:
            obj.parent = parent
        return obj

    def annulus(self, name, r0, r1, material, z=0.0, a0=0.0, a1=math.tau, segments=192, parent=None):
        def build(bm):
            inner, outer = [], []
            for k in range(segments + 1):
                a = a0 + (a1 - a0) * k / segments
                inner.append(bm.verts.new((r0 * math.cos(a), r0 * math.sin(a), z)))
                outer.append(bm.verts.new((r1 * math.cos(a), r1 * math.sin(a), z)))
            for k in range(segments):
                bm.faces.new((inner[k], outer[k], outer[k + 1], inner[k + 1]))
        return self.mesh_object(name, build, material, parent)

    def rect(self, name, x0, x1, y0, y1, material, z=0.0):
        def build(bm):
            v = [bm.verts.new(p) for p in ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))]
            bm.faces.new(v)
        return self.mesh_object(name, build, material)

    def emission(self, name, color, strength):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        emit = nodes.new('ShaderNodeEmission')
        emit.name = 'Glow'
        emit.inputs['Color'].default_value = (*color, 1)
        emit.inputs['Strength'].default_value = strength
        out = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(emit.outputs[0], out.inputs['Surface'])
        return mat

    # ----- world -------------------------------------------------------------------
    def build_world(self):
        scene = self.scene
        scene.view_settings.view_transform = 'Standard'
        scene.eevee.taa_render_samples = 16
        world = scene.world
        world.use_nodes = True
        bg = world.node_tree.nodes['Background']
        bg.inputs['Color'].default_value = (*SKY, 1)
        bg.inputs['Strength'].default_value = 0.9
        for obj in list(scene.objects):
            if obj.type == 'LIGHT':
                bpy.data.objects.remove(obj, do_unlink=True)
        sun = bpy.data.lights.new('Sun', 'SUN')
        sun.energy = 2.6
        sun.angle = math.radians(3)
        self.sun = self.link('Sun', sun)
        self.sun.rotation_euler = (math.radians(42), 0, math.radians(35))
        cam = self.camera.data
        cam.type = 'PERSP'
        cam.sensor_width = 36
        cam.clip_start = .3
        cam.clip_end = 4000
        grass = principled('Grass', GRASS, 1.0)
        self.rect('Ground', -9000, 9000, -9000, 9000, grass, -0.03)
        asphalt = principled('Asphalt', ASPHALT, .85)
        paint = principled('Paint', PAINT, .6)
        R, W = pm.RING_R, pm.LANE_W / 2
        self.annulus('RingRoad', R - W, R + W, asphalt, 0.0)
        self.annulus('RingEdgeIn', R - W + .1, R - W + .28, paint, .01)
        self.annulus('RingEdgeOut', R + W - .28, R + W - .1, paint, .01)
        ox, oy = pm.HWY_ORIGIN
        self.rect('Highway', ox - 1200, ox + 2600, oy - 4.6, oy + 4.6, asphalt, 0.0)
        self.rect('HighwayEdgeL', ox - 1200, ox + 2600, oy + 3.9, oy + 4.1, paint, .01)
        self.rect('HighwayEdgeR', ox - 1200, ox + 2600, oy - 4.1, oy - 3.9, paint, .01)

        def dashes(bm):
            x = ox - 1200
            while x < ox + 2600:
                v = [bm.verts.new(p) for p in ((x, oy - .09, .01), (x + 3, oy - .09, .01), (x + 3, oy + .09, .01), (x, oy + .09, .01))]
                bm.faces.new(v)
                x += 9
        self.mesh_object('HighwayDashes', dashes, paint)
        # Flat ground never needs to cast a shadow; letting the 18 km plane cast
        # one onto itself shows up as diagonal shadow-acne stripes in the grass.
        for name in ('Ground', 'RingRoad', 'RingEdgeIn', 'RingEdgeOut', 'Highway',
                     'HighwayEdgeL', 'HighwayEdgeR', 'HighwayDashes'):
            self.scene.objects[name].visible_shadow = False

    # ----- cars ------------------------------------------------------------------------
    def build_templates(self):
        before = set(self.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(Path(self.job['style']['asset_root']) / 'generic_passenger_car_pack.glb'))
        imported = list(set(self.scene.objects) - before)
        self.scene.view_layers[0].update()
        wheels = [o for o in imported if o.type == 'MESH' and any(p.name.startswith('Wheel') for p in parents(o))]
        self.templates = {}
        scale = Matrix.Scale(pm.CAR_SCALE, 4)
        bodies = [o for o in imported if o.type == 'EMPTY' and o.name.lower().endswith('body')]
        def body_centre(body):
            pts = [c.matrix_world @ Vector(v) for c in body.children if c.type == 'MESH' for v in c.bound_box]
            return Vector((sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts), 0))
        centres = {b.name: body_centre(b) for b in bodies}
        owner = {w.name: min(centres, key=lambda n: (wheel_centre(w) - centres[n]).xy.length) for w in wheels}
        for name in TYPES:
            body = next(o for o in imported if o.type == 'EMPTY' and o.name == name)
            m3 = body.matrix_world.to_3x3()
            fwd = (m3 @ Vector((0, 0, -1))).normalized()
            up = (m3 @ Vector((0, -1, 0))).normalized()
            lat = up.cross(fwd)
            parts = [c for c in body.children if c.type == 'MESH']
            pts = [c.matrix_world @ Vector(v) for c in parts for v in c.bound_box]
            centre = Vector((sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts), 0))
            frame = Matrix((fwd, lat, up)).transposed().to_4x4()
            frame.translation = centre
            to_car = scale @ frame.inverted()
            mine = [w for w in wheels if owner[w.name] == name and (wheel_centre(w) - centre).xy.length < 2.8]
            body_mesh = join_meshes(name + ' template', [(p, to_car @ p.matrix_world) for p in parts])
            wheel_meshes = []
            for w in mine:
                data = w.data.copy()
                data.transform(to_car @ w.matrix_world)
                c = mesh_centre(data)
                data.transform(Matrix.Translation(-c))
                wheel_meshes.append((data, c))
            full = join_meshes(name + ' full', [(p, to_car @ p.matrix_world) for p in parts] +
                               [(w, to_car @ w.matrix_world) for w in mine])
            lo, hi = mesh_bounds(body_mesh)
            self.templates[name] = dict(body=body_mesh, wheels=wheel_meshes, full=full, lo=lo, hi=hi)
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)

    def brake_light(self, name, template, parent):
        lo, hi = template['lo'], template['hi']
        height = lo.z + .45 * (hi.z - lo.z)
        half = (hi.y - lo.y) / 2 - .42
        # Sit on the actual rear surface at tail-light height.
        rear = [v.co.x for v in template['body'].vertices if abs(v.co.z - height) < .1 and abs(v.co.y) < half + .15]
        x = (min(rear) if rear else lo.x) - .015

        def build(bm):
            for side in (-1, 1):
                y = side * half
                v = [bm.verts.new(p) for p in ((x, y - .14, height - .06), (x, y + .14, height - .06),
                                               (x, y + .14, height + .06), (x, y - .14, height + .06))]
                bm.faces.new(v)
        mat = self.emission(name + ' glow', (1.0, .03, .015), 0.0)
        light = self.mesh_object(name, build, mat, parent)
        light['animated_socket'] = 'Glow'
        light['animated_input'] = 1
        light.visible_shadow = False
        return light

    def ring_marker(self, name, color, parent):
        mat = self.emission(name + ' glow', color, 2.5)
        obj = self.annulus(name, 2.55, 2.95, mat, .05, segments=64, parent=parent)
        fade_all_materials(obj)
        obj.visible_shadow = False
        return obj

    def build_cars(self):
        st = self.story
        self.ring_cars = []
        for i in range(pm.RING_N):
            tpl = self.templates[TYPES[(i * 4) % len(TYPES)]]
            root = self.link('Car%02d' % i, tpl['body'])
            wheels = []
            for k, (data, offset) in enumerate(tpl['wheels']):
                w = self.link('Car%02dWheel%d' % (i, k), data)
                w.parent = root
                w.location = offset
                wheels.append(w)
            brake = self.brake_light('Car%02dBrake' % i, tpl, root)
            self.ring_cars.append((root, wheels, brake))
        self.marker_a = self.ring_marker('MarkerA', GOLD, None)
        self.marker_stop = self.ring_marker('MarkerStop', RED, None)
        self.marker_av = self.ring_marker('MarkerAV', TEAL, None)
        self.highway_cars = {}
        for lane in ('L', 'R'):
            offset = st.chase if lane == 'R' else 0
            cars = []
            for i in range(pm.HWY_N):
                tpl = self.templates[TYPES[(i * 5 + (3 if lane == 'L' else 0)) % len(TYPES)]]
                # The lane-R car that camera 1 chases is named 07 (continuity actor).
                label = (i - offset + 7) % pm.HWY_N if lane == 'R' else i
                root = self.link('HwyCar_%s_%02d' % (lane, label), tpl['full'])
                brake = self.brake_light('HwyCar_%s_%02dBrake' % (lane, label), tpl, root)
                cars.append((root, brake))
            self.highway_cars[lane] = cars

    def build_overlays(self):
        mat = self.emission('Jam band', RED, 1.6)
        R, W = pm.RING_R, pm.LANE_W / 2
        self.band = []
        for k in range(96):
            a0, a1 = math.tau * k / 96, math.tau * (k + 1) / 96
            seg = self.annulus('JamBand%02d' % k, R - W + .3, R + W - .3, mat.copy(), .03, a0, a1, 4)
            fade_all_materials(seg)
            seg.visible_shadow = False
            self.band.append(seg)
        self.arrows = []
        for name, radius, a0, a1, color in (('CarDirection', 22.0, math.radians(200), math.radians(290), WHITE),
                                            ('JamDirection', 16.0, math.radians(290), math.radians(200), RED)):
            pts = [(radius * math.cos(a0 + (a1 - a0) * k / 40), radius * math.sin(a0 + (a1 - a0) * k / 40), .2) for k in range(41)]
            shaft = self.path(name, pts[:-3], color, .45)
            tip_mat = self.emission(name + ' tip', color, 1.4)
            end, before_end = Vector(pts[-1]), Vector(pts[-4])
            d = (end - before_end).normalized()
            side = Vector((-d.y, d.x, 0)) * 1.6

            def build(bm, end=end, d=d, side=side):
                v = [bm.verts.new(p) for p in (end + d * .6, before_end - side, before_end + side)]
                bm.faces.new(v)
            tip = self.mesh_object(name + 'Tip', build, tip_mat)
            for obj in (shaft, tip):
                obj.data.materials[0] = obj.data.materials[0].copy()
                fade_all_materials(obj)
                obj.visible_shadow = False
            self.arrows += [shaft, tip]
        self.jam_marker = self.link('JamMarker', None)

    # ----- build -------------------------------------------------------------------------
    def build(self):
        self.fps = self.job['canonical_fps']
        self.story = pm.Story(self.job['timeline'], self.fps)
        self.scene.name = 'Phantom Jam ' + self.job['sequence_id']
        self.camera.name = 'PhantomJamCamera'
        self.build_world()
        self.build_templates()
        self.build_cars()
        self.build_overlays()
        self.animated = [o for o in self.scene.objects
                         if o.name.startswith(('Car', 'HwyCar', 'Marker', 'JamBand', 'CarDirection', 'JamDirection', 'JamMarker'))
                         or o == self.camera]
        self.callouts = CalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job), {o.name: o for o in self.scene.objects})

    # ----- per frame ---------------------------------------------------------------------
    # Nothing toggles hide_render: EEVEE re-syncs the whole scene on every render
    # when objects carry both transform and visibility keys (about 10x slower).
    # Cars off stage are parked underground; overlays fade through their opacity.
    PARK = -60.0

    @staticmethod
    def glow(obj, value):
        for socket in animated_sockets(obj):
            socket.default_value = value

    @staticmethod
    def brake_level(v, a, pedal=0.0):
        return max(min(1.0, max(0.0, -a) / 1.2), .8 if v < .3 else 0.0, pedal)

    def place_ring_car(self, i, x, v, a, pedal):
        root, wheels, brake = self.ring_cars[i]
        (px, py, _), (dx, dy, _) = self.story.ring_point(x)
        root.location = (px, py, 0)
        root.rotation_euler = (0, 0, math.atan2(dy, dx))
        spin = (x / WHEEL_R) % math.tau
        for w in wheels:
            w.rotation_euler = (0, spin, 0)
        self.glow(brake, .06 + 5.0 * self.brake_level(v, a, pedal))

    def follow_marker(self, marker, car, x, amount):
        if car is not None:
            (px, py, _), _ = self.story.ring_point(x[car])
            marker.location = (px, py, 0)
        for socket in animated_sockets(marker):
            socket.default_value = amount

    def sample(self, frame):
        st = self.story.state(frame)
        ring = st['place'] == 'ring'
        if ring:
            for i in range(pm.RING_N):
                self.place_ring_car(i, st['x'][i], st['v'][i], st['a'][i], st['pedal'][i])
            mk = st['markers']
            self.follow_marker(self.marker_a, pm.CAR_A, st['x'], mk['a'])
            self.follow_marker(self.marker_stop, self.story.stopper, st['x'], mk['stop'])
            self.follow_marker(self.marker_av, self.story.av_car, st['x'], mk['av'])
            for seg, level in zip(self.band, st['band_levels']):
                amount = .6 * st['band'] * level
                for socket in animated_sockets(seg):
                    socket.default_value = amount
            for obj in self.arrows:
                for socket in animated_sockets(obj):
                    socket.default_value = st['arrows']
            angle = st['jam_angle']
            self.jam_marker.location = (pm.RING_R * math.cos(angle), pm.RING_R * math.sin(angle), 0)
            self.jam_marker.rotation_euler = (0, 0, angle + math.pi / 2)
        else:
            for i, (root, wheels, brake) in enumerate(self.ring_cars):
                root.location = (0, 0, self.PARK)
            for obj in (self.marker_a, self.marker_stop, self.marker_av, *self.band, *self.arrows):
                for socket in animated_sockets(obj):
                    socket.default_value = 0.0
        cam_x = st.get('camera_x', 0.0)
        for lane, cars in self.highway_cars.items():
            if ring:
                for root, brake in cars:
                    root.location = (pm.HWY_ORIGIN[0], pm.HWY_ORIGIN[1], self.PARK)
                continue
            x, v, a, pedal = st['lanes'][lane]
            for i, (root, brake) in enumerate(cars):
                p = self.story.highway_point(lane, x[i], cam_x, st['highway_base'])
                near = -250 < p[0] - pm.HWY_ORIGIN[0] - cam_x < 700
                root.location = p if near else (p[0], p[1], self.PARK)
                root.rotation_euler = (0, 0, 0)
                self.glow(brake, .06 + 5.0 * self.brake_level(v[i], a[i], pedal[i]))
        eye, look, lens = st['camera']
        self.camera.location = eye
        self.camera.rotation_euler = (Vector(look) - Vector(eye)).to_track_quat('-Z', 'Y').to_euler()
        self.camera.data.lens = lens
        self.scene.view_layers[0].update()
        self.state = st
        return self.job['canonical_state_cache'][frame], self.animated

    # ----- editable keys (bulk, as in the coriolis story) ---------------------------------
    def insert_keys(self, frame):
        for obj in self.animated:
            for prop in ('location', 'rotation_euler'):
                obj.keyframe_insert(data_path=prop, frame=frame)
            for socket in animated_sockets(obj):
                socket.keyframe_insert(data_path='default_value', frame=frame)
        self.camera.data.keyframe_insert(data_path='lens', frame=frame)

    def bake(self):
        from array import array
        from bpy_extras import anim_utils
        frames = self.job['duration_frames']
        self.sample(0)
        self.insert_keys(1)
        owners = [*bpy.data.objects, *bpy.data.cameras,
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
            for point in points:
                point.interpolation = 'LINEAR'
            curve.update()
        self.scene.frame_set(1)
        bpy.ops.file.pack_all()

    def extra_state(self):
        st = self.state
        return {'beat': st['beat'], 'place': st['place'], 'tau': st['tau'],
                'on_stage': sum(1 for obj in self.animated if obj.location.z > self.PARK / 2)}


def parents(obj):
    while obj.parent:
        obj = obj.parent
        yield obj


def wheel_centre(obj):
    pts = [obj.matrix_world @ Vector(v) for v in obj.bound_box]
    return Vector([sum(p[i] for p in pts) / 8 for i in range(3)])


def mesh_bounds(data):
    xs = [v.co for v in data.vertices]
    return (Vector([min(p[i] for p in xs) for i in range(3)]), Vector([max(p[i] for p in xs) for i in range(3)]))


def mesh_centre(data):
    lo, hi = mesh_bounds(data)
    return (lo + hi) / 2


def join_meshes(name, parts):
    """Merge meshes (with their materials) after applying the given matrices."""
    bm = bmesh.new()
    materials = []
    for obj, matrix in parts:
        data = obj.data.copy()
        data.transform(matrix)
        base = len(materials)
        materials += list(data.materials)
        for poly in data.polygons:
            poly.material_index += base
        bm.from_mesh(data)
        bpy.data.meshes.remove(data)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for mat in materials:
        mesh.materials.append(mat)
    return mesh
