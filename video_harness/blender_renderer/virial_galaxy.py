"""Elliptical galaxy, gravity well, energy bars, Doppler spectrum and a balance.

One native scene for the virial-mass story. No on-screen text except declared
formula callouts. Stars ride randomly oriented orbits; the gravity well depth
stands for enclosed mass; the absorption lines are shifted by each star's
line-of-sight velocity so their sum is the broadened galaxy line. All motion
is a function of the canonical frame (orbit clocks are integrated once).
"""
import math
import random
from array import array
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector
try:
    from .scene import SpectralGallery
    from .callout import CalloutLayer, labels_from_job
    from .callout_math import REFERENCE_WIDTH, SAFE_MARGIN
    from .virial_galaxy_math import (
        golden, kinetic_potential, line_profile, smooth, smoother, spin_quaternion, state_at,
        well_depth_units, well_profile)
except ImportError:
    from scene import SpectralGallery
    from callout import CalloutLayer, labels_from_job
    from callout_math import REFERENCE_WIDTH, SAFE_MARGIN
    from virial_galaxy_math import (
        golden, kinetic_potential, line_profile, smooth, smoother, spin_quaternion, state_at,
        well_depth_units, well_profile)

G_SCALE = Vector((1.0, 0.85, 0.75))
G_R = 10.3
SPIRAL_C = Vector((-31.0, 9.0, 1.0))
SCALE_C = Vector((0.0, -24.0, -12.0))    # balance base
BEAM_HALF = 4.2
PAN_DROP = 3.0
WELL_RIM = 16.0
BARS = Vector((21.5, 0.0, 0.0))
SPEC_C = Vector((27.0, -2.0, -7.5))   # right of the frame; the galaxy sits left
SPEC_W, SPEC_H = 13.0, 2.6
PRISM_C = Vector((12.6, -3.0, -11.5))  # centre-bottom, between the galaxy and the spectrum
SCALE_DROP = 16.0         # the balance slides below the frame instead of popping out
RAINBOW = [(0.45, 0.05, 0.9), (0.15, 0.2, 1.0), (0.0, 0.75, 1.0), (0.1, 0.95, 0.2), (1.0, 0.9, 0.05), (1.0, 0.45, 0.0), (0.9, 0.05, 0.05)]
ASSETS = Path(__file__).resolve().parents[2] / 'assets'
FAR_DIR = Vector((0.22, -1.0, 0.16)).normalized()
JWST_C = FAR_DIR * 700 + Vector((-6.0, 4.0, -3.5))
LINE_HALF_SPAN = 2.5      # the line plane spans +-2.5 Gaussian sigmas
HALO_R = 27.0
DOPPLER_R = 6.5
ON_SCALE = 0.13           # galaxy size while it sits on the balance pan
STAR_WARM = (1.0, 0.82, 0.58)
CYAN = (0.25, 0.72, 1.0)
GOLD = (1.0, 0.72, 0.28)
BLUE = (0.3, 0.5, 1.0)
RED = (1.0, 0.28, 0.18)


def lerp(a, b, p):
    return a + (b - a) * p


class CentredCalloutLayer(CalloutLayer):
    """A formula sits centred in the free space beside its anchor, without a drawn leader line."""

    def _glyph_box(self, item):
        """Rendered glyph bounds in text-local units (the estimate in callout_math is per character)."""
        if 'glyphs' not in item:
            text = item['text']
            text.data.align_x, text.data.align_y = 'LEFT', 'BOTTOM_BASELINE'
            saved = tuple(text.scale)
            text.scale = (1, 1, 1)
            self.g.scene.view_layers[0].update()
            box = [Vector(c) for c in text.evaluated_get(bpy.context.evaluated_depsgraph_get()).bound_box]
            text.scale = saved
            item['glyphs'] = (min(v.x for v in box), max(v.x for v in box), min(v.y for v in box), max(v.y for v in box))
        return item['glyphs']

    def _place(self, item, rect, leader, scale, amount):
        side = item['label'].get('side', 'right')
        x_min, x_max, y_min, y_max = self._glyph_box(item)
        out = self.g.job['output']
        if side in ('left', 'right'):
            sx, sy = leader[0]
            w = (x_max - x_min) / REFERENCE_WIDTH
            h = (y_max - y_min) / (REFERENCE_WIDTH * out['height'] / out['width'])
            if side == 'right':
                lo, hi = sx + 0.03, 1 - SAFE_MARGIN
                x0 = max(lo, (lo + hi - w) / 2)
            else:
                lo, hi = SAFE_MARGIN, sx - 0.03
                x0 = min(hi - w, (lo + hi - w) / 2)
            y0 = min(max(sy - h / 2, SAFE_MARGIN), 1 - SAFE_MARGIN - h)
            rect = [x0, y0, x0 + w, y0 + h]
            edge = x0 if side == 'right' else x0 + w
            mid = (y0 + y0 + h) / 2
            leader = [leader[0], (edge, mid), (edge, mid)] if abs(mid - sy) < 1e-9 else [leader[0], (sx, mid), (edge, mid)]
        item['placed'] = (rect, leader)
        super()._place(item, rect, leader, scale, amount)
        # Put the glyphs' own box (not the font's line box) exactly on the rect, so the leader meets their middle.
        corner = self._hud((rect[0], (rect[1] + rect[3]) / 2), scale)
        item['text'].location = corner - Vector((x_min * scale, (y_min + y_max) / 2 * scale, 0))
        # The formula stands on its own beside its object; no leader line is drawn.
        item['leader'].hide_render = item['leader'].hide_viewport = True

    def update(self, frame, amounts=None):
        super().update(frame, amounts)
        for item in self.items:
            if item.get('placed') and item['state'] is not None:
                rect, leader = item['placed']
                item['state']['rect'] = [float(v) for v in rect]
                item['state']['leader'] = [[float(x), float(y)] for x, y in leader]


