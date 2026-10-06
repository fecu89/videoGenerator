"""Continuous Blender film for the typhoon beta-drift narration.

All motion comes from typhoon_beta_math (pure functions of the frame). This file
builds the globe, the wind darts, the typhoon and the arrows once, then applies each
frame's surface placements and opacities. The globe is the Earth model in the run's
asset folder. Material, mesh and bulk-keyframe helpers are shared with the Saturn
ring film. No words are drawn.
"""
import math
from pathlib import Path
import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from callout import CalloutLayer, labels_from_job
from saturn_rings import SaturnRingsGallery
import typhoon_beta_math as tm

TRADE = (1.0, .74, .20)
WEST = (.40, .80, 1.0)
CORIOLIS = (.72, .34, 1.0)
AIR = (.55, 1.0, .78)
FORCE = (.95, .50, 1.0)                      # Coriolis force arrows and turning glyphs
GYRE_CW = (1.0, .42, .16)
GYRE_CCW = (.26, .52, 1.0)
PUSH = (.72, 1.0, .25)
WHITE = (1.0, 1.0, 1.0)
SUN_AT = (20.0, 172.0)                       # sub-solar point: the stage stays in daylight
FILL_AT = (5.0, 105.0)


class TyphoonBetaGallery(SaturnRingsGallery):
    # ----- flat shapes on a tangent plane (local +X is the pointing direction) -------------
    def flat(self, name, polygons, material, uvs=None):
        def build(bm):
            layer = bm.loops.layers.uv.new('UVMap')
            for k, polygon in enumerate(polygons):
                face = bm.faces.new([bm.verts.new((x, y, 0.0)) for x, y in polygon])
                for loop, uv in zip(face.loops, uvs[k] if uvs else polygon):
                    loop[layer].uv = uv
        obj = self.mesh_object(name, build, material)
        obj.visible_shadow = False
        return obj

    @staticmethod
    def arc_arrow(radius, start, span, width, head, steps=14):
        """Polygons of an arrow bent along a circle; span < 0 runs clockwise."""
        sign = 1.0 if span > 0 else -1.0
        body = span - sign * head / radius                    # leave room for the head
        polygons = []
        for k in range(steps):
            a0, a1 = start + body * k / steps, start + body * (k + 1) / steps
            polygons.append([((radius + s * width / 2) * math.cos(a), (radius + s * width / 2) * math.sin(a))
                             for a, s in ((a0, -1), (a0, 1), (a1, 1), (a1, -1))][::int(sign)])
        a, tip = start + body, start + span
        polygons.append([((radius - 1.3 * width) * math.cos(a), (radius - 1.3 * width) * math.sin(a)),
                         ((radius + 1.3 * width) * math.cos(a), (radius + 1.3 * width) * math.sin(a)),
                         (radius * math.cos(tip), radius * math.sin(tip))][::int(-sign)])
        return polygons

    def straight_arrow(self, name, color, key, strength=1.0):
        mat = self.emission(name + ' glow', color, strength, key)
        w, h = .024, tm.ARROW_HEAD
        self.objs[name + 'Shaft'] = self.flat(name + 'Shaft', [[(0, -w), (1, -w), (1, w), (0, w)]], mat)
        self.objs[name + 'Head'] = self.flat(name + 'Head', [[(0, -.060), (h, 0), (0, .060)]], mat)

    # ----- world -----------------------------------------------------------------------------
    def build_world(self):
        scene = self.scene
        scene.view_settings.view_transform = 'Standard'
        scene.eevee.taa_render_samples = 16
        world = scene.world
        world.use_nodes = True
        nodes, links = world.node_tree.nodes, world.node_tree.links
        bg = nodes['Background']
        coord = nodes.new('ShaderNodeTexCoord')
        stars = nodes.new('ShaderNodeTexVoronoi')
        stars.feature = 'F1'
        stars.inputs['Scale'].default_value = 240.0
        near = nodes.new('ShaderNodeMath')
        near.operation = 'LESS_THAN'
        near.inputs[1].default_value = .045
        bright = nodes.new('ShaderNodeMath')
        bright.operation = 'MULTIPLY'
        glow = nodes.new('ShaderNodeMath')
        glow.operation = 'MULTIPLY_ADD'
        glow.inputs[1].default_value = 1.4
        glow.inputs[2].default_value = .004
        links.new(coord.outputs['Generated'], stars.inputs['Vector'])
        links.new(stars.outputs['Distance'], near.inputs[0])
        links.new(near.outputs[0], bright.inputs[0])
        links.new(stars.outputs['Color'], bright.inputs[1])
        links.new(bright.outputs[0], glow.inputs[0])
        # The camera sees stars on black; surfaces still receive a little ambient light.
        path = nodes.new('ShaderNodeLightPath')
        seen = nodes.new('ShaderNodeMix')
        seen.data_type = 'FLOAT'
        seen.inputs['A'].default_value = .10
        links.new(path.outputs['Is Camera Ray'], seen.inputs['Factor'])
        links.new(glow.outputs[0], seen.inputs['B'])
        links.new(seen.outputs['Result'], bg.inputs['Strength'])
        bg.inputs['Color'].default_value = (.75, .82, 1.0, 1)
        for obj in list(scene.objects):
            if obj.type == 'LIGHT':
                bpy.data.objects.remove(obj, do_unlink=True)
        for name, at, energy, shadow in (('Sun', SUN_AT, 3.4, True), ('Fill', FILL_AT, 1.1, False)):
            light = bpy.data.lights.new(name, 'SUN')
            light.energy = energy
            light.use_shadow = shadow
            obj = self.link(name, light)
            obj.rotation_euler = (-Vector(tm.normal(*at))).to_track_quat('-Z', 'Y').to_euler()
        cam = self.camera.data
        cam.type = 'PERSP'
        cam.sensor_width = 36
        cam.lens = tm.LENS
        cam.clip_start = .01
        cam.clip_end = 200

    def build_earth(self):
        """The asset globe already has north on +Z and longitude 0 on +X growing toward +Y."""
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(Path(self.job['style']['asset_root']) / 'earth.glb'))
        imported = [o for o in bpy.data.objects if o not in before]
        self.scene.view_layers[0].update()
        meshes = [o for o in imported if o.type == 'MESH']
        pts = [o.matrix_world @ Vector(v) for o in meshes for v in o.bound_box]
        lo = Vector([min(p[i] for p in pts) for i in range(3)])
        hi = Vector([max(p[i] for p in pts) for i in range(3)])
        fit = Matrix.Scale(2.0 / max(hi - lo), 4) @ Matrix.Translation(-(lo + hi) / 2)
        for index, obj in enumerate(sorted(meshes, key=lambda o: -len(o.data.vertices))):
            data = obj.data.copy()
            data.transform(fit @ obj.matrix_world)
            for poly in data.polygons:
                poly.use_smooth = True
            name = 'Earth' if index == 0 else 'EarthLayer%d' % index
            self.objs[name] = self.link(name, data)
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
        for image in bpy.data.images:
            if image.source == 'FILE' and not image.packed_file:
                image.pack()

        axis = self.emission('Axis glow', WHITE, 1.6, 'Axis')
        def rod(bm):
            bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=.011, radius2=.011, depth=2.9,
                                  matrix=Matrix.Translation((0, 0, .05)))
        self.objs['Axis'] = self.mesh_object('Axis', rod, axis)
        self.objs['Axis'].visible_shadow = False
        turning = [p for k in range(3) for p in self.arc_arrow(.40, math.tau * k / 3, math.radians(88), .045, .14)]
        self.objs['Spin'] = self.flat('Spin', turning, self.emission('Spin glow', WHITE, 1.0, 'Spin'))

        shell = bpy.data.materials.new('Coriolis strength')
        shell.use_nodes = True
        nodes, links = shell.node_tree.nodes, shell.node_tree.links
        nodes.clear()
        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value = (*CORIOLIS, 1)
        emit.inputs['Strength'].default_value = 1.0
        clear = nodes.new('ShaderNodeBsdfTransparent')
        geom = nodes.new('ShaderNodeNewGeometry')
        split = nodes.new('ShaderNodeSeparateXYZ')
        north = nodes.new('ShaderNodeMath')            # sin(latitude), northern hemisphere only
        north.operation = 'MAXIMUM'
        north.inputs[1].default_value = 0.0
        amount = nodes.new('ShaderNodeMath')
        amount.name = 'Coriolis opacity'
        amount.operation = 'MULTIPLY'
        amount.inputs[1].default_value = 0.0
        gain = nodes.new('ShaderNodeMath')
        gain.operation = 'MULTIPLY'
        gain.inputs[1].default_value = .78
        mixer = nodes.new('ShaderNodeMixShader')
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(geom.outputs['Position'], split.inputs[0])
        links.new(split.outputs['Z'], north.inputs[0])
        links.new(north.outputs[0], amount.inputs[0])
        links.new(amount.outputs[0], gain.inputs[0])
        links.new(gain.outputs[0], mixer.inputs[0])
        links.new(clear.outputs[0], mixer.inputs[1])
        links.new(emit.outputs[0], mixer.inputs[2])
        links.new(mixer.outputs[0], out.inputs['Surface'])
        shell.surface_render_method = 'BLENDED'
        self.sockets['Coriolis'] = [amount.inputs[1]]
        self.objs['Coriolis'] = self.sphere('Coriolis', 1.007, shell, 96, 48)
        self.objs['Coriolis'].visible_shadow = False

    # ----- winds, storm, track -----------------------------------------------------------------
    def build_winds(self):
        L, w = tm.DART, .052
        shape = [[(L / 2, 0), (-L / 2, w), (-L / 4, 0)], [(L / 2, 0), (-L / 4, 0), (-L / 2, -w)]]
        for band, (count, *_rest) in tm.BANDS.items():
            mat = self.emission(band + ' wind', TRADE if band.startswith('Trade') else WEST, 1.0, band)
            first = None
            for i in range(count):
                name = '%s%02d' % (band, i)
                if first is None:
                    first = self.objs[name] = self.flat(name, shape, mat)
                else:
                    self.objs[name] = self.link(name, first.data)
                    self.objs[name].visible_shadow = False

    def cloud_image(self):
        n = 512
        y, x = np.mgrid[-1:1:n * 1j, -1:1:n * 1j]
        r = np.hypot(x, y)
        theta = np.arctan2(y, x)
        step = lambda a, b, v: np.clip((v - a) / (b - a), 0, 1) ** 2 * (3 - 2 * np.clip((v - a) / (b - a), 0, 1))
        # Bands spiral inward counterclockwise: along one band the angle falls as the radius grows.
        arms = (.5 + .5 * np.cos(2 * theta + 7.5 * np.log(r + .06))) ** 1.6
        ragged = .5 + .5 * np.sin(9 * theta - 21 * r) * np.cos(5 * theta + 13 * r)
        core = np.exp(-(r / .40) ** 2)
        alpha = np.clip(1.15 * core + arms * np.exp(-(r / .78) ** 2) * (.80 + .20 * ragged), 0, 1)
        alpha *= step(.030, .075, r) * (1 - step(.84, .99, r))
        shade = np.clip(.80 + .20 * arms + .12 * core, 0, 1)
        rgba = np.dstack([shade, shade, np.clip(shade + .02, 0, 1), alpha]).astype(np.float32)
        image = bpy.data.images.new('Typhoon cloud', n, n, alpha=True)
        image.pixels.foreach_set(rgba.ravel())
        image.pack()
        return image

    def cloud(self, name, radius, key, image):
        mat = bpy.data.materials.new(name + ' cloud')
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Roughness'].default_value = 1.0
        bsdf.inputs['Emission Strength'].default_value = .55
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = image
        tex.extension = 'CLIP'
        links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        links.new(tex.outputs['Color'], bsdf.inputs['Emission Color'])
        links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
        self.fadeable(mat, key, blended=True)
        corners = [(-radius, -radius), (radius, -radius), (radius, radius), (-radius, radius)]
        self.objs[name] = self.flat(name, [corners], mat, uvs=[[(0, 0), (1, 0), (1, 1), (0, 1)]])

    def ribbon(self, name, width, alt, color, strength, key, window):
        """A strip along the track whose U runs 0..1; `window` names the reveal sockets."""
        track = self.story.track
        mat = bpy.data.materials.new(name + ' line')
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value = (*color, 1)
        emit.inputs['Strength'].default_value = strength
        clear = nodes.new('ShaderNodeBsdfTransparent')
        coord = nodes.new('ShaderNodeTexCoord')
        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coord.outputs['UV'], split.inputs[0])
        amount = nodes.new('ShaderNodeMath')
        amount.name = name + ' opacity'
        amount.operation = 'MULTIPLY'
        amount.inputs[1].default_value = 0.0
        self.sockets[key] = [amount.inputs[1]]
        shown = None
        for socket_key, operation in window:
            test = nodes.new('ShaderNodeMath')
            test.operation = operation
            test.inputs[1].default_value = 0.0
            links.new(split.outputs['X'], test.inputs[0])
            self.sockets[socket_key] = [test.inputs[1]]
            if shown is None:
                shown = test
            else:
                both = nodes.new('ShaderNodeMath')
                both.operation = 'MULTIPLY'
                links.new(shown.outputs[0], both.inputs[0])
                links.new(test.outputs[0], both.inputs[1])
                shown = both
        links.new(shown.outputs[0], amount.inputs[0])
        mixer = nodes.new('ShaderNodeMixShader')
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(amount.outputs[0], mixer.inputs[0])
        links.new(clear.outputs[0], mixer.inputs[1])
        links.new(emit.outputs[0], mixer.inputs[2])
        links.new(mixer.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'DITHERED'

        def build(bm):
            layer = bm.loops.layers.uv.new('UVMap')
            rows = []
            pts = [Vector(tm.normal(*p)) for p in track.pts]
            for i, p in enumerate(pts):
                along = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
                side = along.cross(p).normalized() * width / 2
                rows.append((bm.verts.new((p + side) * (1 + alt)), bm.verts.new((p - side) * (1 + alt))))
            for i in range(len(rows) - 1):
                face = bm.faces.new((rows[i][0], rows[i + 1][0], rows[i + 1][1], rows[i][1]))
                for loop, u in zip(face.loops, (track.s[i], track.s[i + 1], track.s[i + 1], track.s[i])):
                    loop[layer].uv = (u, .5)
        self.objs[name] = self.mesh_object(name, build, mat)
        self.objs[name].visible_shadow = False

    def build_story_objects(self):
        image = self.cloud_image()
        self.cloud('Typhoon', tm.TY_R, 'Typhoon', image)
        self.cloud('Ghost', tm.GHOST_R, 'Ghost', image)
        self.ribbon('TrackDim', .016, .012, (.80, .86, .95), 1.0, 'TrackDim', (('TrackDimReveal', 'LESS_THAN'),))
        self.ribbon('TrackHot', .030, .016, (1.0, .96, .80), 2.6, 'TrackHot', (('HotLo', 'GREATER_THAN'), ('HotHi', 'LESS_THAN')))
        for name, color in (('Wind', TRADE), ('Move', WHITE), ('FlowE', AIR), ('FlowW', AIR), ('Push', PUSH), ('Steer', TRADE)):
            self.straight_arrow(name, color, name)
        for side in ('CorE', 'CorW'):
            for k in range(tm.CORIOLIS_ROW):
                self.straight_arrow('%s%d' % (side, k), FORCE, side)
        turn = self.emission('Turn glow', FORCE, 1.0, 'Turn')
        for i in range(len(tm.TURN_LATS)):
            # moving air is turned to the right in the northern hemisphere: a clockwise bend
            self.objs['Turn%d' % i] = self.flat('Turn%d' % i, self.arc_arrow(.105, math.radians(200), -math.radians(240), .038, .09), turn)
        for name, color, sense in (('GyreNE', GYRE_CW, -1.0), ('GyreSW', GYRE_CCW, 1.0)):
            mat = self.emission(name + ' glow', color, 1.0, 'Gyre')
            polygons = [p for k in range(4) for p in self.arc_arrow(tm.GYRE_R, math.tau * k / 4, sense * math.radians(66), .030, .066)]
            self.objs[name] = self.flat(name, polygons, mat)

    # ----- build -------------------------------------------------------------------------------
    def build(self):
        self.fps = self.job['canonical_fps']
        self.story = tm.Story(self.job['timeline'], self.fps)
        self.scene.name = 'Typhoon Beta ' + self.job['sequence_id']
        self.camera.name = 'TyphoonBetaCamera'
        self.objs, self.sockets = {}, {}
        self.build_world()
        self.build_earth()
        self.build_winds()
        self.build_story_objects()
        self.animated = [*self.objs.values(), self.camera]
        self.callouts = CalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job), dict(self.objs))

    # ----- per frame ---------------------------------------------------------------------------
    @staticmethod
    def on_surface(lat, lon, alt, psi):
        la, lo = math.radians(lat), math.radians(lon)
        up = Vector((math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)))
        east = Vector((-math.sin(lo), math.cos(lo), 0.0))
        north = up.cross(east)
        frame = Matrix((east, north, up)).transposed() @ Matrix.Rotation(math.radians(psi), 3, 'Z')
        return up * (1 + alt), frame.to_euler()

    def sample(self, frame):
        st = self.story.state(frame)
        for name, entry in st['xf'].items():
            obj = self.objs[name]
            if entry[0] == 'S':
                _, lat, lon, alt, psi, scale = entry
                obj.location, obj.rotation_euler = self.on_surface(lat, lon, alt, psi)
            else:
                _, obj.location, obj.rotation_euler, scale = entry
            obj.scale = scale
        for key, value in st['op'].items():
            for socket in self.sockets[key]:
                socket.default_value = value
        eye, look, lens = st['camera']
        self.camera.location = eye
        self.camera.rotation_euler = (Vector(look) - Vector(eye)).to_track_quat('-Z', 'Y').to_euler()
        self.camera.data.lens = lens
        self.scene.view_layers[0].update()
        self.state = st
        return self.job['canonical_state_cache'][frame], self.animated

    def extra_state(self):
        st = self.state
        return {'shot': st['shot'], 'typhoon': st['typhoon'], 'opacity': {k: round(v, 5) for k, v in st['op'].items()}}
