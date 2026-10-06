import math
import pytest
from video_harness.blender_renderer import phantom_jam_math as pm
from video_harness.blender_backend import renderer_modules

# Beat frame edges of the approved 17-beat plan (30 fps).
EDGES = [0, 352, 717, 1109, 1443, 1818, 2265, 2568, 2922, 3048, 3350, 3694, 4039, 4305, 4602, 4888, 5245, 5496]


def timeline():
    return [dict(beat_id=f'B{n:02d}', start_frame=a, end_frame=b, controller=pm.CONTROLLER,
                 controller_options={'beat_number': n})
            for n, (a, b) in enumerate(zip(EDGES, EDGES[1:]), 1)]


@pytest.fixture(scope='module')
def story():
    return pm.Story(timeline(), 30)


def clusters(x, v):
    order = sorted(range(pm.RING_N), key=lambda i: x[i] % pm.RING_L)
    slow = [v[i] < 1 for i in order]
    return sum(1 for k in range(pm.RING_N) if slow[k] and not slow[k - 1])


def test_ring_starts_near_30_kmh_and_car_a_slows_to_about_28(story):
    assert pm.optimal_velocity(pm.RING_L / pm.RING_N) * 3.6 == pytest.approx(30.2, abs=.3)
    dip = min(story.ring.sample(story.tau_main + d)[1][pm.CAR_A] for d in (.5, 1, 1.5, 2, 2.5, 3))
    assert dip * 3.6 == pytest.approx(28, abs=.6)


def test_first_stop_is_several_cars_behind_car_a_and_lands_on_scene_9(story):
    behind = (pm.CAR_A - story.stopper) % pm.RING_N
    assert 5 <= behind <= 14
    frame = round(story.f_stop * 30)
    assert story.tau[frame] == pytest.approx(story.tau_stop, abs=.05)


def test_a_single_jam_of_about_five_cars_drifts_backward(story):
    for frame in range(story.start[11], story.end[15], 45):
        x, v, _ = story.ring.sample(story.tau[frame])
        assert clusters(x, v) == 1
        assert 4 <= sum(s < .5 for s in v) <= 8
    a0 = story.jam_angle(story.tau[story.start[12] + 60])
    a1 = story.jam_angle(story.tau[story.end[12] - 30])
    assert pm.wrap(a1 - a0) < -math.radians(60)   # clockwise, against the cars


def test_the_autonomous_car_is_not_car_a_and_dissolves_the_jam(story):
    assert story.av_car != pm.CAR_A
    x, v, _ = story.ring.sample(story.tau[story.end[16] - 1])
    mean = sum(v) / len(v)
    assert max(abs(s - mean) for s in v) < .2
    assert story.av_speed * 3.6 == pytest.approx(24, abs=2)


def test_model_time_is_monotone_and_only_jumps_at_the_cut(story):
    frames = sorted(story.tau)
    steps = [story.tau[b] - story.tau[a] for a, b in zip(frames, frames[1:]) if b == a + 1]
    assert min(steps) > 0
    jump = story.tau[story.start[11]] - story.tau[story.start[11] - 1]
    assert jump > 100
    assert max(s for s in steps if s < 10) < 4 / 30


def test_camera_is_continuous_across_continuous_boundaries(story):
    cuts = {story.start[3], story.start[11], story.start[17]}
    previous = story.state(0)['camera'][0]
    for frame in range(1, story.total):
        eye = story.state(frame)['camera'][0]
        if frame not in cuts:
            assert math.dist(previous, eye) < 4.0, frame
        previous = eye


def test_state_is_independent_of_evaluation_order(story):
    frames = [5000, 300, 3500, 1200]
    expected = {f: story.state(f)['camera'] for f in frames}
    assert {f: story.state(f)['camera'] for f in reversed(frames)} == expected
    assert renderer_modules(pm.GRAPH) == ('phantom_jam', 'PhantomJamGallery')


def test_rejects_wrong_beat_order():
    job = dict(scene_graph=pm.GRAPH, frame_count=10, duration_frames=EDGES[16], canonical_fps=30,
               output=dict(width=384, height=216, fps=12), timeline=timeline()[:16])
    with pytest.raises(ValueError, match='17-beat'):
        pm.validate_job(job)
