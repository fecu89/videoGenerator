"""Blender executable entrypoint; produces PNGs, actual state and editable .blend."""
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
from mathutils import Vector
from spectra import canonical_frame, validate_job
from scene import SpectralGallery
from continuity_capture import capture_continuity
from animated_materials import animated_sockets
from callout_math import select_sample_frames


def main():
    path=Path(sys.argv[sys.argv.index('--')+1])
    job=json.loads(path.read_text())
    gallery_class=SpectralGallery
    if job.get('scene_graph')=='typhoon-beta-blender-v1':
        from typhoon_beta import TyphoonBetaGallery
        from typhoon_beta_math import validate_job as validate_typhoon_beta_job
        validate_typhoon_beta_job(job);gallery_class=TyphoonBetaGallery
    elif job.get('scene_graph')=='saturn-rings-blender-v1':
        from saturn_rings import SaturnRingsGallery
        from saturn_rings_math import validate_job as validate_saturn_rings_job
        validate_saturn_rings_job(job);gallery_class=SaturnRingsGallery
    elif job.get('scene_graph')=='adiabatic-expansion-blender-v1':
        from adiabatic import AdiabaticGallery
        from adiabatic_math import validate_job as validate_adiabatic_job
        validate_adiabatic_job(job);gallery_class=AdiabaticGallery
    elif job.get('scene_graph')=='virial-galaxy-story-blender-v1':
        from virial_galaxy import VirialGalaxyStoryGallery
        from virial_galaxy_math import validate_job as validate_virial_galaxy_job
        validate_virial_galaxy_job(job);gallery_class=VirialGalaxyStoryGallery
    elif job.get('scene_graph')=='transfer-equation-story-blender-v1':
        from transfer_equation_story import TransferEquationStoryGallery
        from transfer_equation_story_math import validate_job as validate_transfer_equation_job
        validate_transfer_equation_job(job);gallery_class=TransferEquationStoryGallery
    elif job.get('scene_graph')=='optical-depth-story-blender-v2':
        from optical_depth_story import OpticalDepthStoryGallery
        from optical_depth_story_math import validate_job as validate_optical_depth_story_job
        validate_optical_depth_story_job(job);gallery_class=OpticalDepthStoryGallery
    elif job.get('scene_graph')=='optical-depth-blender-v1':
        from optical_depth import OpticalDepthGallery
        from optical_depth_math import validate_job as validate_optical_depth_job
        validate_optical_depth_job(job);gallery_class=OpticalDepthGallery
    elif job.get('scene_graph')=='phantom-jam-blender-v1':
        from phantom_jam import PhantomJamGallery
        from phantom_jam_math import validate_job as validate_phantom_jam_job
        validate_phantom_jam_job(job);gallery_class=PhantomJamGallery
    elif job.get('scene_graph')=='coriolis-story-blender-v1':
        from coriolis_story import CoriolisStoryGallery
        from coriolis_story_math import validate_job as validate_coriolis_story_job
        validate_coriolis_story_job(job);gallery_class=CoriolisStoryGallery
    elif job.get('scene_graph')=='vorticity-story-blender-v2':
        from vorticity_story import VorticityStoryGallery
        from vorticity_story_math import validate_job as validate_vorticity_story_job
        validate_vorticity_story_job(job);gallery_class=VorticityStoryGallery
    elif job.get('scene_graph')=='bonding-flow-blender-v2':
        from bonding_flow import BondingFlowGallery
        from bonding_math import validate_job as validate_bonding_job
        validate_bonding_job(job);gallery_class=BondingFlowGallery
    elif job.get('scene_graph')=='bonding-blender-v1':
        from bonding import BondingGallery
        from bonding_math import validate_job as validate_bonding_job
        validate_bonding_job(job);gallery_class=BondingGallery
    elif job.get('scene_graph')=='vorticity-blender-v1':
        from vorticity import VorticityGallery
        from vorticity_math import validate_job as validate_vorticity_job
        validate_vorticity_job(job);gallery_class=VorticityGallery
    elif job.get('scene_graph')=='sun-earth-moon-blender-v1':
        from eclipse import EclipseGallery
        from eclipse_math import validate_job as validate_eclipse_job
        validate_eclipse_job(job);gallery_class=EclipseGallery
    else:validate_job(job)
    output=Path(job['output_directory']);output.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    gallery=gallery_class(job)
    gallery.bake()
    bpy.ops.wm.save_as_mainfile(filepath=str(output/'scene.blend'))
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
            continuity=capture_continuity(gallery.scene,gallery.camera),
            visible_layers=[job['scene_graph']],geometry_operation_keys=list(entry['active_beat_ids']),
            camera=dict(position=list(gallery.camera.location),target=list(gallery.camera.location+gallery.camera.rotation_euler.to_quaternion()@Vector((0,0,-10)))),
            entity_scales={obj.name:float(obj.scale.x) for obj in tracked},state_fingerprint=fingerprint)
        if callouts is not None:sample['callouts']=callouts.screen_state()
        if hasattr(gallery,'graph_text_state'):sample['graph_text']=gallery.graph_text_state()
        samples.append(sample)
        frames.append(str(target))
    ended=time.perf_counter()
    if gallery.scene.render.engine!='BLENDER_EEVEE':raise RuntimeError('Unexpected render engine')
    report=dict(sequence_id=job['sequence_id'],frame_count=len(frames),width=job['output']['width'],height=job['output']['height'],
        frames=frames,sample_frames=selected,state_samples=samples,
        browser_version='not-applicable; Blender '+bpy.app.version_string,capture_method='blender_native_render',
        capture_timing_mode='legacy_combined',capture_transport_bytes=0,
        backend=dict(requested='blender_eevee',actual='blender_eevee',vendor='Blender',renderer=bpy.app.version_string+' BLENDER_EEVEE'),
        timings=dict(frame_count=len(frames),initialization_ms=(initialized-started)*1000,
            render_ms=(ended-initialized)*1000,capture_ms=0,write_ms=0,total_ms=(ended-started)*1000))
    (output/'frame-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
