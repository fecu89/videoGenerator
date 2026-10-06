"""Classroom coin line, gas slabs and a layered star for the transfer-equation story.

No people and no on-screen text. Desks stand for students and the teacher's
desk tray for the teacher. Every coin is a real object that slides, leaves or
arrives according to transfer_equation_story_math; stack heights are drawn at
the exact value (for example 8.5), so a stack of nine coins is gently
compressed to 8.5 coin heights.
"""
import math
from array import array
import bmesh
import bpy
from mathutils import Matrix, Vector
try:
    from .callout import CalloutLayer, labels_from_job
    from .optical_depth import OpticalDepthGallery
    from .transfer_equation_story_math import (
        EXTINCTION, SOURCE, STEPS, beam_intensities, beam_radius, lane_plan, sequence_values,
        smooth, smoother, state_at, step_phase)
except ImportError:
    from callout import CalloutLayer, labels_from_job
    from optical_depth import OpticalDepthGallery
    from transfer_equation_story_math import (
        EXTINCTION, SOURCE, STEPS, beam_intensities, beam_radius, lane_plan, sequence_values,
        smooth, smoother, state_at, step_phase)

ROW_X = 0.0
LANE_B_X = 1.25
DESK_Y = [3.9 - 0.9 * i for i in range(8)]
DESK_TOP = 0.79
STACK_OFFSET = Vector((-0.24, 0.12, 0.0))
JAR_OFFSET = Vector((-0.18, -0.2, 0.0))
TRAY = Vector((0.0, -3.28, 0.80))
BALANCE_OFFSET = Vector((-0.34, 0.0, 0.0))      # beside the arrived stack on the teacher desk
COMPARE_DESK = Vector((-1.5, 0.45, 0.0))
BEAM_Z = 1.12
SLAB_T = [0.42, 0.22, 0.34, 0.18, 0.30, 0.24, 0.38, 0.20]
STAR_C = Vector((0.0, 34.0, BEAM_Z))
STAR_R = 20.0
TAU_SHELL = 0.955
COIN_DIAMETER = 0.15
COIN_THICKNESS = 0.0105
BRONZE = (0.72, 0.45, 0.2)


def lerp(a, b, p):
    return a + (b - a) * p


def golden(i):
    return (i * 0.6180339887) % 1.0


class CoinLane:
    """One stack following the rule along a list of stack points."""

    def __init__(self, gallery, name, start, points, jars, *, steps=STEPS, tray=None, blue=False):
        self.g, self.name = gallery, name
        self.plan = lane_plan(start, steps, blue=blue)
        self.points, self.jars, self.tray = points, jars, tray
        self.root = gallery.link(name, None)
        anchor = gallery.link(name + ' anchor', gallery.anchor_mesh())
        anchor.parent = self.root
        anchor.hide_render = True
        self.coins = []
        for i, colour in enumerate(self.plan['colours']):
            coin = gallery.coin(f'{name} coin {i:03d}', colour)
            self.coins.append(coin)
        self.exact_blue = [72 * EXTINCTION ** (k + 1) for k in range(steps)] if blue else None

    def slot_z(self, index, count, value):
        spacing = self.g.coin_th * (value / count if count else 1.0)
        return DESK_TOP + self.g.coin_th / 2 + index * spacing

    def evaluate(self, t, visible):
        plan, steps = self.plan, self.plan['steps']
        n = len(steps)
        if self.tray is not None and t > n - 1:
            t = n - 1 + (t - (n - 1)) * 1.5  # arrive at the tray early and rest there
        t = max(0.0, min(float(n), t))
        k = min(int(t), n - 1)
        u = 1.0 if t >= n else t - k
        pos = {}
        before = plan['initial'] if k == 0 else steps[k - 1]['stack']
        value_before = plan['start'] if k == 0 else steps[k - 1]['value']
        step = steps[k]
        s, r, a = (step_phase(u, p) for p in ('slide', 'remove', 'add'))
        tr = step_phase(u, 'tray') if (self.tray is not None and k == n - 1) else 0.0
        p0, p1 = self.points[k], self.points[k + 1]
        base = p0.lerp(p1, s) + Vector((0, 0, 0.04 * math.sin(math.pi * s)))
        if tr > 0:
            base = p1.lerp(self.tray, tr) + Vector((0, 0, 0.04 * math.sin(math.pi * tr)))
        for j in range(k):  # coins already kept on earlier desks
            jar = self.jars[j + 1]
            for idx, cid in enumerate(steps[j]['removed']):
                pos[cid] = jar + Vector((0, 0, DESK_TOP + self.g.coin_th * (idx + 0.5)))
        kept_value = value_before * (1 - EXTINCTION)
        n_before, n_kept, n_after = len(before), len(step['kept']), len(step['stack'])
        slot = {cid: i for i, cid in enumerate(before)}
        for cid in before:
            z0 = self.slot_z(slot[cid], n_before, value_before)
            if cid in step['kept']:
                i = step['kept'].index(cid)
                z = lerp(z0, self.slot_z(i, n_kept, kept_value), r) if a == 0 else \
                    lerp(self.slot_z(i, n_kept, kept_value), self.slot_z(i, n_after, step['value']), a)
                pos[cid] = Vector((base.x, base.y, z))
            else:
                idx = step['removed'].index(cid)
                start = Vector((base.x, base.y, z0))
                end = self.jars[k + 1] + Vector((0, 0, DESK_TOP + self.g.coin_th * (idx + 0.5)))
                q = smooth((r - 0.4 * idx / max(1, len(step['removed']))) / 0.6) if r < 1 else 1.0
                pos[cid] = start.lerp(end, q) + Vector((0, 0, 0.22 * math.sin(math.pi * q)))
        scales = {}
        for i, cid in enumerate(step['added']):
            if a <= 0:
                continue
            q = smooth((a - 0.15 * i) / 0.55)
            start = Vector((base.x + 0.05, base.y - 0.06, DESK_TOP - 0.06))
            end = Vector((base.x, base.y, self.slot_z(n_kept + i, n_after, step['value'])))
            pos[cid] = start.lerp(end, q) + Vector((0, 0, 0.12 * math.sin(math.pi * q)))
            scales[cid] = min(1.0, q * 3)
        for cid, coin in enumerate(self.coins):
            if cid in pos and visible > 0.001:
                coin.hide_render = False
                coin.location = pos[cid]
                coin.scale = (self.g.coin_scale * visible * scales.get(cid, 1.0),) * 3
            else:
                coin.hide_render = True
                coin.scale = (1e-5,) * 3
        self.root.location = base
        self.root.scale = (1, 1, 1)
        exact = step['value'] if a >= 1 else (kept_value if r > 0 else value_before)
        return dict(step=k, base=base, value=exact)

    def blue_alpha(self, t):
        if not self.exact_blue:
            return 1.0
        k = max(0, min(len(self.exact_blue) - 1, int(t) - (0 if t % 1 > 0.58 else 1)))
        stack = self.plan['steps'][k]['stack']
        count = sum(self.plan['colours'][c] == 'blue' for c in stack)
        return min(1.0, self.exact_blue[k] / max(1, count))


