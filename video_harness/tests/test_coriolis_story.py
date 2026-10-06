import math
import pytest
from video_harness.blender_renderer import coriolis_story_math as cm
from video_harness.blender_backend import renderer_modules

# Beat lengths (frames) of the approved 23-beat plan.
LENGTHS = [320, 416, 367, 425, 444, 380, 190, 414, 445, 480, 423, 461, 201, 170, 170, 383, 408, 244,
           402, 360, 316, 425, 309]


def timeline():
    beats, cursor = [], 0
    for n, length in enumerate(LENGTHS, 1):
        beats.append(dict(beat_id=f'B{n:02d}', start_frame=cursor, end_frame=cursor + length,
                          controller='coriolis-story', controller_options={'beat_number': n}))
        cursor += length
    return beats


@pytest.fixture(scope='module')
def story():
    return cm.Story(timeline(), 30)


def test_first_flight_turns_the_earth_88_degrees_and_lands_east_of_turkey(story):
    assert story.phi(story.t_arrive) - story.phi(story.t_depart) == pytest.approx(cm.FLIGHT_TURN)
    assert cm.track1(1.0) == pytest.approx((37.57, 38.98))
    assert story.flight1(story.t_arrive) == pytest.approx(1.0)


def test_seoul_faces_the_camera_at_departure(story):
    assert cm.angle_to_front(story.apparent(story.t_depart)) == pytest.approx(cm.SEOUL[1])


def test_second_track_stays_clear_of_the_first(story):
    # At the same latitudes the two ground tracks are far apart in longitude.
    for lat in (40, 50):
        u = (90 - lat) / (90 - cm.SEOUL[0])
        assert abs(story.track2(lat / cm.SECOND_FLIGHT_LAT)[1] - cm.track1(u)[1]) > 25


def test_ground_tracks_bend_right_in_the_north():
    # Southbound from the pole the track drifts west (right of travel).
    assert cm.track1(.5)[1] < cm.SEOUL[1]
    s = cm.Story(timeline(), 30)
    # Northbound from the equator the plane drifts east (right of travel).
    lat, lon = s.track2(1.0)
    assert lat == pytest.approx(cm.SECOND_FLIGHT_LAT) and lon > cm.EQUATOR_START[1] + 10


def test_earth_turn_is_monotone_and_eastward(story):
    frames = range(0, sum(LENGTHS), 7)
    phis = [story.phi(f / 30) for f in frames]
    assert all(b > a for a, b in zip(phis, phis[1:]))
    a, b = cm.rot_y(cm.point(0, 0), 10), cm.point(0, 10)
    assert a == pytest.approx(b)


def test_views_are_continuous_and_return_to_the_opening(story):
    angles = [story.apparent(f / 30) for f in range(sum(LENGTHS))]
    assert max(abs(b - a) for a, b in zip(angles, angles[1:])) < 1.2
    for t in (story.s[22] + cm.PSI_RETURN,):
        assert (story.psi(t) - story.psi0 + 180) % 360 - 180 == pytest.approx(0, abs=1e-6)


def test_plane_moves_without_jumps(story):
    points = [story.plane(f / 30)[0] for f in range(sum(LENGTHS))]
    assert max(math.dist(a, b) for a, b in zip(points, points[1:])) < .05


def test_state_is_independent_of_evaluation_order(story):
    frames = [5000, 300, 7000, 1200]
    expected = {f: story.state(f)['plane_pos'] for f in frames}
    assert {f: story.state(f)['plane_pos'] for f in reversed(frames)} == expected
    assert renderer_modules('coriolis-story-blender-v1') == ('coriolis_story', 'CoriolisStoryGallery')


def test_rejects_wrong_beat_order():
    job = dict(scene_graph=cm.GRAPH, frame_count=10, duration_frames=sum(LENGTHS[:22]), canonical_fps=30,
               output=dict(width=384, height=216, fps=12), timeline=timeline()[:22])
    with pytest.raises(ValueError, match='23-beat'):
        cm.validate_job(job)
