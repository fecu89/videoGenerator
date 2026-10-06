"""Camera choreography and normalized direct transmission for optical-depth v2."""
import math
try:
    from .optical_depth_math import transmission, free_depth, direct_count, smooth
except ImportError:
    from optical_depth_math import transmission, free_depth, direct_count, smooth

GRAPH='optical-depth-story-blender-v2'
CONTROLLER='optical-depth-story'
DEFAULTS=dict(tau=1.,distance=16.,particles=0.,section=0.,graph=0.,solar_zoom=0.,
              camera=[10.,-18.,7.],target=[-4.,0.,3.],lens=38.)

def mix(a,b,p):
    if isinstance(a,list):return [mix(x,y,p) for x,y in zip(a,b)]
    return a+(b-a)*p


def transition_at(job, frame):
    """Brightness-matched edits are explicitly owned by their planned beats."""
    beat = next(b for b in job['timeline'] if b['start_frame'] <= frame < b['end_frame'])
    opts = beat['controller_options'];kind = opts.get('light_transition', '')
    seconds = (frame - beat['start_frame']) / job['canonical_fps']
    duration = (beat['end_frame'] - beat['start_frame'] - 1) / job['canonical_fps']
    progress = min(1., max(0., seconds / max(duration, 1e-6)))
    flash = 0.
    zoom = 0.
    if kind == 'solar_to_lamp':
        zoom = smooth((seconds - (duration - 1.2)) / 1.2)
        flash = smooth((seconds - (duration - .38)) / .38)
    elif kind in ('lamp_reveal', 'sun_pullback'):
        flash = 1. - smooth(seconds / .3)
    elif kind == 'lamp_to_sun':
        flash = smooth((seconds - (duration - .65)) / .65)
    return dict(kind=kind, progress=progress, seconds=seconds, flash=flash, zoom=zoom)

def state_at(job,frame):
    values={k:list(v) if isinstance(v,list) else v for k,v in DEFAULTS.items()}
    first=job['timeline'][0]['controller_options']
    if first.get('environment') in ('sun','street'):
        for key in ('camera','target','lens'):
            if key in first.get('state',{}):values[key]=first['state'][key]
    for beat in job['timeline']:
        if frame < beat['start_frame']:break
        opts=beat['controller_options'];target={**values,**opts.get('state',{})}
        progress=smooth((frame-beat['start_frame'])/max(1,beat['end_frame']-beat['start_frame']-1))
        move=opts.get('camera_move_seconds',job.get('camera_transition_seconds',.4))
        cp=smooth((frame-beat['start_frame'])/max(1,move*job['canonical_fps']))
        previous=values
        values={k:mix(previous[k],target[k],cp if k in ('camera','target','lens','graph') else progress) for k in DEFAULTS}
        # Interpolate viewing angles for the 180-degree turn, rather than
        # aiming through the camera and pitching into the sky halfway through.
        if 0 < cp < 1:
            vectors=[[pose['target'][i]-pose['camera'][i] for i in range(3)] for pose in (previous,target)]
            yaw=[math.atan2(d[1],d[0]) for d in vectors]
            pitch=[math.atan2(d[2],math.hypot(d[0],d[1])) for d in vectors]
            angle=yaw[0]+((yaw[1]-yaw[0]+math.pi)%(2*math.pi)-math.pi)*cp
            elevation=mix(pitch[0],pitch[1],cp)
            distance=mix(math.sqrt(sum(x*x for x in vectors[0])),math.sqrt(sum(x*x for x in vectors[1])),cp)
            direction=[math.cos(elevation)*math.cos(angle),math.cos(elevation)*math.sin(angle),math.sin(elevation)]
            values['target']=[values['camera'][i]+direction[i]*distance for i in range(3)]
        if frame<beat['end_frame']:break
    values['transmission']=transmission(values['tau'])
    values['extinction_per_length']=values['tau']/values['distance']
    tr=transition_at(job,frame)
    if tr['kind']=='solar_to_lamp' and tr['zoom']>0:
        values['camera']=mix(values['camera'],[0.,2.72,1.],tr['zoom'])
        values['target']=mix(values['target'],[0.,3.,1.],tr['zoom'])
    elif tr['kind']=='lamp_reveal':
        p=smooth(tr['seconds']/3.3)
        values['camera']=mix([-7.8,-.65,5.5],first['state']['camera'],p)
        values['target']=mix([-8.,0.,5.5],first['state']['target'],p)
    elif tr['kind']=='sun_pullback':
        p=smooth(tr['progress'])
        values['camera']=mix([0.,-3.08,100.],[0.,-23.,103.],p)
        values['target']=[0.,0.,100.];values['lens']=42.;values['graph']=0.
    elif tr['kind']=='lamp_to_sun':
        values['graph']*=1.-smooth(tr['seconds']/.45)
    return values

def validate_job(job):
    if job.get('scene_graph')!=GRAPH:raise ValueError('unsupported optical-depth story graph')
    try:from .spectra import validate_job as validate_cache
    except ImportError:from spectra import validate_job as validate_cache
    proxy={**job,'scene_graph':'stellar-spectra-blender-v1','timeline':[{**b,'controller':'spectra-intro'} for b in job['timeline']]}
    validate_cache(proxy)
    for b in job['timeline']:
        if b['controller']!=CONTROLLER:raise ValueError('unknown optical-depth story controller')
        st=b['controller_options'].get('state',{})
        if set(st)-set(DEFAULTS):raise ValueError('unknown state field')
        for k,v in st.items():
            values=v if isinstance(v,list) else [v]
            if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):raise ValueError('nonfinite state')
            if k in ('camera','target') and (not isinstance(v,list) or len(v)!=3):raise ValueError('camera/target must be vec3')
        transmission(st.get('tau',1))
        if st.get('distance',16)<=3.82 or st.get('lens',38)<=0:raise ValueError('path distance must exceed lamp-to-eye height; lens must be positive')
        if any(not 0<=st.get(k,0)<=1 for k in ('particles','section','graph','solar_zoom')):raise ValueError('invalid blend')