class TransferEquationStoryGallery(OpticalDepthGallery):
    def build(self):
        self.scene.name = 'Transfer equation — coins, gas and a star'
        for name in ('Softbox',):
            if name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
        self.scene.view_settings.view_transform = 'AgX'
        self.scene.view_settings.look = 'AgX - Punchy'
        self.scene.eevee.taa_render_samples = 16
        # A full shadow pool stops EEVEE dropping shadows frame to frame (flicker in camera moves).
        self.scene.eevee.shadow_pool_size = '2048'
        world = self.scene.world
        world.use_nodes = True
        bg = world.node_tree.nodes['Background']
        bg.inputs['Color'].default_value = (0.012, 0.02, 0.045, 1)
        bg.inputs['Strength'].default_value = 0.6
        self.camera.data.type = 'PERSP'
        self.camera.data.clip_start = 0.05
        self.camera.data.clip_end = 600
        self.animated = [self.camera]
        self.fade_sockets = []      # (socket, group)
        self.room_objects = []
        self.room_lights = []
        self.build_coin_proto()
        self.build_classroom()
        self.build_lanes()
        self.build_atmosphere()
        self.build_star()
        self.state = {}
        self.last_pose = None
        self.build_white_card()
        # Subtitle films declare no labels; the layer stays bound but empty.
        self.callouts = CalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job), {o.name: o for o in self.scene.objects})

    # ---------- helpers ----------
    def emission(self, name, color, strength=1.0, alpha=True):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*color, 1)
        em.inputs['Strength'].default_value = strength
        out = nodes.new('ShaderNodeOutputMaterial')
        if alpha:
            tr = nodes.new('ShaderNodeBsdfTransparent')
            mix = nodes.new('ShaderNodeMixShader')
            mix.inputs[0].default_value = 1.0
            links.new(tr.outputs[0], mix.inputs[1])
            links.new(em.outputs[0], mix.inputs[2])
            links.new(mix.outputs[0], out.inputs['Surface'])
            mat.surface_render_method = 'BLENDED'
            mat['fade'] = True
        else:
            links.new(em.outputs[0], out.inputs['Surface'])
        return mat

    def glassy(self, name, color, alpha, emission=0.0):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*color, 1)
        bsdf.inputs['Roughness'].default_value = 0.5
        bsdf.inputs['Emission Color'].default_value = (*color, 1)
        bsdf.inputs['Emission Strength'].default_value = emission
        out = nodes.get('Material Output')
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = alpha
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(bsdf.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'BLENDED'
        mat['base_alpha'] = alpha
        return mat

    def fade(self, mat):
        """Insert (once) an opacity mix in front of the material output; return its factor socket."""
        if mat is None or not mat.use_nodes:
            return None
        if 'fade_socket' in mat:
            return mat.node_tree.nodes[mat['fade_socket']].inputs[0]
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        out = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if out is None or not out.inputs['Surface'].links:
            return None
        old = out.inputs['Surface'].links[0].from_socket
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = 1.0
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(old, mix.inputs[2])
        links.new(mix.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'DITHERED'
        mat['fade_socket'] = mix.name
        return mix.inputs[0]

    def cylinder(self, name, radius, depth, mat, location=(0, 0, 0), axis='Z', vertices=24):
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
        obj = bpy.context.object
        obj.name = name
        if axis == 'Y':
            obj.rotation_euler = (math.pi / 2, 0, 0)
        obj.data.materials.append(mat)
        for f in obj.data.polygons:
            f.use_smooth = True
        return obj

    def import_flat(self, filename, scale=1.0):
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / 'assets' / filename
        before = set(self.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(path))
        imported = [o for o in self.scene.objects if o not in before]
        self.scene.view_layers[0].update()
        meshes = [o for o in imported if o.type == 'MESH']
        seen = set()
        for obj in meshes:
            if obj.data.users > 1 or obj.data.name in seen:
                obj.data = obj.data.copy()
            seen.add(obj.data.name)
            world = obj.matrix_world.copy()
            obj.parent = None
            obj.data.transform(Matrix.Scale(scale, 4) @ world)
            obj.matrix_world = Matrix.Identity(4)
        for obj in imported:
            if obj not in meshes:
                bpy.data.objects.remove(obj, do_unlink=True)
        for obj in meshes:
            for mat in obj.data.materials:
                if mat and mat.node_tree:
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image:
                            node.image.pack()
        return meshes

    @staticmethod
    def islands(bm):
        bm.verts.ensure_lookup_table()
        seen, out = set(), []
        for v in bm.verts:
            if v.index in seen:
                continue
            stack, group = [v], []
            seen.add(v.index)
            while stack:
                cur = stack.pop()
                group.append(cur)
                for e in cur.link_edges:
                    o = e.other_vert(cur)
                    if o.index not in seen:
                        seen.add(o.index)
                        stack.append(o)
            out.append(group)
        return out

    # ---------- coins ----------
    def build_coin_proto(self):
        """A solid bevelled disc wearing the roman_coins.glb face and rim textures.

        The scanned coins are thin face shells with a partial rim, which read as
        translucent, wavy stacks; a solid disc stacks cleanly and keeps the asset look.
        """
        meshes = self.import_flat('roman_coins.glb')
        pile = meshes[0]
        bm = bmesh.new()
        bm.from_mesh(pile.data)
        uv = bm.loops.layers.uv.active
        target = Vector((0.012, -0.002))
        discs, rims = [], []
        for group in self.islands(bm):
            c = sum((v.co for v in group), Vector()) / len(group)
            if (c.xy - target).length >= 0.012:
                continue
            faces = {f for v in group for f in v.link_faces}
            uvs = [l[uv].uv.copy() for f in faces for l in f.loops]
            lo = Vector((min(u.x for u in uvs), min(u.y for u in uvs)))
            hi = Vector((max(u.x for u in uvs), max(u.y for u in uvs)))
            size = hi - lo
            (discs if min(size) > 0.2 * max(size) else rims).append((lo, hi, len(faces)))
        bm.free()
        discs.sort(key=lambda d: -d[2])
        top = discs[0]
        bottom = discs[1] if len(discs) > 1 else discs[0]
        rim = rims[0] if rims else top
        R, H = COIN_DIAMETER / 2, COIN_THICKNESS
        coin = bmesh.new()
        bmesh.ops.create_cone(coin, cap_ends=True, cap_tris=False, segments=48, radius1=R, radius2=R, depth=H)
        bmesh.ops.bevel(coin, geom=[e for e in coin.edges if all(abs(abs(v.co.z) - H / 2) < 1e-6 for v in e.verts)
                                   and abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-6],
                        offset=H * 0.28, segments=2, affect='EDGES', profile=0.6)
        layer = coin.loops.layers.uv.new('UVMap')
        for face in coin.faces:
            n = face.normal
            for loop in face.loops:
                co = loop.vert.co
                if abs(n.z) > 0.7:
                    lo, hi, _ = top if n.z > 0 else bottom
                    centre, radius = (lo + hi) / 2, (hi - lo) / 2
                    loop[layer].uv = (centre.x + co.x / R * radius.x * 0.96, centre.y + co.y / R * radius.y * 0.96)
                else:
                    lo, hi, _ = rim
                    a = (math.atan2(co.y, co.x) / math.tau) % 1.0
                    across = (co.z / H + 0.5)
                    if (hi - lo).x < (hi - lo).y:
                        loop[layer].uv = (lo.x + across * (hi - lo).x, lo.y + a * (hi - lo).y)
                    else:
                        loop[layer].uv = (lo.x + a * (hi - lo).x, lo.y + across * (hi - lo).y)
        for f in coin.faces:
            f.smooth = abs(f.normal.z) < 0.7
        mesh = bpy.data.meshes.new('RomanCoin')
        coin.to_mesh(mesh)
        coin.free()
        mesh.materials.append(pile.data.materials[0])
        for m in meshes:
            bpy.data.objects.remove(m, do_unlink=True)
        self.coin_mesh = mesh
        self.coin_scale = 1.0
        self.coin_th = COIN_THICKNESS
        self.bronze = mesh.materials[0]
        pb = next(n for n in self.bronze.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        if pb.inputs['Base Color'].links:
            # Warm the scanned texture towards gold-bronze; the coin reads as metal, not beige.
            nt = self.bronze.node_tree
            gold = nt.nodes.new('ShaderNodeMix')
            gold.data_type = 'RGBA'
            gold.blend_type = 'MULTIPLY'
            gold.inputs['Factor'].default_value = 1.0
            gold.inputs['B'].default_value = (1.25, 0.72, 0.26, 1)
            nt.links.new(pb.inputs['Base Color'].links[0].from_socket, gold.inputs['A'])
            nt.links.new(gold.outputs['Result'], pb.inputs['Base Color'])
            nt.links.new(gold.outputs['Result'], pb.inputs['Emission Color'])
        pb.inputs['Emission Strength'].default_value = 0.45
        # Less mirror-like, so bright daylight does not wash the bronze out to silver.
        for name, value in (('Metallic', 0.55), ('Roughness', 0.42)):
            for link in list(pb.inputs[name].links):
                self.bronze.node_tree.links.remove(link)
            pb.inputs[name].default_value = value
        self.blue = self.bronze.copy()
        self.blue.name = 'Marked blue coin'
        nodes, links = self.blue.node_tree.nodes, self.blue.node_tree.links
        bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
        tint = nodes.new('ShaderNodeMix')
        tint.data_type = 'RGBA'
        tint.blend_type = 'MULTIPLY'
        tint.inputs['Factor'].default_value = 1.0
        tint.inputs['B'].default_value = (0.25, 0.55, 1.6, 1)
        src = bsdf.inputs['Base Color'].links[0].from_socket if bsdf.inputs['Base Color'].links else None
        if src:
            links.new(src, tint.inputs['A'])
        else:
            tint.inputs['A'].default_value = bsdf.inputs['Base Color'].default_value
        links.new(tint.outputs['Result'], bsdf.inputs['Base Color'])
        for link in list(bsdf.inputs['Emission Color'].links):
            links.remove(link)
        bsdf.inputs['Emission Color'].default_value = (0.06, 0.32, 1.0, 1)
        bsdf.inputs['Emission Strength'].default_value = 1.1
        tint.inputs['B'].default_value = (0.35, 0.7, 2.2, 1)
        self.blue_alpha = self.fade(self.blue)

    def anchor_mesh(self):
        if not hasattr(self, '_anchor'):
            self._anchor = bpy.data.meshes.new('Stack anchor')
            h = 0.25
            self._anchor.from_pydata([(x, y, z) for x in (-h, h) for y in (-h, h) for z in (0.0, 2 * h)], [], [])
        return self._anchor

    def coin(self, name, colour):
        obj = self.link(name, self.coin_mesh)
        obj.material_slots[0].link = 'OBJECT'
        obj.material_slots[0].material = self.blue if colour == 'blue' else self.bronze
        obj.scale = (1e-5,) * 3
        obj.hide_render = True
        return obj

    # ---------- classroom ----------
    def build_classroom(self):
        meshes = self.import_flat('classroom.glb', 0.01)
        grid = next(o for o in meshes if o.name.startswith('Cube_Desk'))
        chairs = [o for o in meshes if 'chair' in o.name.lower()]
        proto_chair = min(chairs, key=lambda o: (o.matrix_world @ o.data.vertices[0].co - Vector((2.78, 2.18, 0))).length
                          if o.data.vertices else 1e9)
        chair_center = sum((v.co for v in proto_chair.data.vertices), Vector()) / len(proto_chair.data.vertices)
        # One student desk out of the merged grid of twenty.
        bm = bmesh.new()
        bm.from_mesh(grid.data)
        box = lambda co: 2.30 <= co.x <= 3.52 and 1.58 <= co.y <= 2.38
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not all(box(v.co) for v in f.verts)], context='FACES')
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
        desk_center = Vector((2.91, 1.98, 0))
        bmesh.ops.translate(bm, vec=-desk_center, verts=bm.verts)
        desk_mesh = bpy.data.meshes.new('StudentDesk')
        bm.to_mesh(desk_mesh)
        bm.free()
        for mat in grid.data.materials:
            desk_mesh.materials.append(mat)
        chair_mesh = proto_chair.data.copy()
        chair_mesh.transform(Matrix.Translation(-Vector((chair_center.x, chair_center.y, 0))))
        chair_offset = Vector((chair_center.x - desk_center.x, chair_center.y - desk_center.y, 0))
        hide = ('Door', 'porteManteau', 'handle')
        for obj in meshes:
            if obj is grid or obj in chairs or any(h in obj.name for h in hide):
                bpy.data.objects.remove(obj, do_unlink=True)
                continue
            obj.name = 'Room ' + obj.name.split('|')[0][:40]
            near = [v.co.x < -3.2 for v in obj.data.vertices]
            if near and any(near):
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                doomed = [f for f in bm.faces if all(v.co.x < -3.2 for v in f.verts)]
                if len(doomed) == len(bm.faces):
                    bm.free()
                    bpy.data.objects.remove(obj, do_unlink=True)
                    continue
                bmesh.ops.delete(bm, geom=doomed, context='FACES')
                bm.to_mesh(obj.data)
                bm.free()
            if any(m and 'godray' in m.name.lower() for m in obj.data.materials):
                obj['godray'] = True
            self.room_objects.append(obj)
            for mat in obj.data.materials:
                if mat and any(k in mat.name.lower() for k in ('wall', 'ceilling', 'ceiling')):
                    mat.use_backface_culling = True
        self.teacher_desk = next(o for o in self.room_objects if 'teacherDesk' in o.name)
        self.desks, self.chairs = [], []
        for lane, x in (('A', ROW_X), ('B', LANE_B_X)):
            for i, y in enumerate(DESK_Y):
                d = self.link(f'Desk{lane}{i + 1}', desk_mesh)
                d.location = (x, y, 0)
                c = self.link(f'Chair{lane}{i + 1}', chair_mesh)
                c.location = Vector((x, y, 0)) + chair_offset
                (self.desks if lane == 'A' else self.room_objects).append(d)
                (self.chairs if lane == 'A' else self.room_objects).append(c)
                if lane == 'B':
                    d['lane_b'] = c['lane_b'] = True
        self.compare_desk = self.link('CompareDesk', desk_mesh)
        self.compare_desk.location = COMPARE_DESK
        self.compare_chair = self.link('CompareChair', chair_mesh)
        self.compare_chair.location = COMPARE_DESK + chair_offset
        self.room_objects += self.desks + self.chairs + [self.compare_desk, self.compare_chair]
        # Teacher tray: a shallow brass dish whose rim can glow.
        rim = self.emission('Tray rim glow', (1.0, 0.72, 0.3), 0.0, alpha=False)
        dish = bpy.data.materials.new('Tray brass')
        dish.use_nodes = True
        p = dish.node_tree.nodes.get('Principled BSDF')
        p.inputs['Base Color'].default_value = (0.55, 0.42, 0.22, 1)
        p.inputs['Metallic'].default_value = 0.9
        p.inputs['Roughness'].default_value = 0.35
        self.tray = self.cylinder('TeacherTray', 0.2, 0.02, dish, TRAY - Vector((0, 0, 0.0)))
        bpy.ops.mesh.primitive_torus_add(major_radius=0.2, minor_radius=0.012, location=TRAY + Vector((0, 0, 0.012)))
        self.tray_rim = bpy.context.object
        self.tray_rim.name = 'TeacherTray rim'
        self.tray_rim.data.materials.append(rim)
        self.tray_glow = rim.node_tree.nodes['Emission'].inputs['Strength']
        self.room_objects += [self.tray, self.tray_rim]
        for obj in self.room_objects:
            if obj.get('godray'):
                continue  # volumetric light shafts keep their own blending
            for mat in obj.data.materials:
                socket = self.fade(mat)
                if socket is not None and socket not in [s for s, _ in self.fade_sockets]:
                    self.fade_sockets.append((socket, 'room'))
        # Light: ceiling panels, warm window sun and a soft fill from the open side.
        for x in (-1.58, 1.54):
            for y in (2.6, -2.48, 0.05):
                d = bpy.data.lights.new('Ceiling panel', 'AREA')
                d.energy = 420
                d.size = 1.2
                d.color = (1.0, 0.96, 0.9)
                o = self.link('Ceiling panel', d)
                o.location = (x, y, 3.25)
                self.room_lights.append((d, 420))
        sun = bpy.data.lights.new('Window sun', 'SUN')
        sun.energy = 3.2
        sun.color = (1.0, 0.86, 0.66)
        so = self.link('Window sun', sun)
        so.rotation_euler = (math.radians(55), 0, math.radians(-90))
        self.room_lights.append((sun, 3.2))
        fill = bpy.data.lights.new('Aisle fill', 'AREA')
        fill.energy = 380
        fill.size = 4
        fo = self.link('Aisle fill', fill)
        fo.location = (-5.5, 0.3, 2.6)
        fo.rotation_euler = (Vector((0, 0.3, 1.0)) - fo.location).to_track_quat('-Z', 'Y').to_euler()
        self.room_lights.append((fill, 380))

    def build_white_card(self):
        """A camera-attached white card for the sun → classroom whiteout (no text)."""
        mat = self.emission('Whiteout', (1.0, 1.0, 1.0), 1.0)
        self.white_fade = mat.node_tree.nodes['Mix Shader'].inputs[0]
        bpy.ops.mesh.primitive_plane_add(size=1.0)
        card = bpy.context.object
        card.name = 'Whiteout card'
        card.data.materials.append(mat)
        card.parent = self.camera
        card.location = (0, 0, -0.12)
        card.scale = (0.3, 0.3, 1)
        self.white_card = card

    def light_transition(self, st, pos, tgt, lens):
        """Return camera pose, exposure and white-card opacity for the planned whiteout."""
        kind, e, total = st['light_transition'], st['beat_elapsed'], st['beat_seconds']
        if kind == 'sun_whiteout':
            q = smoother((e - (total - 1.3)) / 1.3)
            core = STAR_C + Vector((-2.0, -3.0, 2.5))
            pos = pos.lerp(core + (pos - core).normalized() * 4.0, q)
            tgt = tgt.lerp(core, q)
            return pos, tgt, lens, 7.0 * q * q, smoother((e - (total - 0.45)) / 0.45)
        if kind == 'window_reveal':
            window = Vector((3.95, 2.39, 2.05))
            near = Vector((1.3, 1.55, 1.5))
            q = smoother((e - 0.45) / 1.0)
            pos, tgt, lens = near.lerp(pos, q), window.lerp(tgt, q), lerp(28, lens, q)
            return pos, tgt, lens, 6.0 * (1 - smooth(e / 1.25)), 1 - smooth(e / 0.45)
        return pos, tgt, lens, 0.0, 0.0

    def stack_point(self, x, y):
        return Vector((x, y, 0)) + STACK_OFFSET

    # ---------- coin lanes ----------
    def build_lanes(self):
        pts_a = [self.stack_point(ROW_X, y) for y in DESK_Y]
        jars_a = [Vector((ROW_X, y, 0)) + JAR_OFFSET for y in DESK_Y]
        pts_b = [self.stack_point(LANE_B_X, y) for y in DESK_Y]
        jars_b = [Vector((LANE_B_X, y, 0)) + JAR_OFFSET for y in DESK_Y]
        tray_point = Vector((TRAY.x, TRAY.y, 0)) + Vector((0.06, 0, TRAY.z + 0.012 - DESK_TOP))
        self.tray_point = tray_point
        self.lane_a = CoinLane(self, 'CoinStack', 72, pts_a, jars_a, tray=tray_point)
        self.lane_b = CoinLane(self, 'LaneBStack', 0, pts_b, jars_b)
        self.lane_m = CoinLane(self, 'MarkedStack', 72, pts_a, jars_a, tray=tray_point, blue=True)
        self.lane_f = CoinLane(self, 'FinalStack', 72, pts_a, jars_a, tray=tray_point)
        bal = tray_point + BALANCE_OFFSET
        self.lane_bal = CoinLane(self, 'BalanceStack', 8, [bal, bal], [bal, bal + Vector((0, -0.2, 0))], steps=1)
        cd = COMPARE_DESK
        big, small = cd + Vector((-0.22, 0.12, 0)), cd + Vector((-0.22, -0.16, 0))
        self.lane_big = CoinLane(self, 'CompareBig', 40, [big] * 6, [big + Vector((0.3, 0.0, 0))] * 6, steps=5)
        self.lane_small = CoinLane(self, 'CompareSmall', 4, [small] * 6, [small + Vector((0.3, 0.0, 0))] * 6, steps=5)
        self.lanes = [self.lane_a, self.lane_b, self.lane_m, self.lane_f, self.lane_bal, self.lane_big, self.lane_small]
        # Translucent record of each stack height (trail).
        ghost = self.glassy('Ghost stack', (1.0, 0.62, 0.25), 0.3, emission=0.25)
        self.ghost_fade = self.fade(ghost)
        self.ghosts = []
        for lane, pts, start in ((self.lane_a, pts_a, 72), (self.lane_b, pts_b, 0)):
            vals = sequence_values(start)
            row = []
            for j, p in enumerate(pts):
                g = self.cylinder(f'{lane.name} ghost {j + 1}', COIN_DIAMETER / 2 * 0.98, 1.0, ghost, p)
                g['value'] = vals[j]
                row.append(g)
            self.ghosts.append((lane, row))
        ring = self.emission('Level ring', (1.0, 0.8, 0.35), 3.0)
        self.level_fade = ring.node_tree.nodes['Mix Shader'].inputs[0]
        bpy.ops.mesh.primitive_torus_add(major_radius=0.34, minor_radius=0.006,
                                         location=cd + Vector((-0.22, -0.02, DESK_TOP + SOURCE * self.coin_th)))
        self.level_ring = bpy.context.object
        self.level_ring.name = 'LevelRing'
        self.level_ring.scale = (0.75, 1.0, 1.0)
        self.level_ring.data.materials.append(ring)

    # ---------- gas slabs and beams ----------
    def tube(self, name, stations, mat, axis_offset=Vector((0, 0, 0)), segments=28):
        """A beam along -y. stations: list of (y, radius)."""
        bm = bmesh.new()
        rings = []
        for y, r in stations:
            ring = [bm.verts.new((axis_offset.x + r * math.cos(a), y, axis_offset.z + r * math.sin(a)))
                    for a in (math.tau * i / segments for i in range(segments))]
            rings.append(ring)
        for r0, r1 in zip(rings, rings[1:]):
            for i in range(segments):
                bm.faces.new((r0[i], r0[(i + 1) % segments], r1[(i + 1) % segments], r1[i]))
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for p in mesh.polygons:
            p.use_smooth = True
        obj = self.link(name, mesh)
        mesh.materials.append(mat)
        return obj

    def beam_material(self, name, color, strength):
        """Emission beam revealed along -y from its start by a moving threshold."""
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        tc = nodes.new('ShaderNodeTexCoord')
        sep = nodes.new('ShaderNodeSeparateXYZ')
        links.new(tc.outputs['Object'], sep.inputs[0])
        reveal = nodes.new('ShaderNodeMath')
        reveal.operation = 'GREATER_THAN'
        reveal.inputs[1].default_value = -1e6
        links.new(sep.outputs['Y'], reveal.inputs[0])
        amount = nodes.new('ShaderNodeMath')
        amount.operation = 'MULTIPLY'
        amount.inputs[1].default_value = 1.0
        links.new(reveal.outputs[0], amount.inputs[0])
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*color, 1)
        em.inputs['Strength'].default_value = strength
        tr = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        links.new(amount.outputs[0], mix.inputs[0])
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(em.outputs[0], mix.inputs[2])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(mix.outputs[0], out.inputs['Surface'])
        mat.surface_render_method = 'BLENDED'
        return mat, reveal.inputs[1], amount.inputs[1]

    def beam_stations(self, start, slabs_y, entry_y, exit_y):
        rows = beam_intensities(start)
        st = [(entry_y, beam_radius(start))]
        for (y, t), (i_in, lost, out) in zip(slabs_y, rows):
            st += [(y + t / 2, beam_radius(i_in)), (y, beam_radius(lost)), (y - t / 2, beam_radius(out))]
        st.append((exit_y, beam_radius(rows[-1][2])))
        return st

    def build_atmosphere(self):
        self.column = self.link('GasColumn', None)
        self.column_pivot = Vector((ROW_X, 0.75, BEAM_Z))
        self.column.location = self.column_pivot
        self.slabs = []
        self.slab_sockets = []
        slabs_y = []
        for i, (y, t) in enumerate(zip(DESK_Y, SLAB_T)):
            mat = self.glassy(f'Gas slab {i + 1}', (1.0, 0.36, 0.06), 0.0, emission=1.6)
            bpy.ops.mesh.primitive_cube_add(size=1.0)
            slab = bpy.context.object
            slab.name = f'GasSlab{i + 1}'
            slab.dimensions = (1.15, t, 1.15)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            slab.data.materials.append(mat)
            slab.parent = self.column
            slab.location = Vector((ROW_X, y, BEAM_Z)) - self.column_pivot
            self.slabs.append(slab)
            # thinner slabs are denser so each slab removes the same half
            self.slab_sockets.append((mat.node_tree.nodes['Mix Shader'].inputs[0], min(0.55, 0.05 / t)))
            slabs_y.append((y - self.column_pivot.y, t))
        entry, exit_ = 4.65 - self.column_pivot.y, TRAY.y + 0.25 - self.column_pivot.y
        self.beam_mat, self.beam_reveal, self.beam_alpha = self.beam_material('Light beam', (1.0, 0.5, 0.08), 2.2)
        self.beam = self.tube('LightBeam', self.beam_stations(72, slabs_y, entry, exit_), self.beam_mat)
        self.beam.parent = self.column
        self.beam_range = (entry, exit_)
        bright_mat, self.bright_reveal, self.bright_alpha = self.beam_material('Bright beam', (1.0, 0.58, 0.12), 2.4)
        dim_mat, self.dim_reveal, self.dim_alpha = self.beam_material('Dim beam', (1.0, 0.42, 0.06), 1.8)
        self.bright = self.tube('BrightBeam', self.beam_stations(24, slabs_y, entry, exit_), bright_mat, Vector((0.33, 0, 0)))
        self.dim = self.tube('DimBeam', self.beam_stations(1, slabs_y, entry, exit_), dim_mat, Vector((-0.33, 0, 0)))
        for o in (self.bright, self.dim):
            o.parent = self.column
        hoop_mat = self.emission('Source hoop', (1.0, 0.85, 0.4), 6.0)
        self.hoop_fade = hoop_mat.node_tree.nodes['Mix Shader'].inputs[0]
        bpy.ops.mesh.primitive_torus_add(major_radius=beam_radius(SOURCE) + 0.03, minor_radius=0.011,
                                         rotation=(math.pi / 2, 0, 0))
        self.hoop = bpy.context.object
        self.hoop.name = 'SourceHoop'
        self.hoop.data.materials.append(hoop_mat)
        self.hoop.parent = self.column
        self.hoop.location = Vector((0, exit_ + 0.18, 0))
        # Photon exchange inside slab 4.
        out_mat = self.emission('Photon out', (1.0, 0.7, 0.3), 7.0)
        in_mat = self.emission('Photon in', (1.0, 0.95, 0.7), 8.0)
        self.photons = []
        for i in range(36):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=0.022)
            p = bpy.context.object
            p.name = f'Photon {"out" if i % 2 else "in"} {i:02d}'
            p.data.materials.append(out_mat if i % 2 else in_mat)
            p.parent = self.column
            self.photons.append(p)
        slice_mat = self.glassy('Thin slice', (1.0, 0.95, 0.85), 0.22, emission=0.6)
        self.slice_fade = self.fade(slice_mat)
        self.slices = []
        for i in range(2):
            bpy.ops.mesh.primitive_circle_add(vertices=48, radius=0.55, fill_type='NGON', rotation=(math.pi / 2, 0, 0))
            s = bpy.context.object
            s.name = f'ThinSlice {i + 1}'
            s.data.materials.append(slice_mat)
            s.parent = self.column
            self.slices.append(s)
        tick_mat = self.emission('Ticks', (0.85, 0.92, 1.0), 2.5)
        self.tick_fade = tick_mat.node_tree.nodes['Mix Shader'].inputs[0]
        self.ticks = []
        self.meter_y = [4.35 - 0.6 * i - self.column_pivot.y for i in range(13)]
        self.optical_y = [y for y, _ in slabs_y]
        for i in range(13):
            t = self.cylinder(f'Tick {i + 1}', 0.014, 0.34, tick_mat)
            t.parent = self.column
            self.ticks.append(t)
        ghost_mat = self.glassy('Desk ghost', (0.8, 0.9, 1.0), 0.0, emission=1.2)
        self.desk_ghost_fade = ghost_mat.node_tree.nodes['Mix Shader'].inputs[0]
        self.desk_ghosts = []
        for i, (y, _) in enumerate(slabs_y):
            g = self.link(f'DeskGhost{i + 1}', self.desks[0].data.copy())
            g.data.materials.clear()
            g.data.materials.append(ghost_mat)
            g.parent = self.column
            g.location = Vector((-0.85, y, -BEAM_Z))
            g.scale = (0.5, 0.5, 0.5)
            self.desk_ghosts.append(g)
        obs_mat = bpy.data.materials.new('Observer lens')
        obs_mat.use_nodes = True
        pb = obs_mat.node_tree.nodes.get('Principled BSDF')
        pb.inputs['Base Color'].default_value = (0.03, 0.04, 0.06, 1)
        pb.inputs['Metallic'].default_value = 0.8
        pb.inputs['Roughness'].default_value = 0.15
        self.observer_fade = self.fade(obs_mat)
        self.observer = self.cylinder('Observer', 0.14, 0.12, obs_mat, (TRAY.x, TRAY.y - 0.05, BEAM_Z), axis='Y')
        self.observer_parts = [self.observer]

    # ---------- star ----------
    def build_star(self):
        surface = self.star('Sun', 0, 0, STAR_R, (1.0, 0.58, 0.2))
        surface.location = STAR_C
        for node in surface.data.materials[0].node_tree.nodes:
            if node.type == 'MATH' and node.operation == 'MULTIPLY_ADD':
                node.inputs[1].default_value = -1.4   # stronger limb darkening
                node.inputs[2].default_value = 3.4    # brighter photosphere
        halo = bpy.data.objects.get('Sun glow')
        if halo is not None:
            bpy.data.objects.remove(halo, do_unlink=True)
        self.sun = surface
        self.sun_surface_fade = self.fade(surface.data.materials[0])
        interior = bpy.data.materials.new('Star interior')
        interior.use_nodes = True
        nodes, links = interior.node_tree.nodes, interior.node_tree.links
        nodes.clear()
        tc = nodes.new('ShaderNodeTexCoord')
        length = nodes.new('ShaderNodeVectorMath')
        length.operation = 'LENGTH'
        links.new(tc.outputs['Object'], length.inputs[0])
        norm = nodes.new('ShaderNodeMath')
        norm.operation = 'DIVIDE'
        norm.inputs[1].default_value = STAR_R
        links.new(length.outputs['Value'], norm.inputs[0])
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.interpolation = 'CONSTANT'
        stops = [(0.0, (1.0, 0.92, 0.6)), (0.3, (1.0, 0.75, 0.25)), (0.5, (1.0, 0.55, 0.1)),
                 (0.7, (0.95, 0.38, 0.05)), (0.85, (0.85, 0.24, 0.03)), (0.93, (0.7, 0.15, 0.02))]
        els = ramp.color_ramp.elements
        els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1)
        els[1].position, els[1].color = stops[1][0], (*stops[1][1], 1)
        for pos, col in stops[2:]:
            e = els.new(pos)
            e.color = (*col, 1)
        links.new(norm.outputs[0], ramp.inputs[0])
        # thin τ≈1 shell glow: 1 - |r - 0.955| / 0.013
        d = nodes.new('ShaderNodeMath'); d.operation = 'SUBTRACT'; d.inputs[1].default_value = TAU_SHELL
        a = nodes.new('ShaderNodeMath'); a.operation = 'ABSOLUTE'
        m = nodes.new('ShaderNodeMath'); m.operation = 'DIVIDE'; m.inputs[1].default_value = 0.013
        inv = nodes.new('ShaderNodeMath'); inv.operation = 'SUBTRACT'; inv.inputs[0].default_value = 1.0
        clamp = nodes.new('ShaderNodeMath'); clamp.operation = 'MAXIMUM'; clamp.inputs[1].default_value = 0.0
        amt = nodes.new('ShaderNodeMath'); amt.operation = 'MULTIPLY'; amt.inputs[1].default_value = 0.0
        strength = nodes.new('ShaderNodeMath'); strength.operation = 'MULTIPLY_ADD'
        strength.inputs[1].default_value = 6.0; strength.inputs[2].default_value = 1.1
        links.new(norm.outputs[0], d.inputs[0]); links.new(d.outputs[0], a.inputs[0])
        links.new(a.outputs[0], m.inputs[0]); links.new(m.outputs[0], inv.inputs[1])
        links.new(inv.outputs[0], clamp.inputs[0]); links.new(clamp.outputs[0], amt.inputs[0])
        links.new(amt.outputs[0], strength.inputs[0])
        em = nodes.new('ShaderNodeEmission')
        links.new(ramp.outputs['Color'], em.inputs['Color'])
        links.new(strength.outputs[0], em.inputs['Strength'])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(em.outputs[0], out.inputs['Surface'])
        self.tau_shell_amount = amt.inputs[1]
        self.star_interior_fade = self.fade(interior)
        # Upper front quarter (x<0, z>centre) is removed by an animated cutter.
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        cutter = bpy.context.object
        cutter.name = 'StarCutter'
        cutter.dimensions = (STAR_R + 2, 2 * STAR_R + 4, STAR_R + 2)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        cutter.data.materials.append(interior)
        cutter.hide_render = True
        cutter.display_type = 'WIRE'
        self.cutter = cutter
        surface.data.materials.append(interior)
        mod = surface.modifiers.new('Quarter cut', 'BOOLEAN')
        mod.operation = 'DIFFERENCE'
        mod.solver = 'EXACT'
        mod.object = cutter
        mod.material_mode = 'TRANSFER'
        self.cut_open = Vector((-(STAR_R + 2) / 2, 0, (STAR_R + 2) / 2)) + STAR_C
        # Star beams sit just in front of the exposed vertical face.
        off = Vector((-0.25, 0, 0.25))
        self.star_gold_deep_mat, _, self.gold_deep_alpha = self.beam_material('Star gold deep', (1.0, 0.62, 0.15), 3.0)
        self.star_gold_out_mat, _, self.gold_out_alpha = self.beam_material('Star gold outer', (1.0, 0.62, 0.15), 3.0)
        self.star_blue_mat, self.blue_reveal, self.blue_beam_alpha = self.beam_material('Star blue', (0.15, 0.4, 1.0), 4.0)
        R = STAR_R
        self.gold_deep = self.tube('StarBeamDeep', [(0, 0.35), (-0.72 * R, 0.35)], self.star_gold_deep_mat, off)
        self.gold_out = self.tube('StarBeamOuter', [(-0.72 * R, 0.35), (-1.35 * R, 0.35)], self.star_gold_out_mat, off)
        self.blue_light = self.tube('BlueLight', [(0, 0.4), (-0.3 * R, 0.34), (-0.5 * R, 0.2), (-0.62 * R, 0.02)],
                                    self.star_blue_mat, off)
        for o in (self.gold_deep, self.gold_out, self.blue_light):
            o.location = STAR_C
        pulse_mat = self.emission('Star pulse', (1.0, 0.95, 0.8), 14.0)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.7)
        self.pulse = bpy.context.object
        self.pulse.name = 'StarPhoton'
        self.pulse.data.materials.append(pulse_mat)
        self.pulse_fade = pulse_mat.node_tree.nodes['Mix Shader'].inputs[0]
        esc_mat = self.emission('Escape photon', (1.0, 0.9, 0.6), 10.0)
        self.escape_mat = esc_mat
        self.escapes = []
        for i in range(100):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=8, ring_count=5, radius=0.07)
            p = bpy.context.object
            p.name = f'EscapePhoton {i:03d}'
            p.data.materials.append(esc_mat)
            self.escapes.append(p)
        self.star_offset = off

    # ---------- camera ----------
    def slab_y(self, i):
        return DESK_Y[i]

    def shot_pose(self, shot, st, u, t):
        C, R = STAR_C, STAR_R
        e = smooth(u)
        drift = Vector((0, 0.07 * math.sin(t * 0.35), 0.03 * math.sin(t * 0.27)))
        stack = self.focus_stack(st)
        if shot == 'star_whole':
            d = lerp(165, 138, e)
            return C + Vector((-0.78, -0.6, 0.12)).normalized() * d, C.copy(), 50
        if shot == 'star_wedge':
            ahead = lerp(3, 12, e) if st['deep_marked'] < 0.001 else 8
            return C + Vector((-52, -54, 36)), C + Vector((0, -ahead, 2)), 50
        if shot == 'star_surface':
            P = C + Vector((0, -TAU_SHELL * R, 0))
            return P + Vector((-lerp(7.5, 5.8, e), -2.6, 2.4)), P + Vector((0, 0.9, 0.2)), 40
        if shot == 'row_wide':
            return Vector((-8.2, 0.35, 2.45)) + drift, Vector((0, 0.35, 0.95)), 35
        if shot == 'row_track_to_teacher':
            y = lerp(DESK_Y[0], TRAY.y, e)
            return Vector((-3.4, y + 0.9, 1.75)), Vector((0, y - 0.4, 0.95)), 32
        if shot == 'desk_close':
            base = stack + Vector((0, 0, DESK_TOP))
            return base + Vector((-1.55, 0.75, 0.62)), base + Vector((0.05, -0.12, 0.28)), 40
        if shot == 'row_medium':
            y = stack.y
            return Vector((-4.6, y + 1.3, 2.05)), Vector((0, y - 0.8, 0.95)), 32
        if shot == 'balance_close':
            b = self.tray_point + BALANCE_OFFSET * 0.5 + Vector((0, 0, DESK_TOP))
            return b + Vector((-1.45, 0.85, 0.62)), b + Vector((0, 0, 0.08)), 40
        if shot == 'two_lane':
            return Vector((-6.2, 1.9, 3.0)) + drift, Vector((0.6, -0.1, 0.9)), 32
        if shot == 'two_lane_high':
            h = lerp(3.2, 5.6, e)
            return Vector((-4.3, 3.6, h)), Vector((0.6, -0.9, 0.85)), 30
        if shot == 'compare_close':
            c = COMPARE_DESK + Vector((-0.22, -0.02, DESK_TOP + 0.15))
            back = lerp(1.0, 1.5, e) if st['compare'] > 1.0 else 1.0
            return c + Vector((-1.35, 0.35, 0.45)) * back, c, 40
        if shot == 'slab_wide':
            return Vector((-7.6, 0.4, 2.1)) + drift, Vector((0, 0.4, BEAM_Z)), 35
        if shot == 'slab_close':
            y = self.slab_y(3)
            return Vector((-lerp(3.1, 2.3, e), y + 0.55, 1.5)), Vector((0, y, BEAM_Z)), 38
        if shot == 'slice_close':
            y = self.slab_y(3)
            return Vector((-lerp(1.9, 2.4, e), y + 0.35, 1.32)), Vector((0, y, BEAM_Z)), 40
        if shot == 'two_beam':
            y = lerp(1.3, -0.6, e)
            return Vector((-6.8, y, 2.2)) + drift, Vector((0, y, BEAM_Z)), 35
        raise ValueError(shot)

    def focus_stack(self, st):
        if st['final_run'] > 0.001:
            return self.lane_f.root.location.copy()
        if st['marked'] > 0.001:
            return self.lane_m.root.location.copy()
        return self.lane_a.root.location.copy()

    def camera_pose(self, st, t):
        pos, tgt, lens = self.shot_pose(st['shot'], st, st['shot_u'], t)
        if st['prev_shot'] != st['shot']:
            p0, t0, l0 = self.shot_pose(st['prev_shot'], st, 1.0, t)
            seconds = max(0.4, min(2.8, (pos - p0).length / 4.0))
            q = smoother(st['shot_elapsed'] / seconds)
            pos, tgt, lens = p0.lerp(pos, q), t0.lerp(tgt, q), lerp(l0, lens, q)
        return pos, tgt, lens

    # ---------- per frame ----------
    def sample(self, frame):
        st = state_at(self.job, frame)
        entry = self.job['canonical_state_cache'][frame]
        t = entry['simulation_time']
        self.state = {k: round(v, 6) if isinstance(v, float) else v for k, v in st.items()}
        room = st['classroom']
        # Daylight sky outside the windows while the classroom is on screen; deep navy in space.
        bg = self.scene.world.node_tree.nodes['Background']
        navy, sky = Vector((0.012, 0.02, 0.045)), Vector((0.78, 0.86, 1.0))
        bg.inputs['Color'].default_value = (*navy.lerp(sky, room), 1)
        bg.inputs['Strength'].default_value = lerp(0.6, 1.6, room)
        opaque = smooth(min(1.0, room * 1.6))  # the room turns solid early, so crossfades stay short
        for socket, _ in self.fade_sockets:
            socket.default_value = opaque
        for obj in self.room_objects:
            lane_b = obj.get('lane_b', False)
            obj.hide_render = bool(room < 0.01 or (lane_b and st['b_visible'] < 0.01)) or bool(obj.get('godray') and room < 0.99)
            if lane_b:
                obj.scale = (1, 1, max(1e-4, min(1.0, st['b_visible'] * 1.4)))
        cshow = min(1.0, st['compare'] * 3) * room
        self.compare_desk.hide_render = self.compare_chair.hide_render = cshow < 0.01
        self.compare_desk.scale = self.compare_chair.scale = (1, 1, max(1e-4, cshow))
        for light, energy in self.room_lights:
            light.energy = energy * room
        self.tray_glow.default_value = 4.0 * st['tray_glow'] * room
        # lanes
        retired = st['retired_a']
        a_vis = room * (1 - retired)
        self.lane_a.evaluate(st['a_progress'], a_vis if st['a_start'] > 0 else 0.0)
        self.lane_b.evaluate(st['b_progress'], room * st['b_visible'])
        self.lane_m.evaluate(st['m_progress'], room * min(1.0, st['marked']) * (1 - min(1.0, st['final_run'] * 4)))
        self.blue_alpha.default_value = self.lane_m.blue_alpha(st['m_progress'])
        self.lane_f.evaluate(st['final_run'] * STEPS, room * min(1.0, st['final_run'] * 6))
        self.lane_bal.evaluate(st['balance'], room * min(1.0, st['balance'] * 4) * (1 - retired))
        compare = st['compare']
        steps = compare if compare <= 1 else 1 + (compare - 1) * 4
        cvis = room * min(1.0, compare * 4)
        self.lane_big.evaluate(steps, cvis)
        self.lane_small.evaluate(steps, cvis)
        self.level_fade.default_value = st['level_ring'] * room
        self.level_ring.hide_render = st['level_ring'] * room < 0.01
        # ghosts appear once the stack has left each desk
        self.ghost_fade.default_value = st['trail'] * room
        for lane, row in self.ghosts:
            t_lane = st['a_progress'] if lane is self.lane_a else st['b_progress']
            vis = (1 - retired) if lane is self.lane_a else st['b_visible']
            for j, g in enumerate(row):
                shown = smooth((t_lane - j - 0.05) * 4) if j < len(row) - 1 else smooth((t_lane - (STEPS - 1) - 0.86) * 8)
                h = max(1e-4, g['value'] * self.coin_th)
                on = st['trail'] * room * vis * shown
                g.hide_render = on < 0.01
                g.scale = (1, 1, h * max(1e-3, min(1.0, on * 2)))
                g.location.z = DESK_TOP + h * max(1e-3, min(1.0, on * 2)) / 2
        self.update_atmosphere(st, t)
        self.update_star(st, t)
        pos, tgt, lens = self.camera_pose(st, t)
        pos, tgt, lens, exposure, white = self.light_transition(st, pos, tgt, lens)
        self.scene.view_settings.exposure = exposure
        self.white_fade.default_value = white
        self.white_card.hide_render = white < 0.001
        self.state['exposure'] = round(exposure, 6)
        self.state['whiteout'] = round(white, 6)
        self.camera.location = pos
        self.camera.rotation_euler = (tgt - pos).to_track_quat('-Z', 'Y').to_euler()
        self.camera.data.lens = lens
        tracked = [self.camera, self.sun, self.column, self.beam, self.hoop, *(l.root for l in self.lanes)]
        return entry, tracked

    def update_atmosphere(self, st, t):
        atm = st['atmosphere']
        merge = min(st['star'], 1.0)  # follows the star even while hidden, so it never jumps
        target = STAR_C + Vector((0, -TAU_SHELL * STAR_R + 2.2, 0)) + self.star_offset
        self.column.location = self.column_pivot.lerp(target, smooth(merge))
        self.column.scale = (lerp(1.0, 0.42, smooth(merge)),) * 3
        for slab, (socket, alpha) in zip(self.slabs, self.slab_sockets):
            socket.default_value = alpha * atm
            slab.hide_render = atm < 0.01
        span = self.beam_range[0] - self.beam_range[1]
        self.beam_reveal.default_value = self.beam_range[0] - span * st['beam'] - 0.001
        self.beam_alpha.default_value = min(1.0, st['beam'] * 3) * atm
        self.beam.hide_render = st['beam'] * atm < 0.01
        dual = st['dual_beam']
        reach = self.beam_range[0] - (0.34 if dual <= 1 else 0.34 + (span - 0.34) * (dual - 1)) * 1.0
        if dual <= 1:
            reach = self.beam_range[0] - (1.4 * dual)
        self.bright_reveal.default_value = self.dim_reveal.default_value = reach
        for alpha, obj in ((self.bright_alpha, self.bright), (self.dim_alpha, self.dim)):
            alpha.default_value = min(1.0, dual * 2) * atm
            obj.hide_render = dual * atm < 0.01
        self.hoop_fade.default_value = st['hoop'] * atm
        self.hoop.hide_render = st['hoop'] * atm < 0.01
        # exchange particles in slab 4 (or the thin slice)
        y4 = self.slab_y(3) - self.column_pivot.y
        sl = st['slice']
        half = SLAB_T[3] / 2 if sl < 0.01 else 0.06 * max(1.0, sl)
        active = max(st['exchange'], min(1.0, sl * 2), st['ratio_demo'])
        count = len(self.photons) if sl < 0.01 else int(round(8 * max(1.0, sl) + 2 * (sl - 1 if sl > 1 else 0)))
        for i, p in enumerate(self.photons):
            phase = (t / 1.6 + golden(i)) % 1.0
            ang = golden(i * 7) * math.tau
            dy = (golden(i * 3) - 0.5) * 2 * half
            if i % 2:  # absorbed / scattered out of the beam
                r = lerp(0.05, 0.7, phase)
            else:      # emitted by the gas and joining the beam
                r = lerp(0.6, 0.04, phase)
            p.location = Vector((r * math.cos(ang), y4 + dy, r * math.sin(ang)))
            vis = active * atm * (1 if i < count else 0) * math.sin(math.pi * phase)
            p.scale = (max(1e-4, vis),) * 3
            p.hide_render = vis < 0.01
        for k, s in enumerate(self.slices):
            s.location = Vector((0, y4 + (half if k == 0 else -half), 0))
            s.hide_render = sl * atm < 0.01
        self.slice_fade.default_value = min(1.0, sl) * atm
        in_tick_beat = st['beat_index'] in self.tick_beats()
        ticks = st['ticks'] if in_tick_beat else 1.0
        leaving = 1.0 if in_tick_beat else 1 - smooth(st['beat_elapsed'] / 0.6)
        self.tick_fade.default_value = atm * leaving if (in_tick_beat or st['beat_index'] - 1 in self.tick_beats()) else 0.0
        for i, tk in enumerate(self.ticks):
            y0 = self.meter_y[i]
            y1 = self.optical_y[i] if i < len(self.optical_y) else self.optical_y[-1] - 0.3 * (i - 7)
            tk.location = Vector((-0.78, lerp(y0, y1, smooth(ticks)), -0.45))
            extra = 1 - smooth(ticks) if i >= len(self.optical_y) else 1.0
            tk.scale = (1, 1, max(1e-4, extra))
            tk.hide_render = self.tick_fade.default_value * extra < 0.01
        self.desk_ghost_fade.default_value = 0.35 * st['student_ghost'] * atm
        for g in self.desk_ghosts:
            g.hide_render = st['student_ghost'] * atm < 0.01
        obs = max(atm, 0.0) * (1 - min(1.0, st['star'] * 2))
        self.observer_fade.default_value = obs
        self.observer.hide_render = obs < 0.01

    def tick_beats(self):
        if not hasattr(self, '_tick_beats'):
            self._tick_beats = {i for i, b in enumerate(self.job['timeline'])
                                if 'ticks' in b['controller_options'].get('state', {})}
        return self._tick_beats

    def update_star(self, st, t):
        star = st['star']
        visible = star > 0.001
        self.sun.hide_render = not visible
        self.sun_surface_fade.default_value = star
        self.star_interior_fade.default_value = star
        w = smooth(st['wedge'])
        self.cutter.location = self.cut_open + Vector((-(1 - w) * (STAR_R + 4), 0, 0))
        self.sun.rotation_euler.z = 0.0  # a rotating texture would shift the cut; keep the cut fixed
        self.tau_shell_amount.default_value = st['tau_shell']
        deep, marked = st['deep_light'] * star, st['deep_marked']
        blue_on = min(1.0, marked) * max(0.0, min(1.0, 2 - marked))
        self.gold_deep_alpha.default_value = deep * (1 - min(1.0, marked))
        self.gold_out_alpha.default_value = deep
        self.blue_beam_alpha.default_value = deep * blue_on
        self.blue_reveal.default_value = -1e6
        for obj, val in ((self.gold_deep, self.gold_deep_alpha.default_value),
                         (self.gold_out, deep), (self.blue_light, self.blue_beam_alpha.default_value)):
            obj.hide_render = val < 0.01 or not visible
        # a single photon pulse running outward along the beam
        phase = (t / 2.6) % 1.0
        colour_in = marked < 0.01
        self.pulse.location = STAR_C + self.star_offset + Vector((0, -phase * 1.3 * STAR_R, 0))
        on = deep * (1 if colour_in or phase > 0.72 / 1.3 else 0) * math.sin(math.pi * phase)
        if st['shot'] == 'star_surface':
            on = 0.0  # the pulse passes the lens in the close-up and reads as a grey ball
        self.pulse_fade.default_value = on
        self.pulse.hide_render = on < 0.01
        # escape photons from the τ≈1 shell
        esc = st['escape']
        start = STAR_C + self.star_offset + Vector((0, -TAU_SHELL * STAR_R, 0))
        for i, p in enumerate(self.escapes):
            delay = golden(i * 11) * 0.35
            q = max(0.0, min(1.0, (esc - delay) / 0.65))
            escapes = golden(i * 5 + 3) < 0.37
            stop = (0.12 + 0.8 * golden(i * 13)) * (1 - TAU_SHELL) * STAR_R
            travel = q * (4.5 if escapes else stop)
            spread = Vector(((golden(i * 17) - 0.5) * 0.6, 0, (golden(i * 19) - 0.5) * 0.6)) * (1 + travel * 0.15)
            p.location = start + Vector((0, -travel, 0)) + spread
            fade = 1.0 if escapes else 1 - smooth((q - 0.8) / 0.2)
            vis = star * st['tau_shell'] * (1 if esc > 0.001 else 0) * fade
            p.scale = (max(1e-4, vis),) * 3
            p.hide_render = vis < 0.01

    def extra_state(self):
        return dict(self.state)

    def bake(self):
        from bpy_extras import anim_utils
        self.sample(0)
        movers = [self.camera, self.column, *(l.root for l in self.lanes), self.cutter, self.pulse]
        for lane in self.lanes:
            movers += lane.coins
        for obj in movers:
            for prop in ('location', 'scale', 'rotation_euler'):
                obj.keyframe_insert(data_path=prop, frame=1)
        self.camera.data.keyframe_insert(data_path='lens', frame=1)
        owners = [*movers, self.camera.data]
        channels = []
        for owner in dict.fromkeys(owners):
            ad = getattr(owner, 'animation_data', None)
            if not ad or not ad.action:
                continue
            bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
            for curve in bag.fcurves:
                value = owner.path_resolve(curve.data_path)
                channels.append((curve, owner, curve.data_path, curve.array_index, hasattr(value, '__len__')))
        count = self.job['duration_frames']
        stride = max(1, count // 600)  # editable .blend keeps every n-th frame
        frames = list(range(0, count, stride))
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
