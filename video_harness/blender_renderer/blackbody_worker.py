"""Render one blackbody shot with native keyframes and frame-state evidence."""
import sys,json,hashlib,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
from blackbody_gallery import BlackbodyGallery

def main():
    job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text());sid=job['scene_id'];count=job['frame_count'];fps=job['fps'];out=Path(job['output_directory']);out.mkdir(parents=True,exist_ok=True)
    gallery=BlackbodyGallery
    if job.get('visual_style')=='presentation_v2':
        from blackbody_presentation import PresentationGallery
        gallery=PresentationGallery
    started=time.perf_counter();g=gallery(sid,job['width'],job['height'],fps,count)
    g.bake(count,fps)
    # Rebase all rotation phases to the global timeline before saving the shot.
    for frame in range(count):
        g.sample(frame/max(1,count-1),job['start_frame']/fps+frame/fps)
        for star,halo,r in g.stars:star.keyframe_insert(data_path='rotation_euler',frame=frame+1)
        if sid==5:g.ray.data.splines[0].points[1].keyframe_insert(data_path='co',frame=frame+1)
    g.font.pack();g.scene.frame_set(1);bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    frames=[];samples=[]
    for frame in range(count):
        g.scene.frame_set(frame+1);p=frame/max(1,count-1);t=(job['start_frame']+frame)/fps;g.sample(p,t)
        target=out/f'frame-{frame:06d}.png';g.scene.render.filepath=str(target);bpy.ops.render.render(write_still=True,scene=g.scene.name)
        state={'camera':list(g.camera.location),'rotation':list(g.camera.rotation_euler),'objects':{o.name:{'position':list(o.location),'rotation':list(o.rotation_euler),'scale':list(o.scale)} for o in g.dynamic},'opacity':[socket.default_value for o,socket in g.fades]}
        fingerprint=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest();frames.append(str(target));samples.append({'canonical_frame':frame,'simulation_time':t,'geometry_operation_keys':[f'blackbody-scene-{sid:02}'],'state_fingerprint':fingerprint,'camera':state['camera']})
    (out/'frame-report.json').write_text(json.dumps({'scene_id':sid,'frame_count':count,'width':job['width'],'height':job['height'],'fps':fps,'backend':{'requested':'blender_eevee','actual':'blender_eevee','version':bpy.app.version_string},'frames':frames,'state_samples':samples,'render_seconds':time.perf_counter()-started},indent=2))
    print('COMPLETE',sid,count,flush=True)
if __name__=='__main__':main()
