"""Shared native worker for run sources and new settings-aware builtin runs."""
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

# Both installed runtime and copied snapshots keep the same relative layout.
ROOT = Path(__file__).resolve().parent
HELPERS = ROOT.parent if (ROOT.parent / 'callout.py').is_file() else ROOT.parent / 'blender_renderer'
sys.path[:0] = [str(ROOT.parent), str(HELPERS)]
sys.dont_write_bytecode = True
import bpy
from mathutils import Vector
from render_runtime.source_loader import load_source_symbol
from render_runtime.blender_settings import apply_blender_settings
from continuity_capture import capture_continuity
from animated_materials import animated_sockets
from callout_math import select_sample_frames


def canonical_frame(index, output_fps, canonical_fps, duration):
    return min(duration - 1, index * canonical_fps // output_fps)


def capture_gallery_continuity(gallery):
    state = capture_continuity(gallery.scene, gallery.camera)
    for logical, obj in getattr(gallery, 'objects', {}).items():
        for group in ('actors', 'paths'):
            if obj.name in state[group]:
                state[group][logical] = state[group][obj.name]
    return state


def build_gallery(job):
    if 'run_source' in job:
        source = job['run_source']
        factory = load_source_symbol(Path(source['snapshot_root']), source['entrypoint'], namespace=source['namespace'])
    else:
        source = job['builtin_source']
        sys.path.insert(0, source['root'])
        factory = getattr(importlib.import_module(source['module']), source['symbol'])
    gallery = factory(job)
    gallery.bake()
    applied = apply_blender_settings(gallery.scene, job['blender_settings'])
    return gallery, applied


def main():
    path = Path(sys.argv[sys.argv.index('--') + 1])
    job = json.loads(path.read_text())
    output = Path(job['output_directory'])
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    gallery, applied = build_gallery(job)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'scene.blend'))
    initialized=time.perf_counter()
    frames=[];samples=[]
    selected=select_sample_frames(job)
    for index in selected:
        frame=canonical_frame(index,job['output']['fps'],job['canonical_fps'],job['duration_frames'])
        gallery.scene.frame_set(frame+1)
        entry,tracked=gallery.sample(frame)
        gallery.scene.view_layers[0].update()
        callouts=getattr(gallery,'callouts',None)
        if callouts is not None:callouts.update(frame);gallery.scene.view_layers[0].update()
        target=output/f'frame-{index:06d}.png'
        gallery.scene.render.filepath=str(target)
        applied = apply_blender_settings(gallery.scene, job['blender_settings'])
        bpy.ops.render.render(write_still=True,scene=gallery.scene.name)
        actual={obj.name:{'location':list(obj.location),'scale':list(obj.scale),'rotation':list(obj.rotation_euler)} for obj in tracked}
        for obj in tracked:
            sockets=animated_sockets(obj)
            if sockets:actual[obj.name]['animated_material_values']=[socket.default_value for socket in sockets]
            if obj.get('animate_curve_reveal'):actual[obj.name]['curve_reveal']=obj.data.bevel_factor_end
            if 'spectrum_color' in obj:
                actual[obj.name]['line_color']=list(obj.data.materials[0].node_tree.nodes.get('Emission').inputs['Color'].default_value)
        actual['orthographic_scale']=gallery.camera.data.ortho_scale
        if hasattr(gallery,'extra_state'):actual['gallery_state']=gallery.extra_state()
        fingerprint=hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest()
        sample=dict(canonical_frame=frame,simulation_time=entry['simulation_time'],
            continuity=capture_gallery_continuity(gallery),
            visible_layers=[job['scene_graph']],geometry_operation_keys=list(entry['active_beat_ids']),
            camera=dict(position=list(gallery.camera.location),target=list(gallery.camera.location+gallery.camera.rotation_euler.to_quaternion()@Vector((0,0,-10)))),
            entity_scales={obj.name:float(obj.scale.x) for obj in tracked},state_fingerprint=fingerprint)
        if callouts is not None:sample['callouts']=callouts.screen_state()
        if hasattr(gallery,'graph_text_state'):sample['graph_text']=gallery.graph_text_state()
        samples.append(sample)
        frames.append(str(target))
    ended=time.perf_counter()
    if gallery.scene.render.engine!='BLENDER_EEVEE':raise RuntimeError('Unexpected render engine')
    report=dict(blender_settings=applied,renderer_version=job['renderer_version'],sequence_id=job['sequence_id'],frame_count=len(frames),width=job['output']['width'],height=job['output']['height'],
        frames=frames,sample_frames=selected,state_samples=samples,
        browser_version='not-applicable; Blender '+bpy.app.version_string,capture_method='blender_native_render',
        capture_timing_mode='legacy_combined',capture_transport_bytes=0,
        backend=dict(requested='blender_eevee',actual='blender_eevee',vendor='Blender',renderer=bpy.app.version_string+' BLENDER_EEVEE'),
        timings=dict(frame_count=len(frames),initialization_ms=(initialized-started)*1000,
            render_ms=(ended-initialized)*1000,capture_ms=0,write_ms=0,total_ms=(ended-started)*1000))
    (output/'frame-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
