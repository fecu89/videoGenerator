"""Continuous Blender film for the Saturn ring narration.

All motion comes from saturn_rings_math (pure functions of the frame). This
file builds the world once and applies each frame's transforms and opacities.
Textures are prepared from the Saturn model in the run's asset folder; rocks
come from the asteroid models there. No words are drawn.
"""
import math
import random
from pathlib import Path
import bmesh
import bpy
from mathutils import Euler, Matrix, Vector
from scene import SpectralGallery
from callout import CalloutLayer, labels_from_job
import saturn_rings_math as sm

GOLD = (1.0, .70, .12)
RED = (1.0, .22, .08)
TEAL = (.10, .90, .80)
LIMIT = (.45, .85, 1.0)
ICE_LIGHT = (.93, .96, 1.0)
ICE_DARK = (.42, .47, .55)
ROCK_LIGHT = (.50, .43, .36)
ROCK_DARK = (.14, .12, .10)


class SaturnRingsGallery(SpectralGallery):
    # ----- materials ---------------------------------------------------------------
    def image(self, name):
        img = bpy.data.images.load(str(Path(self.job['style']['asset_root']) / name), check_existing=True)
        img.pack()
        return img

    def fadeable(self, mat, key, blended=False):
        """Insert an opacity mix before the output and register its socket under key."""
        mat.surface_render_method = 'BLENDED' if blended else 'DITHERED'
        mat.use_transparent_shadow = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        out = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL')
        source = out.inputs['Surface'].links[0].from_socket
        clear = nodes.new('ShaderNodeBsdfTransparent')
        mixer = nodes.new('ShaderNodeMixShader')
        mixer.name = 'Animated opacity'
        links.new(clear.outputs[0], mixer.inputs[1])
        links.new(source, mixer.inputs[2])
        links.new(mixer.outputs[0], out.inputs['Surface'])
        mixer.inputs[0].default_value = 1.0
        self.sockets.setdefault(key, []).append(mixer.inputs[0])
        return mat

    def emission(self, name, color, strength, key, blended=False):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value = (*color, 1)
        emit.inputs['Strength'].default_value = strength
        out = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(emit.outputs[0], out.inputs['Surface'])
        return self.fadeable(mat, key, blended)

    def rock_material(self, name, source_image, light, dark, key):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Roughness'].default_value = .62
        if source_image is not None:
            tex = nodes.new('ShaderNodeTexImage')
            tex.image = source_image
            ramp = nodes.new('ShaderNodeValToRGB')
            ramp.color_ramp.elements[0].position = .10
            ramp.color_ramp.elements[0].color = (*dark, 1)
            ramp.color_ramp.elements[1].position = .70
            ramp.color_ramp.elements[1].color = (*light, 1)
            links.new(tex.outputs['Color'], ramp.inputs[0])
            links.new(ramp.outputs[0], bsdf.inputs['Base Color'])
        else:
            bsdf.inputs['Base Color'].default_value = (*light, 1)
        return self.fadeable(mat, key)

    def moon_material(self, name, key, tint=(1.0, 1.0, 1.0)):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Roughness'].default_value = .8
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = self.moon_image
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = .15
        ramp.color_ramp.elements[0].color = (.30 * tint[0], .32 * tint[1], .36 * tint[2], 1)
        ramp.color_ramp.elements[1].position = .85
        ramp.color_ramp.elements[1].color = (.96 * tint[0], .97 * tint[1], 1.0 * tint[2], 1)
        links.new(tex.outputs['Color'], ramp.inputs[0])
        links.new(ramp.outputs[0], bsdf.inputs['Base Color'])
        return self.fadeable(mat, key)

    # ----- meshes ------------------------------------------------------------------
    def mesh_object(self, name, build, material=None):
        bm = bmesh.new()
        build(bm)
        data = bpy.data.meshes.new(name)
        bm.to_mesh(data)
        bm.free()
        obj = self.link(name, data)
        if material is not None:
            data.materials.append(material)
        return obj

    def annulus(self, name, r0, r1, material, segments=256):
        """Flat ring whose U coordinate runs from the inner to the outer edge."""
        def build(bm):
            uv = bm.loops.layers.uv.new('UVMap')
            inner = [bm.verts.new(sm.polar(r0, math.tau * k / segments)) for k in range(segments)]
            outer = [bm.verts.new(sm.polar(r1, math.tau * k / segments)) for k in range(segments)]
            for k in range(segments):
                j = (k + 1) % segments
                face = bm.faces.new((inner[k], outer[k], outer[j], inner[j]))
                for loop, u in zip(face.loops, (0.0, 1.0, 1.0, 0.0)):
                    loop[uv].uv = (u, .5)
        return self.mesh_object(name, build, material)

    def sphere(self, name, radius, material, segments=64, rings=32):
        def build(bm):
            bm.loops.layers.uv.new('UVMap')
            bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius, calc_uvs=True)
            for face in bm.faces:
                face.smooth = True
        return self.mesh_object(name, build, material)

    # ----- world -------------------------------------------------------------------
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
        stars.inputs['Scale'].default_value = 260.0
        near = nodes.new('ShaderNodeMath')
        near.operation = 'LESS_THAN'
        near.inputs[1].default_value = .045
        bright = nodes.new('ShaderNodeMath')
        bright.operation = 'MULTIPLY'
        glow = nodes.new('ShaderNodeMath')
        glow.operation = 'MULTIPLY_ADD'
        glow.inputs[1].default_value = 1.6
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
        seen.inputs['A'].default_value = .05
        links.new(path.outputs['Is Camera Ray'], seen.inputs['Factor'])
        links.new(glow.outputs[0], seen.inputs['B'])
        links.new(seen.outputs['Result'], bg.inputs['Strength'])
        bg.inputs['Color'].default_value = (.75, .82, 1.0, 1)
        for obj in list(scene.objects):
            if obj.type == 'LIGHT':
                bpy.data.objects.remove(obj, do_unlink=True)
        sun = bpy.data.lights.new('Sun', 'SUN')
        sun.energy = 3.5
        sun.angle = math.radians(.6)
        self.sun = self.link('Sun', sun)
        toward = Vector(sm.sun_direction())
        self.sun.rotation_euler = (-toward).to_track_quat('-Z', 'Y').to_euler()
        # Soft light from the unlit side so night hemispheres stay readable; it casts no shadows.
        fill = bpy.data.lights.new('Fill', 'SUN')
        fill.energy = .45
        fill.use_shadow = False
        self.fill = self.link('Fill', fill)
        back = Vector((math.cos(math.radians(200)) * .8, math.sin(math.radians(200)) * .8, .6))
        self.fill.rotation_euler = (-back).to_track_quat('-Z', 'Y').to_euler()
        cam = self.camera.data
        cam.type = 'PERSP'
        cam.sensor_width = 36
        cam.clip_start = .004
        cam.clip_end = 400

    def build_planet(self):
        mat = bpy.data.materials.new('Saturn surface')
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Roughness'].default_value = .9
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = self.image('saturn_bands.png')
        links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        links.new(tex.outputs['Color'], bsdf.inputs['Emission Color'])
        bsdf.inputs['Emission Strength'].default_value = .025
        self.objs['Saturn'] = self.sphere('Saturn', 1.0, mat, 128, 64)

        r0, r1 = (float(v) for v in (Path(self.job['style']['asset_root']) / 'ring_profile.txt').read_text().split())
        ring = bpy.data.materials.new('Ring particles (far view)')
        ring.use_nodes = True
        nodes, links = ring.node_tree.nodes, ring.node_tree.links
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Roughness'].default_value = 1.0
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = self.image('ring_profile.png')
        tex.extension = 'EXTEND'
        fade = nodes.new('ShaderNodeMath')
        fade.name = 'Ring opacity'
        fade.operation = 'MULTIPLY'
        fade.inputs[1].default_value = 1.0
        links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        links.new(tex.outputs['Color'], bsdf.inputs['Emission Color'])
        bsdf.inputs['Emission Strength'].default_value = .06
        links.new(tex.outputs['Alpha'], fade.inputs[0])
        links.new(fade.outputs[0], bsdf.inputs['Alpha'])
        ring.surface_render_method = 'BLENDED'
        ring.use_transparent_shadow = True
        ring.use_backface_culling = False
        self.sockets['RingDisk'] = [fade.inputs[1]]
        self.objs['RingDisk'] = self.annulus('RingDisk', r0, r1, ring)

        glow = self.emission('Ring highlight', (1.0, .93, .78), 1.3, 'RingGlow', blended=True)
        self.objs['RingGlow'] = self.annulus('RingGlow', sm.RING_IN, sm.RING_OUT, glow)
        self.objs['RingGlow'].visible_shadow = False

        dust = bpy.data.materials.new('Early disk')
        dust.use_nodes = True
        nodes, links = dust.node_tree.nodes, dust.node_tree.links
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (.78, .64, .46, 1)
        bsdf.inputs['Roughness'].default_value = 1.0
        bsdf.inputs['Emission Color'].default_value = (.78, .64, .46, 1)
        bsdf.inputs['Emission Strength'].default_value = .10
        coord = nodes.new('ShaderNodeTexCoord')
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 2.6
        noise.inputs['Detail'].default_value = 5.0
        uv = nodes.new('ShaderNodeSeparateXYZ')
        edge = nodes.new('ShaderNodeMath')          # soft inner and outer edges: 4u(1-u)
        edge.operation = 'MULTIPLY_ADD'
        edge.inputs[1].default_value = -1.0
        edge.inputs[2].default_value = 1.0
        soft = nodes.new('ShaderNodeMath')
        soft.operation = 'MULTIPLY'
        alpha = nodes.new('ShaderNodeMath')
        alpha.operation = 'MULTIPLY'
        gain = nodes.new('ShaderNodeMath')
        gain.operation = 'MULTIPLY'
        gain.inputs[1].default_value = 3.2
        links.new(coord.outputs['Object'], noise.inputs['Vector'])
        links.new(coord.outputs['UV'], uv.inputs[0])
        links.new(uv.outputs['X'], edge.inputs[0])
        links.new(uv.outputs['X'], soft.inputs[0])
        links.new(edge.outputs[0], soft.inputs[1])
        links.new(soft.outputs[0], gain.inputs[0])
        links.new(gain.outputs[0], alpha.inputs[0])
        links.new(noise.outputs['Fac'], alpha.inputs[1])
        links.new(alpha.outputs[0], bsdf.inputs['Alpha'])
        self.fadeable(dust, 'ProtoDisk', blended=True)
        self.objs['ProtoDisk'] = self.annulus('ProtoDisk', 1.15, 3.7, dust)
        self.objs['ProtoDisk'].visible_shadow = False

    def build_limit(self):
        line = self.emission('Roche limit line', LIMIT, 2.4, 'RocheCircle')
        def torus(bm):
            major, minor, seg, tube = sm.ROCHE, .013, 256, 8
            rows = []
            for i in range(seg):
                a = math.tau * i / seg
                rows.append([bm.verts.new(((major + minor * math.cos(math.tau * j / tube)) * math.cos(a),
                                           (major + minor * math.cos(math.tau * j / tube)) * math.sin(a),
                                           minor * math.sin(math.tau * j / tube))) for j in range(tube)])
            for i in range(seg):
                for j in range(tube):
                    bm.faces.new((rows[i][j], rows[(i + 1) % seg][j], rows[(i + 1) % seg][(j + 1) % tube], rows[i][(j + 1) % tube]))
        self.objs['RocheCircle'] = self.mesh_object('RocheCircle', torus, line)
        self.objs['RocheCircle'].visible_shadow = False

        shell = bpy.data.materials.new('Roche limit shell')
        shell.use_nodes = True
        nodes, links = shell.node_tree.nodes, shell.node_tree.links
        nodes.clear()
        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value = (*LIMIT, 1)
        emit.inputs['Strength'].default_value = .9
        clear = nodes.new('ShaderNodeBsdfTransparent')
        rim = nodes.new('ShaderNodeLayerWeight')
        rim.inputs['Blend'].default_value = .35
        amount = nodes.new('ShaderNodeMath')
        amount.name = 'Shell opacity'
        amount.operation = 'MULTIPLY'
        amount.inputs[1].default_value = 0.0
        mixer = nodes.new('ShaderNodeMixShader')
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(rim.outputs['Fresnel'], amount.inputs[0])
        links.new(amount.outputs[0], mixer.inputs[0])
        links.new(clear.outputs[0], mixer.inputs[1])
        links.new(emit.outputs[0], mixer.inputs[2])
        links.new(mixer.outputs[0], out.inputs['Surface'])
        shell.surface_render_method = 'BLENDED'
        shell.use_backface_culling = True
        self.sockets['RocheShell'] = [amount.inputs[1]]
        self.objs['RocheShell'] = self.sphere('RocheShell', sm.ROCHE, shell, 96, 48)
        self.objs['RocheShell'].visible_shadow = False

    # ----- rocks -------------------------------------------------------------------
    def load_templates(self):
        """Unit-size copies of every asteroid mesh, plus light versions for dense strips."""
        root = Path(self.job['style']['asset_root'])
        self.templates = {}
        depsgraph = bpy.context.evaluated_depsgraph_get
        for key, filename in (('pack', 'asteroids_pack_rocky_version.glb'),
                              ('wander', 'wandering_asteroids_of_andromeda.glb'),
                              ('smooth', 'asteroid_low_poly.glb')):
            before = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=str(root / filename))
            imported = [o for o in bpy.data.objects if o not in before]
            bpy.context.view_layer.update()
            rows = []
            for obj in sorted((o for o in imported if o.type == 'MESH'), key=lambda o: o.name):
                data = obj.data.copy()
                data.transform(obj.matrix_world)
                pts = [v.co.copy() for v in data.vertices]
                lo = Vector([min(p[i] for p in pts) for i in range(3)])
                hi = Vector([max(p[i] for p in pts) for i in range(3)])
                data.transform(Matrix.Translation(-(lo + hi) / 2))
                data.transform(Matrix.Scale(1 / max(hi - lo), 4))
                image = None
                source = obj.data.materials[0] if obj.data.materials else None
                if source and source.node_tree:
                    bsdf = next((n for n in source.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                    link = bsdf.inputs['Base Color'].links if bsdf else ()
                    node = link[0].from_node if link else None
                    while node is not None and node.type != 'TEX_IMAGE':
                        node = next((s.links[0].from_node for s in node.inputs if s.links), None)
                    image = node.image if node is not None else None
                    if image is None:
                        image = next((n.image for n in source.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image), None)
                data.materials.clear()
                rows.append(dict(mesh=data, image=image))
            for obj in imported:
                bpy.data.objects.remove(obj, do_unlink=True)
            self.templates[key] = rows
        for key, target in (('pack_light', 260), ('grain', 40)):
            reduced = []
            for row in self.templates['pack']:
                holder = bpy.data.objects.new('decimate holder', row['mesh'])
                bpy.context.scene.collection.objects.link(holder)
                mod = holder.modifiers.new('reduce', 'DECIMATE')
                mod.ratio = target / max(target, len(row['mesh'].vertices))
                data = bpy.data.meshes.new_from_object(holder.evaluated_get(depsgraph()))
                bpy.data.objects.remove(holder, do_unlink=True)
                reduced.append(dict(mesh=data, image=row['image']))
            self.templates[key] = reduced
        for image in {row['image'] for rows in self.templates.values() for row in rows if row['image']}:
            image.pack()

    def rock_set(self, pattern, key, count, pool, dark_every=0):
        """Individually animated rocks sharing fadeable ice (and a few dark rock) materials."""
        mats = {}
        for i in range(count):
            row = pool[i % len(pool)]
            dark = bool(dark_every) and i % dark_every == dark_every - 1
            tag = (id(row['image']), dark)
            if tag not in mats:
                mats[tag] = self.rock_material('%s %s' % (key, 'rock' if dark else 'ice'), row['image'],
                                               ROCK_LIGHT if dark else ICE_LIGHT, ROCK_DARK if dark else ICE_DARK, key)
            data = row['mesh'].copy()
            data.materials.append(mats[tag])
            for poly in data.polygons:
                poly.use_smooth = True
            name = pattern % i
            self.objs[name] = self.link(name, data)

    def build_patch(self):
        """Six radial strips of small ice blocks around the close-view focus."""
        rng = random.Random(20261005)
        pool = self.templates['pack_light']
        image = pool[0]['image']
        ice = self.rock_material('Patch ice', image, ICE_LIGHT, ICE_DARK, 'Patch')
        rock = self.rock_material('Patch rock', image, ROCK_LIGHT, ROCK_DARK, 'Patch')
        for layer in range(sm.N_LAYERS):
            centre = (layer - (sm.N_LAYERS - 1) / 2) * .03
            bm = bmesh.new()
            for _ in range(200):
                x = centre + rng.uniform(-.015, .015)
                y = clamp(rng.gauss(0, .27), -.75, .75)
                z = rng.gauss(0, .0075)
                if abs(x) < .05 and abs(y) < .06 and rng.random() < .75:
                    continue                      # keep the stage for the individually animated rocks
                size = clamp(.0042 * math.exp(rng.gauss(0, .5)), .0018, .013)
                start = len(bm.verts)
                faces = len(bm.faces)
                bm.from_mesh(rng.choice(pool)['mesh'])
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                turn = Euler([rng.uniform(0, math.tau) for _ in range(3)]).to_matrix().to_4x4()
                place = Matrix.Translation(sm.polar(sm.R_FOCUS + x, y / sm.R_FOCUS, z)) @ turn @ Matrix.Scale(size, 4)
                bmesh.ops.transform(bm, matrix=place, verts=bm.verts[start:])
                dark = rng.random() < .13
                for face in bm.faces[faces:]:
                    face.material_index = 1 if dark else 0
                    face.smooth = True
            # fine grains fill the slab between the blocks
            for _ in range(700):
                x = centre + rng.uniform(-.015, .015)
                y = clamp(rng.gauss(0, .22), -.75, .75)
                z = rng.gauss(0, .0085)
                size = rng.uniform(.0003, .0009)
                start = len(bm.verts)
                faces = len(bm.faces)
                bm.from_mesh(rng.choice(self.templates['grain'])['mesh'])
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                turn = Euler([rng.uniform(0, math.tau) for _ in range(3)]).to_matrix().to_4x4()
                place = Matrix.Translation(sm.polar(sm.R_FOCUS + x, y / sm.R_FOCUS, z)) @ turn @ Matrix.Scale(size, 4)
                bmesh.ops.transform(bm, matrix=place, verts=bm.verts[start:])
                for face in bm.faces[faces:]:
                    face.material_index = 0
                    face.smooth = True
            data = bpy.data.meshes.new('Patch%d' % layer)
            bm.to_mesh(data)
            bm.free()
            data.materials.append(ice)
            data.materials.append(rock)
            self.objs['Patch%d' % layer] = self.link('Patch%d' % layer, data)

    def build_bodies(self):
        self.moon_image = self.image('moon_surface.png')
        for name, radius, key in (('MoonA', sm.MOON_R, 'MoonA'), ('MoonT', sm.MOON_R, 'MoonT'),
                                  ('MoonB', .19, 'MoonB'), ('MoonC', .17, 'MoonC'), ('Moonlet', .12, 'Moonlet')):
            self.objs[name] = self.sphere(name, radius, self.moon_material(name + ' surface', key))
        ghost = self.emission('Imagined moon', (.75, .88, 1.0), .55, 'Ghost', blended=True)
        self.objs['Ghost'] = self.sphere('Ghost', .030, ghost, 48, 24)
        self.objs['Ghost'].visible_shadow = False
        big = self.templates['wander'] + self.templates['pack'][:6]
        self.rock_set('Hero%d', 'Hero', sm.N_HERO, self.templates['smooth'] * 3 + self.templates['wander'] + self.templates['pack'][:2])
        self.build_shards()
        self.rock_set('Debris%02d', 'Debris', sm.N_DEBRIS, big, dark_every=4)
        self.rock_set('Out%02d', 'Out', sm.N_OUT, big, dark_every=6)
        self.rock_set('In%02d', 'In', sm.N_IN, big)

    def build_shards(self):
        """Cut one moon into cells that fit together, so the break-up starts from the intact body."""
        from mathutils import Vector as V
        surface = self.moon_material('Shard surface', 'Frag')
        inner = bpy.data.materials.new('Shard interior')
        inner.use_nodes = True
        bsdf = inner.node_tree.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (.50, .56, .66, 1)
        bsdf.inputs['Roughness'].default_value = .7
        self.fadeable(inner, 'Frag')
        seeds = [V(row['p']) * sm.SEED_SPREAD for row in self.story.frag]
        base = bmesh.new()
        base.loops.layers.uv.new('UVMap')
        bmesh.ops.create_uvsphere(base, u_segments=64, v_segments=32, radius=sm.MOON_R, calc_uvs=True)
        for face in base.faces:
            face.smooth = True
        for i, seed in enumerate(seeds):
            bm = base.copy()
            for j, other in enumerate(seeds):
                if i == j or not bm.verts:
                    continue
                cut = bmesh.ops.bisect_plane(bm, geom=[*bm.verts, *bm.edges, *bm.faces], plane_co=(seed + other) / 2,
                                             plane_no=(other - seed).normalized(), clear_outer=True, clear_inner=False)
                edges = [e for e in cut['geom_cut'] if isinstance(e, bmesh.types.BMEdge)]
                if edges:
                    filled = bmesh.ops.triangle_fill(bm, edges=edges, use_beauty=True)
                    for face in (f for f in filled['geom'] if isinstance(f, bmesh.types.BMFace)):
                        face.material_index = 1
                        face.smooth = False
            bmesh.ops.translate(bm, verts=bm.verts, vec=-seed)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            data = bpy.data.meshes.new('Frag%02d' % i)
            bm.to_mesh(data)
            bm.free()
            data.materials.append(surface)
            data.materials.append(inner)
            self.objs['Frag%02d' % i] = self.link('Frag%02d' % i, data)
        base.free()

    def build_arrows(self):
        for name, color, key in (('GNear', GOLD, 'Gravity'), ('GFar', GOLD, 'Gravity'), ('TNear', RED, 'Tide'),
                                 ('TFar', RED, 'Tide'), ('SNear', TEAL, 'Self'), ('SFar', TEAL, 'Self')):
            mat = self.emission(name + ' glow', color, 2.2, key)
            def shaft(bm):
                bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=.022, radius2=.022, depth=1.0,
                                      matrix=Matrix.Translation((.5, 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, 'Y'))
            def head(bm):
                bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=.062, radius2=0.0, depth=sm.HEAD,
                                      matrix=Matrix.Translation((sm.HEAD / 2, 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, 'Y'))
            for part, build in (('Shaft', shaft), ('Head', head)):
                obj = self.mesh_object(name + part, build, mat)
                obj.visible_shadow = False
                self.objs[name + part] = obj

    # ----- build -----------------------------------------------------------------------
    def build(self):
        self.fps = self.job['canonical_fps']
        self.story = sm.Story(self.job['timeline'], self.fps)
        self.scene.name = 'Saturn Rings ' + self.job['sequence_id']
        self.camera.name = 'SaturnRingsCamera'
        self.objs, self.sockets = {}, {}
        self.build_world()
        self.build_planet()
        self.build_limit()
        self.load_templates()
        self.build_patch()
        self.build_bodies()
        self.build_arrows()
        self.animated = [*self.objs.values(), self.camera]
        self.callouts = CalloutLayer(self)
        self.callouts.bind(labels_from_job(self.job), dict(self.objs))

    # ----- per frame -------------------------------------------------------------------
    def sample(self, frame):
        st = self.story.state(frame)
        for name, (location, rotation, scale) in st['xf'].items():
            obj = self.objs[name]
            obj.location = location
            obj.rotation_euler = rotation
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

    # ----- editable keys (bulk; visibility is opacity, never hide_render) -------------------
    def insert_keys(self, frame):
        for obj in self.animated:
            for prop in ('location', 'rotation_euler', 'scale'):
                obj.keyframe_insert(data_path=prop, frame=frame)
        for sockets in self.sockets.values():
            for socket in sockets:
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
        return {'shot': st['shot'], 'moon': st['moon'], 'forces': st['forces'], 'ring': st['ring'],
                'patch': st['patch'], 'opacity': {k: round(v, 5) for k, v in st['op'].items()}}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))