class VirialGalaxyStoryGallery(SpectralGallery):
    def build(self):
        self.scene.name = 'Virial theorem — weighing a galaxy'
        for name in ('Softbox',):
            if name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
        self.scene.view_settings.view_transform = 'AgX'
        self.scene.view_settings.look = 'None'
        self.scene.eevee.taa_render_samples = 16
        world = self.scene.world
        world.use_nodes = True
        bg = world.node_tree.nodes['Background']
        bg.inputs['Color'].default_value = (0.003, 0.005, 0.012, 1)
        bg.inputs['Strength'].default_value = 1.0
        self.build_composite()
        self.camera.data.type = 'PERSP'
        self.camera.data.clip_start = 0.1
        self.camera.data.clip_end = 9000
        self.camera.data.lens = 45
        sun = bpy.data.lights.new('Key light', 'SUN')
        sun.energy = 3.2
        sun.angle = 0.2
        key = self.link('Key light', sun)
        key.rotation_euler = (math.radians(55), 0, math.radians(-35))
        fill = bpy.data.lights.new('Fill light', 'SUN')
        fill.energy = 0.8
        rim = self.link('Fill light', fill)
        rim.rotation_euler = (math.radians(-60), 0, math.radians(150))
        self.fade_sockets = {}
        count = self.job['duration_frames']
        self.states = [state_at(self.job, f) for f in range(count)]
        fps = self.job['canonical_fps']
        self.orbit_clock = [0.0]
        self.held_clock = [0.0]
        for f in range(1, count):
            prev = self.states[f - 1]
            self.orbit_clock.append(self.orbit_clock[-1] + prev['sigma'] / fps)
            omega = 1.15 * math.sqrt(well_depth_units(prev['well_depth']) / well_depth_units(0.0))
            self.held_clock.append(self.held_clock[-1] + omega / fps)
        self.doppler_t0 = next((b['start_frame'] / fps for b in self.job['timeline']
                                if b['controller_options'].get('state', {}).get('doppler', 0) > 0), 0.0)
        self.movers = [self.camera]
        self.build_sky()
        self.build_far_galaxies()
        self.build_elliptical()
        self.build_tracers()
        self.build_spiral()
        self.build_scale()
        self.build_well()
        self.build_bars()
        self.build_doppler()
        self.build_spectrum()
        self.build_telescope()
        self.build_prism()
        self.build_halo()
        self.state = {}
        # AppleGothic leaves a wide gap before the superscript in σ²; the formula labels use Arial Unicode.
        self.font = bpy.data.fonts.load('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
        self.callouts = CentredCalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job), {o.name: o for o in self.scene.objects})

    # ---------- materials ----------
    def build_composite(self):
        tree = bpy.data.node_groups.new('Galaxy glow composite', 'CompositorNodeTree')
        self.scene.compositing_node_group = tree
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        layers = tree.nodes.new('CompositorNodeRLayers')
        layers.scene = self.scene
        glare = tree.nodes.new('CompositorNodeGlare')
        glare.inputs['Type'].default_value = 'Fog Glow'
        glare.inputs['Quality'].default_value = 'Medium'
        if glare.inputs.get('Threshold'):
            glare.inputs['Threshold'].default_value = 0.9
        out = tree.nodes.new('NodeGroupOutput')
        tree.links.new(layers.outputs['Image'], glare.inputs[0])
        tree.links.new(glare.outputs[0], out.inputs[0])

    def additive(self, name, color, strength, profile_power=None, rim=False):
        """Order-independent glow: transparent + emission; returns the amount socket."""
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*color, 1)
        amount = nodes.new('ShaderNodeMath')
        amount.operation = 'MULTIPLY'
        amount.inputs[0].default_value = strength
        amount.inputs[1].default_value = 1.0
        if profile_power is not None:
            # |N.V| is 1 at the centre of a sphere and 0 at its silhouette: a soft glow profile.
            geo = nodes.new('ShaderNodeNewGeometry')
            dot = nodes.new('ShaderNodeVectorMath')
            dot.operation = 'DOT_PRODUCT'
            links.new(geo.outputs['Normal'], dot.inputs[0])
            links.new(geo.outputs['Incoming'], dot.inputs[1])
            facing = nodes.new('ShaderNodeMath')
            facing.operation = 'ABSOLUTE'
            links.new(dot.outputs['Value'], facing.inputs[0])
            src = facing.outputs[0]
            if rim:
                inv = nodes.new('ShaderNodeMath')
                inv.operation = 'SUBTRACT'
                inv.inputs[0].default_value = 1.0
                links.new(src, inv.inputs[1])
                src = inv.outputs[0]
            pw = nodes.new('ShaderNodeMath')
            pw.operation = 'POWER'
            links.new(src, pw.inputs[0])
            pw.inputs[1].default_value = profile_power
            mul = nodes.new('ShaderNodeMath')
            mul.operation = 'MULTIPLY'
            links.new(pw.outputs[0], mul.inputs[0])
            links.new(amount.outputs[0], mul.inputs[1])
            links.new(mul.outputs[0], em.inputs['Strength'])
        else:
            links.new(amount.outputs[0], em.inputs['Strength'])
        tr = nodes.new('ShaderNodeBsdfTransparent')
        add = nodes.new('ShaderNodeAddShader')
        links.new(tr.outputs[0], add.inputs[0])
        links.new(em.outputs[0], add.inputs[1])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(add.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'BLENDED'
        mat.use_backface_culling = True
        self.fade_sockets[name] = amount.inputs[1]
        return mat, amount.inputs[1]

    def shade(self, name, color, alpha):
        """Multiplicative darkening (order independent): mix towards a dark colour."""
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*color, 1)
        em.inputs['Strength'].default_value = 1.0
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = alpha
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(em.outputs[0], mix.inputs[2])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(mix.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'BLENDED'
        return mat, mix.inputs[0]

    def metal(self, name, color, rough=0.32):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*color, 1)
        bsdf.inputs['Metallic'].default_value = 1.0
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Emission Color'].default_value = (*color, 1)
        bsdf.inputs['Emission Strength'].default_value = 0.08
        out = nodes.get('Material Output')
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = 1.0
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(bsdf.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'DITHERED'
        return mat, mix.inputs[0]

    # ---------- geometry helpers ----------
    def mesh_obj(self, name, build, mat=None, smooth_faces=True):
        bm = bmesh.new()
        build(bm)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        if smooth_faces:
            for p in me.polygons:
                p.use_smooth = True
        obj = self.link(name, me)
        if mat is not None:
            me.materials.append(mat)
        return obj

    def sphere(self, name, radius, mat, segments=40):
        return self.mesh_obj(name, lambda bm: bmesh.ops.create_uvsphere(
            bm, u_segments=segments, v_segments=segments // 2, radius=radius), mat)

    def cylinder(self, name, radius, depth, mat, segments=32):
        return self.mesh_obj(name, lambda bm: bmesh.ops.create_cone(
            bm, cap_ends=True, cap_tris=False, segments=segments, radius1=radius, radius2=radius, depth=depth), mat)

    def box(self, name, size, mat):
        obj = self.mesh_obj(name, lambda bm: bmesh.ops.create_cube(bm, size=1.0), mat, smooth_faces=False)
        obj.scale = size
        return obj

    def torus(self, name, major, minor, mat, seg=128, tube=12):
        def build(bm):
            verts = []
            for i in range(seg):
                a = math.tau * i / seg
                ring = []
                for j in range(tube):
                    b = math.tau * j / tube
                    r = major + minor * math.cos(b)
                    ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), minor * math.sin(b))))
                verts.append(ring)
            for i in range(seg):
                for j in range(tube):
                    a, b = verts[i], verts[(i + 1) % seg]
                    bm.faces.new((a[j], b[j], b[(j + 1) % tube], a[(j + 1) % tube]))
        return self.mesh_obj(name, build, mat)

    def poly_curve(self, name, count, mat, bevel):
        data = bpy.data.curves.new(name, 'CURVE')
        data.dimensions = '3D'
        data.bevel_depth = bevel
        data.bevel_resolution = 3
        data.use_fill_caps = True
        spline = data.splines.new('POLY')
        spline.points.add(count - 1)
        obj = self.link(name, data)
        data.materials.append(mat)
        return obj

    def set_curve(self, obj, points):
        for p, v in zip(obj.data.splines[0].points, points):
            p.co = (v[0], v[1], v[2], 1.0)

    def point_cloud(self, name, points, radius, mat, jitter=(0.55, 1.5)):
        me = bpy.data.meshes.new(name)
        me.from_pydata(points, [], [])
        obj = self.link(name, me)
        tree = bpy.data.node_groups.new(name + ' instances', 'GeometryNodeTree')
        tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        nodes, links = tree.nodes, tree.links
        gi, go = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
        ico = nodes.new('GeometryNodeMeshIcoSphere')
        ico.inputs['Radius'].default_value = radius
        ico.inputs['Subdivisions'].default_value = 1
        rnd = nodes.new('FunctionNodeRandomValue')
        rnd.data_type = 'FLOAT'
        rnd.inputs['Min'].default_value = jitter[0]
        rnd.inputs['Max'].default_value = jitter[1]
        inst = nodes.new('GeometryNodeInstanceOnPoints')
        setm = nodes.new('GeometryNodeSetMaterial')
        setm.inputs['Material'].default_value = mat
        links.new(gi.outputs[0], inst.inputs['Points'])
        links.new(ico.outputs['Mesh'], inst.inputs['Instance'])
        links.new(rnd.outputs['Value'], inst.inputs['Scale'])
        links.new(inst.outputs['Instances'], setm.inputs['Geometry'])
        links.new(setm.outputs[0], go.inputs[0])
        obj.modifiers.new('stars', 'NODES').node_group = tree
        return obj

    def empty(self, name, location=(0, 0, 0)):
        obj = self.link(name, None)
        obj.location = location
        return obj

    def import_glb(self, filename, name, size, location, rotation=(0, 0, 0), keep=None):
        """Import a project asset, bake its transforms and fit its largest extent to size."""
        before = set(self.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(ASSETS / filename))
        imported = [o for o in self.scene.objects if o not in before]
        self.scene.view_layers[0].update()
        meshes = [o for o in imported if o.type == 'MESH']
        for o in meshes:
            world = o.matrix_world.copy()
            o.parent = None
            if o.data.users > 1:
                o.data = o.data.copy()
            o.data.transform(world)
            o.matrix_world = Matrix.Identity(4)
        dropped = [o for o in meshes if keep is not None and not keep(o.name)]
        meshes = [o for o in meshes if o not in dropped]
        for o in imported:
            if o not in meshes:
                bpy.data.objects.remove(o, do_unlink=True)
        pts = [v.co for o in meshes for v in o.data.vertices]
        lo = Vector([min(p[i] for p in pts) for i in range(3)])
        hi = Vector([max(p[i] for p in pts) for i in range(3)])
        scale = size / max(hi - lo)
        fit = Matrix.Scale(scale, 4) @ Matrix.Translation(-(lo + hi) / 2)
        root = self.empty(name, location)
        root.rotation_euler = rotation
        for i, o in enumerate(meshes):
            o.data.transform(fit)
            o.parent = root
            o.name = f'{name}-part-{i:02d}'
            for mat in o.data.materials:
                if mat and mat.node_tree:
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image:
                            node.image.pack()
        return root, meshes

    def fade_asset(self, meshes):
        """One opacity socket per material, inserted in front of the output."""
        sockets = []
        for mat in {m for o in meshes for m in o.data.materials if m and m.use_nodes}:
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            out = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) or \
                next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
            if out is None or not out.inputs['Surface'].links:
                continue
            old = out.inputs['Surface'].links[0].from_socket
            tr = nodes.new('ShaderNodeBsdfTransparent')
            mix = nodes.new('ShaderNodeMixShader')
            mix.inputs[0].default_value = 1.0
            links.new(tr.outputs[0], mix.inputs[1])
            links.new(old, mix.inputs[2])
            links.new(mix.outputs[0], out.inputs['Surface'])
            mat.surface_render_method = 'DITHERED'
            sockets.append(mix.inputs[0])
        return sockets

    # ---------- builders ----------
    def build_sky(self):
        """Nebula-and-stars dome from assets, unlit and dimmed, centred on the camera."""
        self.sky, meshes = self.import_glb('sky_dome._nebula_and_stars_space_hdri..glb', 'SkyDome', 7000.0, (0, 0, 0))
        # The asset holds three layered domes side by side; centre each on the camera, nested.
        for k, o in enumerate(meshes):
            vs = o.data.vertices
            centre = sum((v.co for v in vs), Vector()) / len(vs)
            extent = max((v.co - centre).length for v in vs)
            o.data.transform(Matrix.Scale((3600.0 - 150.0 * k) / extent, 4) @ Matrix.Translation(-centre))
            o.visible_shadow = False
            for mat in o.data.materials:
                if not (mat and mat.node_tree):
                    continue
                nodes, links = mat.node_tree.nodes, mat.node_tree.links
                tex = next((n for n in nodes if n.type == 'TEX_IMAGE'), None)
                out = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
                if tex is None or out is None:
                    continue
                em = nodes.new('ShaderNodeEmission')
                em.inputs['Strength'].default_value = 0.17
                links.new(tex.outputs['Color'], em.inputs['Color'])
                tr = nodes.new('ShaderNodeBsdfTransparent')
                mix = nodes.new('ShaderNodeMixShader')
                links.new(tex.outputs['Alpha'], mix.inputs[0])
                links.new(tr.outputs[0], mix.inputs[1])
                links.new(em.outputs[0], mix.inputs[2])
                links.new(mix.outputs[0], out.inputs['Surface'])
                mat.use_backface_culling = False
                # Dithered keeps depth order: every glow in front of the sky is drawn over it.
                mat.surface_render_method = 'DITHERED'

    def build_starfield_unused(self):
        rng = random.Random(3)
        pts = []
        for _ in range(1500):
            v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
            pts.append(tuple(v * rng.uniform(3000, 3600)))
        mat, self.starfield_amount = self.additive('Background stars', (0.85, 0.9, 1.0), 1.6)
        self.point_cloud('StarField', pts, 2.4, mat, jitter=(0.4, 1.6))

    def build_far_galaxies(self):
        rng = random.Random(11)
        self.far = []
        palette = [(1.0, 0.8, 0.55), (0.75, 0.82, 1.0), (1.0, 0.9, 0.75)]
        for i in range(70):
            v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 0.6))).normalized()
            d = rng.uniform(260, 1500)
            mat, _ = self.additive(f'Far galaxy {i:02d}', palette[i % 3], rng.uniform(0.35, 0.7), profile_power=2.2)
            obj = self.sphere(f'FarGalaxy-{i:02d}', 1.0, mat, segments=24)
            obj.location = v * d
            s = rng.uniform(3.0, 8.0)
            obj.scale = (s, s * rng.uniform(0.35, 0.9), s * rng.uniform(0.35, 0.8))
            obj.rotation_euler = (rng.uniform(0, math.pi), rng.uniform(0, math.pi), rng.uniform(0, math.pi))

    def build_elliptical(self):
        rng = random.Random(7)
        self.galaxy = self.empty('EllipticalGalaxy')
        self.galaxy.scale = G_SCALE
        self.star_swarm = self.empty('StarSwarm')
        self.star_swarm.parent = self.galaxy
        self.shells = []
        colours = [(1.0, 0.84, 0.62), (1.0, 0.7, 0.45), (1.0, 0.93, 0.82)]
        mats = [self.additive(f'Galaxy stars {k}', c, 2.4)[0] for k, c in enumerate(colours)]
        self.star_amounts = [self.fade_sockets[f'Galaxy stars {k}'] for k in range(3)]
        for i in range(16):
            axis = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
            pts = []
            for _ in range(150):
                r = G_R * (rng.random() ** 1.9) * 0.97 + 0.25
                a = rng.random() * math.tau
                pts.append((r * math.cos(a), r * math.sin(a), rng.gauss(0, 0.3 + 0.06 * r)))
            shell = self.point_cloud(f'StarShell-{i:02d}', pts, 0.05, mats[i % 3])
            shell.parent = self.star_swarm
            shell.rotation_mode = 'QUATERNION'
            base = axis.to_track_quat('Z', 'Y')
            omega = rng.uniform(0.09, 0.2) * rng.choice((-1, 1))
            self.shells.append((shell, base, omega))
        glow, self.glow_amount = self.additive('Galaxy glow', (1.0, 0.58, 0.26), 0.16, profile_power=2.5)
        self.glow = self.sphere('GalaxyGlow', G_R, glow, segments=64)
        self.glow.parent = self.galaxy
        mid, self.mid_amount = self.additive('Galaxy glow inner', (1.0, 0.64, 0.32), 0.35, profile_power=3.0)
        self.glow_mid = self.sphere('GalaxyGlowInner', G_R * 0.5, mid, segments=48)
        self.glow_mid.parent = self.galaxy
        core, self.core_amount = self.additive('Galaxy core', (1.0, 0.78, 0.5), 2.2, profile_power=2.0)
        self.core = self.sphere('GalaxyCore', 1.0, core, segments=48)
        self.movers += [self.galaxy, self.star_swarm, self.core, *(s for s, _, _ in self.shells)]

    def build_tracers(self):
        rng = random.Random(23)
        self.tracers = []
        trail_mat, self.trail_amount = self.additive('Tracer trails', (1.0, 0.78, 0.45), 1.4)
        star_mat, self.tracer_amount = self.additive('Tracer stars', (1.0, 0.9, 0.7), 8.0, profile_power=0.6)
        for i in range(7):
            axis = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
            a = rng.uniform(4.8, 9.2)
            orbit = dict(q=axis.to_track_quat('Z', 'Y'), a=a, b=a * rng.uniform(0.45, 0.8),
                         omega=rng.uniform(0.28, 0.45) * rng.choice((-1, 1)), phase=rng.uniform(0, math.tau))
            star = self.sphere(f'TracerStar-{i}', 0.2, star_mat, segments=20)
            star.parent = self.galaxy
            trail = self.poly_curve(f'TracerTrail-{i}', 40, trail_mat, 0.045)
            trail.parent = self.galaxy
            self.tracers.append((orbit, star, trail))
            self.movers.append(star)
        fling_mat, self.fling_amount = self.additive('Fling star', (0.85, 0.92, 1.0), 16.0, profile_power=0.6)
        self.fling_star = self.sphere('FlingStar', 0.26, fling_mat, segments=20)
        self.fling_star.parent = self.galaxy
        ftrail, self.fling_trail_amount = self.additive('Fling trail', (0.7, 0.85, 1.0), 3.0)
        self.fling_trail = self.poly_curve('FlingTrail', 48, ftrail, 0.06)
        self.fling_trail.parent = self.galaxy
        self.movers.append(self.fling_star)

    def orbit_pos(self, orbit, clock):
        ph = orbit['phase'] + orbit['omega'] * clock
        return orbit['q'] @ Vector((orbit['a'] * math.cos(ph), orbit['b'] * math.sin(ph), 0.0))

    def fling_pos(self, p):
        d = Vector((0.78, -0.42, 0.46)).normalized()
        e = d.cross(Vector((0, 0, 1))).normalized()
        return d * (13.2 * math.sin(math.pi * p)) + e * (1.6 * (1 - math.cos(math.pi * p)))

    def build_spiral(self):
        rng = random.Random(5)
        self.spiral = self.empty('SpiralGalaxy', SPIRAL_C)
        self.spiral.rotation_euler = (math.radians(62), math.radians(-8), math.radians(18))
        self.spiral_disk = self.empty('SpiralDisk')
        self.spiral_disk.parent = self.spiral
        arms, bulge = [], []
        for i in range(1700):
            k = i % 2
            t = rng.random() ** 0.8
            th = 0.4 + k * math.pi + 4.4 * t
            r = 1.0 + 8.2 * t
            j = rng.gauss(0, 0.35 + 0.55 * t)
            arms.append((r * math.cos(th) + j * math.cos(th + 1.3), r * math.sin(th) + j * math.sin(th + 1.3),
                         rng.gauss(0, 0.12)))
        for _ in range(420):
            r = 2.2 * rng.random() ** 1.6
            a = rng.random() * math.tau
            bulge.append((r * math.cos(a), r * math.sin(a), rng.gauss(0, 0.35 * (1 - r / 2.4))))
        disk_root, disk_meshes = self.import_glb('galaxy.glb', 'SpiralDiskAsset', 17.0, (0, 0, 0))
        disk_pts = [tuple(v.co) for o in disk_meshes for i, v in enumerate(o.data.vertices) if i % 4 == 0]
        for o in disk_meshes:
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.objects.remove(disk_root, do_unlink=True)
        arm_mat, self.arm_amount = self.additive('Spiral arms', (0.6, 0.75, 1.0), 3.0)
        bulge_mat, self.bulge_amount = self.additive('Spiral bulge', (1.0, 0.78, 0.45), 3.0)
        for obj in (self.point_cloud('SpiralArms', arms, 0.085, arm_mat),
                    self.point_cloud('SpiralBulge', bulge, 0.09, bulge_mat),
                    self.point_cloud('SpiralDiskStars', disk_pts, 0.05, arm_mat, jitter=(0.4, 1.2))):
            obj.parent = self.spiral_disk
        disk_mat, self.disk_amount = self.additive('Spiral disk glow', (0.6, 0.72, 1.0), 0.05, profile_power=4.0)
        disk = self.sphere('SpiralGlow', 1.0, disk_mat, segments=48)
        disk.parent = self.spiral_disk
        disk.scale = (6.0, 6.0, 1.2)
        self.movers += [self.spiral_disk]

    def build_scale(self):
        brass, self.brass_alpha = self.metal('Brass', (0.86, 0.6, 0.28))
        c = SCALE_C
        self.scale_parts = []
        base = self.cylinder('ScaleBase', 2.2, 0.35, brass)
        base.location = c + Vector((0, 0, 0.175))
        pillar = self.cylinder('ScalePillar', 0.2, 6.4, brass)
        pillar.location = c + Vector((0, 0, 3.55))
        self.scale_top = c + Vector((0, 0, 6.9))
        pivot = self.sphere('ScalePivot', 0.36, brass, segments=24)
        pivot.location = self.scale_top
        self.beam = self.box('ScaleBeam', (BEAM_HALF * 2, 0.16, 0.16), brass)
        self.beam.location = self.scale_top
        self.pans, self.cords = [], []
        for side in (-1, 1):
            pan = self.cylinder('PanLeft' if side < 0 else 'PanRight', 1.5, 0.12, brass, segments=40)
            self.pans.append(pan)
            for k in range(3):
                cord = self.cylinder(f'Cord{"L" if side < 0 else "R"}{k}', 0.03, 1.0, brass, segments=8)
                self.cords.append((side, k, cord))
        self.scale_parts = [base, pillar, pivot, self.beam, *self.pans, *(c for _, _, c in self.cords)]
        self.scale_fixed = [(o, o.location.copy()) for o in (base, pillar, pivot)]
        light_mat, self.light_ball_amount = self.additive('Light mass', (1.0, 0.6, 0.12), 1.0, profile_power=0.8)
        self.light_ball = self.sphere('LightMassBall', 0.9, light_mat)
        dyn_mat, self.dyn_core_amount = self.additive('Dynamical core', (1.0, 0.6, 0.12), 1.0, profile_power=0.8)
        self.dyn_core = self.sphere('DynamicalCore', 0.9, dyn_mat)
        shell_mat, self.shell_amount = self.additive('Dark shell rim', (0.5, 0.3, 1.0), 2.0, profile_power=3.0, rim=True)
        self.dark_shell = self.sphere('DarkShell', 1.55, shell_mat, segments=48)
        fill_mat, self.shell_fill = self.shade('Dark shell fill', (0.03, 0.01, 0.06), 0.0)
        self.dark_fill = self.sphere('DarkShellFill', 1.5, fill_mat, segments=48)
        flow_mat, self.flow_amount = self.additive('Light flow', GOLD, 4.0, profile_power=0.6)
        self.flow = [self.sphere(f'LightFlow-{i:02d}', 0.22, flow_mat, segments=12) for i in range(16)]
        self.movers += [self.beam, *self.pans, self.light_ball, self.dyn_core, self.dark_shell, self.dark_fill]

    def build_well(self):
        nr, ns = 18, 44
        self.well_rings = [0.0] + [WELL_RIM * (k / nr) ** 1.3 for k in range(1, nr + 1)]
        self.well_ns = ns

        def build(bm):
            centre = bm.verts.new((0, 0, -1))
            rings = []
            for r in self.well_rings[1:]:
                rings.append([bm.verts.new((r * math.cos(math.tau * j / ns), r * math.sin(math.tau * j / ns), 0))
                              for j in range(ns)])
            for j in range(ns):
                bm.faces.new((centre, rings[0][j], rings[0][(j + 1) % ns]))
            for a, b in zip(rings, rings[1:]):
                for j in range(ns):
                    bm.faces.new((a[j], b[j], b[(j + 1) % ns], a[(j + 1) % ns]))
        grid_mat, self.grid_amount = self.additive('Well grid', CYAN, 3.2)
        self.well_grid = self.mesh_obj('GravityWellGrid', build, grid_mat, smooth_faces=False)
        wire = self.well_grid.modifiers.new('wire', 'WIREFRAME')
        wire.thickness = 0.06
        wire.use_even_offset = True
        wire.use_replace = True
        surf_mat, self.surface_amount = self.additive('Well surface', (0.1, 0.3, 0.8), 0.35, profile_power=0.8)
        self.well_surface = self.mesh_obj('GravityWellSurface', build, surf_mat)
        self.well_radii = [math.hypot(v.co.x, v.co.y) for v in self.well_grid.data.vertices]
        ball = lambda name, colour: self.additive(name, colour, 12.0, profile_power=0.5)
        slow_mat, self.slow_amount = ball('Slow star', (1.0, 0.8, 0.5))
        fast_mat, self.fast_amount = ball('Fast star', (0.75, 0.88, 1.0))
        held_mat, self.held_amount = ball('Held star', (0.75, 0.88, 1.0))
        self.slow_ball = self.sphere('SlowStar', 0.55, slow_mat, segments=24)
        self.fast_ball = self.sphere('FastStar', 0.55, fast_mat, segments=24)
        self.held_ball = self.sphere('HeldStar', 0.55, held_mat, segments=24)
        trail = lambda name, colour: self.additive(name, colour, 2.6)
        st_mat, self.slow_trail_amount = trail('Slow trail', (1.0, 0.78, 0.45))
        ft_mat, self.fast_trail_amount = trail('Fast trail', (0.6, 0.8, 1.0))
        ht_mat, self.held_trail_amount = trail('Held trail', (0.6, 0.8, 1.0))
        self.slow_trail = self.poly_curve('SlowTrail', 30, st_mat, 0.08)
        self.fast_trail = self.poly_curve('FastTrail', 30, ft_mat, 0.08)
        self.held_trail = self.poly_curve('HeldTrail', 30, ht_mat, 0.08)
        self.movers += [self.slow_ball, self.fast_ball, self.held_ball]

    def build_bars(self):
        k_mat, self.k_amount = self.additive('Kinetic energy', (1.0, 0.35, 0.03), 0.7)
        k2_mat, self.k2_amount = self.additive('Kinetic energy copy', (1.0, 0.35, 0.03), 0.7)
        u_mat, self.u_amount = self.additive('Potential energy', (0.05, 0.3, 1.0), 0.8)
        z_mat, self.zero_amount = self.additive('Zero plate', (0.9, 0.95, 1.0), 1.0)
        self.k_bar = self.cylinder('KineticBar', 0.7, 1.0, k_mat)
        self.k2_bar = self.cylinder('KineticBarCopy', 0.7, 1.0, k2_mat)
        self.u_bar = self.cylinder('PotentialBar', 0.7, 1.0, u_mat)
        self.zero = self.box('ZeroPlate', (4.6, 1.8, 0.06), z_mat)
        self.movers += [self.k_bar, self.k2_bar, self.u_bar, self.zero]

    def build_doppler(self):
        self.approach_mat, self.approach_amount = self.additive('Approaching star', STAR_WARM, 14.0, profile_power=0.5)
        self.recede_mat, self.recede_amount = self.additive('Receding star', STAR_WARM, 14.0, profile_power=0.5)
        self.approach = self.sphere('ApproachStar', 0.5, self.approach_mat, segments=24)
        self.recede = self.sphere('RecedeStar', 0.5, self.recede_mat, segments=24)
        blue, self.blue_wave_amount = self.additive('Blue wave', BLUE, 5.0)
        red, self.red_wave_amount = self.additive('Red wave', RED, 5.0)
        self.blue_wave = self.poly_curve('BlueWave', 160, blue, 0.07)
        self.red_wave = self.poly_curve('RedWave', 160, red, 0.07)
        self.movers += [self.approach, self.recede]

    def build_spectrum(self):
        mat = bpy.data.materials.new('Spectrum band')
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        coords = nodes.new('ShaderNodeTexCoord')
        xyz = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coords.outputs['Generated'], xyz.inputs[0])
        ramp = nodes.new('ShaderNodeValToRGB')
        stops = [(0.0, (0.3, 0.02, 0.55)), (0.16, (0.12, 0.12, 1.0)), (0.33, (0.0, 0.7, 1.0)),
                 (0.5, (0.1, 0.95, 0.2)), (0.66, (1.0, 0.92, 0.05)), (0.82, (1.0, 0.45, 0.0)), (1.0, (0.85, 0.03, 0.03))]
        elements = ramp.color_ramp.elements
        elements[0].position, elements[0].color = stops[0][0], (*stops[0][1], 1)
        elements[1].position, elements[1].color = stops[-1][0], (*stops[-1][1], 1)
        for pos, col in stops[1:-1]:
            e = elements.new(pos)
            e.color = (*col, 1)
        links.new(xyz.outputs['X'], ramp.inputs['Fac'])
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Strength'].default_value = 1.0   # dim enough that glare does not wash out the dark line
        links.new(ramp.outputs['Color'], em.inputs['Color'])
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = 0.0
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(em.outputs[0], mix.inputs[2])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(mix.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'BLENDED'
        self.spectrum_alpha = mix.inputs[0]

        def plane(bm, w, h):
            for v in [(-w / 2, 0, -h / 2), (w / 2, 0, -h / 2), (w / 2, 0, h / 2), (-w / 2, 0, h / 2)]:
                bm.verts.new(v)
            bm.faces.new(bm.verts)
        self.spectrum = self.mesh_obj('SpectrumPanel', lambda bm: plane(bm, SPEC_W, SPEC_H), mat, smooth_faces=False)
        self.spectrum.location = SPEC_C
        self.rest_x = SPEC_C.x - SPEC_W / 2 + 0.56 * SPEC_W
        # One absorption line whose darkness follows a Gaussian across its width.
        lmat = bpy.data.materials.new('Absorption line')
        lmat.use_nodes = True
        nodes, links = lmat.node_tree.nodes, lmat.node_tree.links
        nodes.clear()
        coords = nodes.new('ShaderNodeTexCoord')
        sep = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coords.outputs['Generated'], sep.inputs[0])
        centred = nodes.new('ShaderNodeMath')
        centred.operation = 'SUBTRACT'
        centred.inputs[1].default_value = 0.5
        links.new(sep.outputs['X'], centred.inputs[0])
        units = nodes.new('ShaderNodeMath')
        units.operation = 'MULTIPLY'
        units.inputs[1].default_value = 2 * LINE_HALF_SPAN
        links.new(centred.outputs[0], units.inputs[0])
        square = nodes.new('ShaderNodeMath')
        square.operation = 'MULTIPLY'
        links.new(units.outputs[0], square.inputs[0])
        links.new(units.outputs[0], square.inputs[1])
        half = nodes.new('ShaderNodeMath')
        half.operation = 'MULTIPLY'
        half.inputs[1].default_value = -0.5
        links.new(square.outputs[0], half.inputs[0])
        gauss = nodes.new('ShaderNodeMath')
        gauss.operation = 'EXPONENT'
        links.new(half.outputs[0], gauss.inputs[0])
        depth = nodes.new('ShaderNodeMath')
        depth.operation = 'MULTIPLY'
        depth.inputs[1].default_value = 0.0
        links.new(gauss.outputs[0], depth.inputs[0])
        dark = nodes.new('ShaderNodeEmission')
        dark.inputs['Color'].default_value = (0, 0, 0, 1)
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        links.new(depth.outputs[0], mix.inputs[0])
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(dark.outputs[0], mix.inputs[2])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(mix.outputs[0], out.inputs['Surface'])
        lmat.surface_render_method = 'BLENDED'
        self.line_depth = depth.inputs[1]
        self.line = self.mesh_obj('AbsorptionLine', lambda bm: plane(bm, 1.0, SPEC_H), lmat, smooth_faces=False)
        mark_mat, self.mark_amount = self.additive('Width marks', (1.0, 1.0, 1.0), 4.0)
        self.marks = [self.box(f'WidthMark{"L" if s < 0 else "R"}', (0.08, 0.08, SPEC_H + 1.4), mark_mat) for s in (-1, 1)]
        ring_mat, self.ring_amount = self.additive('Radius ring', CYAN, 5.0)
        self.ring = self.torus('RadiusRing', G_R, 0.07, ring_mat)
        self.ring.rotation_euler = (math.pi / 2, 0, 0)
        self.radius_line = self.cylinder('RadiusLine', 0.07, 1.0, ring_mat, segments=12)
        self.radius_line.rotation_euler = (0, math.pi / 2, 0)
        self.movers += [self.spectrum, self.line, *self.marks, self.ring, self.radius_line]

    def build_telescope(self):
        self.jwst, meshes = self.import_glb('James Webb Space Telescope (A).glb', 'WebbTelescope', 16.0, JWST_C)
        look = (-FAR_DIR).to_track_quat('Y', 'Z')
        self.jwst.rotation_mode = 'QUATERNION'
        self.jwst.rotation_quaternion = look
        self.jwst_parts = meshes
        self.jwst_fade = self.fade_asset(meshes)
        self.movers.append(self.jwst)

    def build_prism(self):
        # Only the glass body of the asset; the galaxy's own light beam and its split rays are drawn here.
        self.scope, meshes = self.import_glb('Reflection:Refraction Prism.glb', 'Prism', 4.0, PRISM_C,
                                             rotation=(0, 0, math.radians(45)),
                                             keep=lambda n: 'Pyramid' in n)
        self.scope.scale = (1, 1, 1.8)   # the asset's pyramid is squat; stand it up so it reads as a prism
        self.scope_parts = meshes
        self.scope_fade = self.fade_asset(meshes)
        beam_mat, self.beam_amount = self.additive('Galaxy light beam', (1.0, 0.92, 0.75), 5.0)
        self.light_in = self.poly_curve('GalaxyLightIn', 24, beam_mat, 0.1)
        self.rays = []
        for k, colour in enumerate(RAINBOW):
            mat, amount = self.additive(f'Prism ray {k}', colour, 4.0)
            self.rays.append((self.poly_curve(f'PrismRay-{k}', 12, mat, 0.08), amount))

    def build_halo(self):
        mat, self.halo_amount = self.additive('Dark matter halo rim', (0.45, 0.3, 1.0), 1.0, profile_power=4.0, rim=True)
        self.halo = self.sphere('DarkMatterHalo', HALO_R, mat, segments=64)
        fill, self.halo_fill = self.shade('Dark matter halo fill', (0.02, 0.0, 0.05), 0.0)
        self.halo_shade = self.sphere('DarkMatterHaloFill', HALO_R * 0.98, fill, segments=64)
        self.movers += [self.halo]

    # ---------- camera ----------
    def shot_pose(self, shot, st, u, t):
        e = smooth(u)
        drift = Vector((0.6 * math.sin(t * 0.21), 0, 0.35 * math.sin(t * 0.17)))
        o = Vector((0, 0, 0))
        if shot == 'hook_wide':
            centre = SCALE_C + Vector((0, 0, 3.9))
            return centre + Vector((lerp(2.5, 1.5, e), lerp(-25, -22, e), 1.2)), centre, 38
        if shot == 'galaxy_close':
            return Vector((lerp(4.5, 2.5, e), lerp(-15.5, -11.5, e), lerp(2.6, 1.6, e))), Vector((0, 0, 0)), 28
        if shot == 'galaxy_front':
            return Vector((0, lerp(-56, -50, e), 4)) + drift, o, 45
        if shot == 'two_galaxies':
            return Vector((-15 + lerp(-2, 2, e), -64, 7)), Vector((-15, 4, 0)), 38
        if shot == 'tracers':
            a = math.radians(lerp(-70, -58, e))
            return Vector((42 * math.cos(a), 42 * math.sin(a), 20)), o, 42
        if shot == 'fling':
            return Vector((12, -46, 7)) + drift, Vector((4, 0, 1)), 40
        if shot == 'well_high':
            a = math.radians(lerp(-100, -80, e))
            return Vector((36 * math.cos(a), 36 * math.sin(a), 24)), Vector((0, 0, -4.5)), 34
        if shot == 'well_bars':
            return Vector((8, -44, 19)) + drift * 0.5, Vector((8.5, 0, -3.5)), 34
        if shot == 'bars_close':
            return Vector((29.4, lerp(-27, -26, e), 0.0)), Vector((29.4, 0, 0.0)), 38
        if shot == 'galaxy_measure':
            return Vector((13, lerp(-66, -63, e), 0.0)), Vector((13, 0, 0)), 42
        if shot == 'galaxy_ring':
            return Vector((0, lerp(-52, -48, e), 0.0)), o, 42
        if shot == 'far_away':
            d = lerp(735, 760, e)
            return FAR_DIR * lerp(722, 728, e) + Vector((4.0, -1.0, 2.5)), o, 40
        if shot == 'doppler_front':
            return Vector((0, lerp(-32, -28, e), 24)), Vector((0, 0, -1)), 40
        if shot == 'doppler_side':
            return Vector((lerp(40, 37, e), -7, 5)), Vector((0, -7, 0)), 36
        if shot == 'spectrum':
            return Vector((12.6, lerp(-58, -54, e), -2.5)), Vector((12.6, -2, -4.5)), 40
        if shot == 'scale_compare':
            return Vector((lerp(-2, 2, e), -46, -3)), SCALE_C + Vector((0, 0, 4.2)), 40
        if shot == 'scale_dyn_close':
            ball = self.pan_point(1, st) - Vector((0, 0, PAN_DROP - 1.6))
            return ball + Vector((lerp(-2.0, -1.2, e), -14.0, 1.8)), ball, 45
        if shot == 'halo_wide':
            return Vector((0, lerp(-118, -108, e), 12)), o, 40
        if shot == 'closing':
            a = math.radians(-90 + 28 * e)
            return Vector((105 * math.cos(a), 105 * math.sin(a), lerp(14, 20, e))), o, 40
        raise ValueError(shot)

    def camera_pose(self, st, t):
        pos, tgt, lens = self.shot_pose(st['shot'], st, st['shot_u'], t)
        if st['prev_shot'] != st['shot']:
            p0, t0, l0 = self.shot_pose(st['prev_shot'], st, 1.0, t)
            ratio = max((pos - tgt).length, 1e-3) / max((p0 - t0).length, 1e-3)
            seconds = max(1.0, min(3.2, 0.9 + 0.6 * abs(math.log(ratio)) + (tgt - t0).length / 30))
            q = smoother(st['shot_elapsed'] / seconds)
            o0, o1 = p0 - t0, pos - tgt
            tgt = t0.lerp(tgt, q)
            d = math.exp(lerp(math.log(max(o0.length, 1e-3)), math.log(max(o1.length, 1e-3)), q))
            direction = o0.normalized().lerp(o1.normalized(), q)
            if direction.length < 1e-4:
                direction = o1.normalized()
            pos = tgt + direction.normalized() * d
            lens = lerp(l0, lens, q)
        return pos, tgt, lens

    # ---------- per-frame helpers ----------
    def scale_drop(self, st):
        return Vector((0, 0, -SCALE_DROP * (1 - smooth(st['scale']))))

    def pan_point(self, side, st, dropped=True):
        theta = 0.2 * st['tilt']
        top = self.scale_top + (self.scale_drop(st) if dropped else Vector((0, 0, 0)))
        return top + Vector((BEAM_HALF * side * math.cos(theta), 0, -BEAM_HALF * side * math.sin(theta)))

    def well_z(self, r, depth):
        return -depth * well_profile(min(r, WELL_RIM), WELL_RIM)

    def slow_pos(self, t, depth):
        th = 0.5 + 0.42 * t
        r = 8.8
        return Vector((r * math.cos(th), r * math.sin(th), self.well_z(r, depth) + 0.55))

    def fast_pos(self, e, depth):
        r = 6.4 + 13.5 * e ** 1.5
        th = 2.2 + 3.3 * e
        z = self.well_z(r, depth) + 0.55 + max(0.0, r - WELL_RIM) * 0.35
        return Vector((r * math.cos(th), r * math.sin(th), z)), r

    def held_pos(self, clock, depth):
        r = 6.2
        th = 4.0 + clock
        return Vector((r * math.cos(th), r * math.sin(th), self.well_z(r, depth) + 0.55))

    def depth_at(self, st):
        return well_depth_units(st['well_depth'])

    # ---------- per frame ----------
    def sample(self, frame):
        st = self.states[frame]
        entry = self.job['canonical_state_cache'][frame]
        t = entry['simulation_time']
        clock = self.orbit_clock[frame]
        fps = self.job['canonical_fps']
        self.state = {k: round(v, 6) if isinstance(v, float) else v for k, v in st.items()}
        # elliptical galaxy: collapse into the core while the gravity well is shown
        ell = smooth(st['elliptical'])
        c = lerp(0.1, 1.0, ell)
        self.star_swarm.scale = (c, c, c)
        for shell, base, omega in self.shells:
            shell.rotation_quaternion = base @ Quaternion(spin_quaternion(omega * clock))
        for socket in self.star_amounts:
            socket.default_value = smooth(min(1.0, ell * 1.6))
        self.glow.scale = (c, c, c)
        self.glow_mid.scale = (c, c, c)
        self.glow_amount.default_value = ell * (1 + 0.8 * st['mass_glow'])
        self.mid_amount.default_value = ell * (1 + 0.8 * st['mass_glow'])
        for obj in (self.glow, self.glow_mid):
            obj.hide_render = ell < 0.002
        for shell, _, _ in self.shells:
            shell.hide_render = ell < 0.002
        depth = self.depth_at(st)
        well = smooth(st['well'])
        core_r = 1.25 * (1 + 0.42 * st['core_mass'])
        # The whole galaxy shrinks into the well bottom, or onto the balance pan.
        centre = Vector((0, 0, lerp(0.0, -depth + core_r * 0.35, well)))
        on = smooth(st['on_scale'])
        pan_top = self.pan_point(1, st, dropped=False) - Vector((0, 0, PAN_DROP - 0.06 - G_R * G_SCALE.z * ON_SCALE))
        centre = centre.lerp(pan_top, on) + Vector((0, 0, 2.5 * math.sin(math.pi * on)))
        size = lerp(1.0, ON_SCALE, on)
        self.galaxy.location = centre
        self.galaxy.scale = G_SCALE * size
        self.core.location = centre
        self.core.scale = (core_r * size,) * 3
        pulse = 1 + 0.25 * st['mass_glow'] * (0.5 + 0.5 * math.sin(t * 4.0))
        self.core_amount.default_value = max(ell, well, 0.35) * pulse
        # tracer orbits and trails
        tr = st['tracers']
        self.trail_amount.default_value = tr * ell
        self.tracer_amount.default_value = tr * ell
        for orbit, star, trail in self.tracers:
            star.location = self.orbit_pos(orbit, clock)
            span = 1.5 / abs(orbit['omega'])
            self.set_curve(trail, [self.orbit_pos(orbit, clock - span * (1 - k / 39)) for k in range(40)])
            star.hide_render = trail.hide_render = tr * ell < 0.002
        fp = st['fling']
        self.fling_star.location = self.fling_pos(fp)
        self.set_curve(self.fling_trail, [self.fling_pos(max(0.0, fp - 0.35 * (1 - k / 47))) for k in range(48)])
        fvis = st['fling_star'] * ell
        self.fling_amount.default_value = fvis
        self.fling_trail_amount.default_value = fvis
        self.fling_star.hide_render = self.fling_trail.hide_render = fvis < 0.002
        # spiral galaxy turning one way
        sp = st['spiral']
        self.spiral_disk.rotation_euler = (0, 0, -0.23 * t)
        for socket in (self.arm_amount, self.bulge_amount, self.disk_amount):
            socket.default_value = sp
        for obj in self.spiral_disk.children:
            obj.hide_render = sp < 0.002
        self.update_scale(st, t)
        self.update_well(st, t, frame, depth, well)
        self.update_bars(st)
        self.update_doppler(st, t)
        self.update_spectrum(st)
        halo = smooth(st['halo'])
        self.halo_amount.default_value = halo
        self.halo_fill.default_value = 0.22 * halo
        self.halo.hide_render = self.halo_shade.hide_render = halo < 0.002
        self.halo.scale = (lerp(0.85, 1.0, halo),) * 3
        self.halo_shade.scale = self.halo.scale
        pos, tgt, lens = self.camera_pose(st, t)
        self.camera.location = pos
        self.camera.rotation_euler = (tgt - pos).to_track_quat('-Z', 'Y').to_euler()
        self.camera.data.lens = lens
        self.sky.location = pos
        self.update_instruments(st)
        tracked = [self.camera, self.galaxy, self.core, self.spiral_disk, self.beam, self.well_grid, self.k_bar,
                   self.u_bar, self.approach, self.recede, self.spectrum, self.halo, self.fling_star,
                   *(s for _, s, _ in self.tracers)]
        return entry, tracked

    def update_scale(self, st, t):
        vis = smooth(st['scale'])
        self.brass_alpha.default_value = vis
        for obj in self.scale_parts:
            obj.hide_render = vis < 0.002
        theta = 0.2 * st['tilt']
        drop = self.scale_drop(st)
        for obj, home in self.scale_fixed:
            obj.location = home + drop
        self.beam.location = self.scale_top + drop
        self.beam.rotation_euler = (0, theta, 0)
        for side, pan in zip((-1, 1), self.pans):
            end = self.pan_point(side, st)
            pan.location = end - Vector((0, 0, PAN_DROP))
        for side, k, cord in self.cords:
            end = self.pan_point(side, st)
            a = math.tau * k / 3 + 0.5
            rim = end - Vector((0, 0, PAN_DROP)) + Vector((1.35 * math.cos(a), 1.35 * math.sin(a), 0.06))
            mid = (end + rim) / 2
            d = rim - end
            cord.location = mid
            cord.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
            cord.scale = (1, 1, d.length)
        left = self.pans[0].location + Vector((0, 0, 0.06 + 0.9))
        right = self.pans[1].location + Vector((0, 0, 0.06 + 0.9))
        lb = smooth(st['light_ball'])
        self.light_ball.location = left
        self.light_ball.scale = (max(1e-4, lb),) * 3
        self.light_ball_amount.default_value = lb * vis
        self.light_ball.hide_render = lb * vis < 0.002
        db = smooth(st['dyn_ball'])
        ds = smooth(st['dark_shell'])
        for obj in (self.dyn_core, self.dark_shell, self.dark_fill):
            obj.location = right + Vector((0, 0, 0.62))
        self.dyn_core.scale = (max(1e-4, db),) * 3
        self.dark_shell.scale = self.dark_fill.scale = (max(1e-4, db),) * 3
        self.dyn_core_amount.default_value = db * vis
        self.shell_amount.default_value = db * vis * (0.55 + 1.4 * ds * (0.75 + 0.25 * math.sin(t * 3.0)))
        self.shell_fill.default_value = 0.55 * db * vis
        for obj in (self.dyn_core, self.dark_shell, self.dark_fill):
            obj.hide_render = db * vis < 0.002
        # light leaving the galaxy and gathering on the left pan
        fl = st['light_flow']
        start = Vector((-4.0, -6.5, -2.0))
        end = left + Vector((0, 0, 0.3))
        ctrl = (start + end) / 2 + Vector((-3.0, 0, 5.0))
        for i, p in enumerate(self.flow):
            ph = (t * 0.45 + golden(i)) % 1.0
            q = smooth(ph)
            spread = Vector(((golden(i * 3) - 0.5) * 3.0, 0, (golden(i * 5) - 0.5) * 2.0)) * (1 - q)
            p.location = (1 - q) ** 2 * start + 2 * (1 - q) * q * ctrl + q * q * end + spread
            amt = fl * math.sin(math.pi * ph)
            p.scale = (max(1e-4, 0.4 + 0.6 * amt),) * 3
            p.hide_render = amt < 0.01
        self.flow_amount.default_value = fl

    def update_well(self, st, t, frame, depth, well):
        verts = self.well_grid.data.vertices
        co = array('f', [0.0]) * (3 * len(verts))
        verts.foreach_get('co', co)
        for i, r in enumerate(self.well_radii):
            co[3 * i + 2] = -depth * well_profile(r, WELL_RIM) * well
        verts.foreach_set('co', co)
        self.well_grid.data.update()
        self.well_surface.data.vertices.foreach_set('co', co)
        self.well_surface.data.update()
        self.grid_amount.default_value = well
        self.surface_amount.default_value = well
        self.well_grid.hide_render = self.well_surface.hide_render = well < 0.002
        fps = self.job['canonical_fps']
        shown_depth = depth * well
        # slow star holds a wide orbit
        sv = smooth(st['slow_star']) * well
        self.slow_ball.location = self.slow_pos(t, shown_depth)
        self.set_curve(self.slow_trail, [self.slow_pos(t - 1.4 * (1 - k / 29), shown_depth) for k in range(30)])
        self.slow_amount.default_value = sv
        self.slow_trail_amount.default_value = sv
        self.slow_ball.hide_render = self.slow_trail.hide_render = sv < 0.002
        # fast star climbs out of the shallow well
        e = st['escape']
        pos, r = self.fast_pos(e, shown_depth)
        leave = 1 - smooth((r - 18.0) / 2.0)
        fv = smooth(st['fast_star']) * well * leave
        self.fast_ball.location = pos
        history = [self.states[max(0, frame - 2 * (29 - k))]['escape'] for k in range(30)]
        self.set_curve(self.fast_trail, [self.fast_pos(h, shown_depth)[0] for h in history])
        self.fast_amount.default_value = fv
        self.fast_trail_amount.default_value = fv
        self.fast_ball.hide_render = self.fast_trail.hide_render = fv < 0.002
        # fast star held by a deeper well
        hv = smooth(st['held_star']) * well
        hc = self.held_clock
        self.held_ball.location = self.held_pos(hc[frame], shown_depth)
        pts = [self.held_pos(hc[max(0, frame - 2 * (29 - k))], shown_depth) for k in range(30)]
        self.set_curve(self.held_trail, pts)
        self.held_amount.default_value = hv
        self.held_trail_amount.default_value = hv
        self.held_ball.hide_render = self.held_trail.hide_render = hv < 0.002

    def update_bars(self, st):
        vis = smooth(st['bars'])
        k, u = kinetic_potential(st['bars_level'])
        grow = smooth(st['bars'] * 1.2)
        hk = max(1e-3, k * grow)
        self.k_bar.location = BARS + Vector((0, 0, hk / 2))
        self.k_bar.scale = (1, 1, hk)
        d2 = smooth(st['double_k'])
        h2 = max(1e-3, k * d2)
        self.k2_bar.location = BARS + Vector((0, 0, hk + h2 / 2))
        self.k2_bar.scale = (1, 1, h2)
        hu = max(1e-3, -u * grow)
        self.u_bar.location = BARS + Vector((2.1, 0, -hu / 2))
        self.u_bar.scale = (1, 1, hu)
        self.zero.location = BARS + Vector((1.05, 0, 0))
        self.k_amount.default_value = vis
        self.k2_amount.default_value = vis * d2
        self.u_amount.default_value = vis
        self.zero_amount.default_value = vis
        for obj in (self.k_bar, self.u_bar, self.zero):
            obj.hide_render = vis < 0.002
        self.k2_bar.hide_render = vis * d2 < 0.002

    def update_doppler(self, st, t):
        dv = smooth(st['doppler'])
        th = 0.07 * (t - self.doppler_t0)
        self.recede.location = Vector((DOPPLER_R * math.cos(th), DOPPLER_R * math.sin(th), -2.2))
        self.approach.location = Vector((-DOPPLER_R * math.cos(th), -DOPPLER_R * math.sin(th), 2.2))
        warm = Vector(STAR_WARM)
        for mat, colour in ((self.approach_mat, BLUE), (self.recede_mat, RED)):
            em = next(n for n in mat.node_tree.nodes if n.type == 'EMISSION')
            em.inputs['Color'].default_value = (*warm.lerp(Vector(colour), dv), 1)
        self.approach_amount.default_value = dv
        self.recede_amount.default_value = dv
        self.approach.hide_render = self.recede.hide_render = dv < 0.002
        wv = smooth(st['waves'])
        for obj, star, lam, amount in ((self.blue_wave, self.approach, 1.0, self.blue_wave_amount),
                                       (self.red_wave, self.recede, 2.5, self.red_wave_amount)):
            base = star.location
            length = 17.0
            pts = []
            for k in range(160):
                s = 0.6 + length * k / 159
                pts.append((base.x, base.y - s, base.z + 0.7 * math.sin(math.tau * (s - 3.2 * t) / lam)))
            self.set_curve(obj, pts)
            amount.default_value = wv
            obj.hide_render = wv < 0.002

    def update_spectrum(self, st):
        sv = smooth(st['spectrum'])
        self.spectrum_alpha.default_value = sv
        self.spectrum.hide_render = sv < 0.002
        # The line appears narrow (one star) and widens as the starlight mixes, then tracks sigma.
        s, d = line_profile(st['sigma'], st['lines'])
        appear = min(1.0, st['lines'] * 6.0) * sv
        self.line.location = Vector((self.rest_x, SPEC_C.y - 0.3, SPEC_C.z))   # clearly in front, so it sorts over the band
        self.line.scale = (2 * LINE_HALF_SPAN * s, 1, 1)
        self.line_depth.default_value = d * appear
        self.line.hide_render = appear < 0.002
        wm = smooth(st['width_marks']) * sv
        for side, mark in zip((-1, 1), self.marks):
            mark.location = Vector((self.rest_x + side * 1.1774 * s, SPEC_C.y - 0.2, SPEC_C.z))   # half maximum
            mark.hide_render = wm < 0.002
        self.mark_amount.default_value = wm
        rr = smooth(st['radius_ring'])
        self.ring.scale = (max(1e-4, rr), max(1e-4, rr * G_SCALE.z / G_SCALE.x), max(1e-4, rr))
        self.ring.location = Vector((0, -0.2, 0))
        self.ring_amount.default_value = rr
        self.radius_line.location = Vector((G_R * rr / 2, -0.2, 0))
        self.radius_line.scale = (1, 1, max(1e-4, G_R * rr))
        self.ring.hide_render = self.radius_line.hide_render = rr < 0.002

    def update_instruments(self, st):
        far = smooth(st['telescope'])
        for socket in self.jwst_fade:
            socket.default_value = far
        for o in self.jwst_parts:
            o.hide_render = far < 0.002
        sv = smooth(st['spectrum'])
        for socket in self.scope_fade:
            socket.default_value = sv
        for o in self.scope_parts:
            o.hide_render = sv < 0.002
        start = Vector((7.0, -2.0, -4.5))   # lower-right edge of the galaxy
        reach = smooth(st['lines'] * 3.0) if sv > 0.002 else 0.0
        self.set_curve(self.light_in, [start.lerp(PRISM_C, reach * k / 23) for k in range(24)])
        out = smooth(st['lines'] * 3.0 - 1.0) if sv > 0.002 else 0.0
        for k, (ray, amount) in enumerate(self.rays):
            frac = (k + 0.5) / len(self.rays)
            hit = Vector((SPEC_C.x - SPEC_W / 2 + frac * SPEC_W, SPEC_C.y - 0.1, SPEC_C.z - SPEC_H / 2))   # bottom edge, under its colour
            self.set_curve(ray, [PRISM_C.lerp(hit, out * j / 11) for j in range(12)])
            amount.default_value = sv
            ray.hide_render = sv * out < 0.002
        self.beam_amount.default_value = sv
        self.light_in.hide_render = sv * reach < 0.002

    def extra_state(self):
        return dict(self.state)

    def bake(self):
        from bpy_extras import anim_utils
        self.sample(0)
        movers = list(dict.fromkeys(self.movers))
        for obj in movers:
            rot = 'rotation_quaternion' if obj.rotation_mode == 'QUATERNION' else 'rotation_euler'
            for prop in ('location', 'scale', rot):
                obj.keyframe_insert(data_path=prop, frame=1)
        self.camera.data.keyframe_insert(data_path='lens', frame=1)
        owners = [*movers, self.camera.data]
        channels = []
        for owner in owners:
            ad = getattr(owner, 'animation_data', None)
            if not ad or not ad.action:
                continue
            bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
            for curve in bag.fcurves:
                value = owner.path_resolve(curve.data_path)
                channels.append((curve, owner, curve.data_path, curve.array_index, hasattr(value, '__len__')))
        count = self.job['duration_frames']
        # Renders read these keys, not sample(): key every frame so nothing is interpolated between them.
        frames = list(range(count))
        columns = [array('f') for _ in channels]
        for frame in frames:
            self.sample(frame)
            for (_, owner, path, index, vector), column in zip(channels, columns):
                value = owner.path_resolve(path)
                column.append(float(value[index] if vector else value))
        for (curve, *_), values in zip(channels, columns):
            if min(values) == max(values):
                continue
            points = curve.keyframe_points
            points.add(len(frames) - len(points))
            co = array('f', [0.0]) * (2 * len(frames))
            co[0::2] = array('f', [f + 1 for f in frames])
            co[1::2] = values
            points.foreach_set('co', co)
            for p in points:
                p.interpolation = 'LINEAR'
            curve.update()
        self.scene.frame_set(1)
        bpy.ops.file.pack_all()
