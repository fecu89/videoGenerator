import math

import pytest

from video_harness.blender_backend import renderer_modules, validate_blender_job
from video_harness.blender_renderer.optical_depth_math import (
    direct_count, state_at, transmission,
)


def job():
    timeline = [dict(beat_id=f'B{i+1:02}', start_frame=i*60, end_frame=(i+1)*60,
                     controller='optical-depth', controller_options={'state': state})
                for i,state in enumerate(({'tau':1.,'length':8.},
                                           {'tau':1.,'length':4.,'camera_width':22.},
                                           {'tau':3.,'length':9.}))]
    return dict(scene_graph='optical-depth-blender-v1', frame_count=180,
                duration_frames=180, canonical_fps=30, camera_transition_seconds=.4,
                output=dict(width=384,height=216,fps=30), timeline=timeline,
                canonical_state_cache=[dict(canonical_frame=i,simulation_time=i/30,
                                           active_beat_ids=[f'B{i//60+1:02}']) for i in range(180)])


def test_exponential_direct_transmission_and_equal_layers():
    assert [direct_count(t) for t in (0,1,2,3)] == [100,37,14,5]
    assert transmission(2) == pytest.approx(transmission(1)**2)
    assert transmission(3) == pytest.approx(transmission(1)**3)
    assert transmission(.1) > .9 and transmission(4) < .02
    assert abs(transmission(1-1e-6)-transmission(1+1e-6)) < 1e-6


def test_equal_optical_depth_at_double_density_half_length():
    j=job(); long=state_at(j,59); short=state_at(j,119)
    assert short['length'] == long['length']/2
    assert short['tau']/short['length'] == 2*long['tau']/long['length']
    assert short['direct_fraction'] == long['direct_fraction']


def test_random_access_and_boundary_continuity():
    j=job(); ordered=[state_at(j,i) for i in range(180)]
    assert [state_at(j,i) for i in reversed(range(180))] == list(reversed(ordered))
    assert state_at(j,60) == state_at(j,59)
    assert state_at(j,120) == state_at(j,119)
    assert state_at(j,72)['camera_width'] == 22  # saved .4-second transition
    assert state_at(j,71)['camera_width'] > 22


def test_registered_backend_and_invalid_physics():
    assert renderer_modules('optical-depth-blender-v1') == ('optical_depth','OpticalDepthGallery')
    validate_blender_job(job())
    for bad in (-1, math.inf, math.nan):
        with pytest.raises(ValueError):
            transmission(bad)
    j=job();j['timeline'][0]['controller_options']['state']['length']=0
    with pytest.raises(ValueError,match='positive'):
        validate_blender_job(j)
