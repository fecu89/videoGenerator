import math
from video_harness.blender_renderer.directed_motion import atmosphere_ray_length, atmosphere_absorption, orbit_angle, incoming_ray_head


def test_absorption_grows_with_one_ray_crossing_the_atmosphere():
    points=[i/100 for i in range(101)]
    lengths=[atmosphere_ray_length(p) for p in points]
    absorption=[atmosphere_absorption(p) for p in points]
    assert all(a<=b for a,b in zip(lengths,lengths[1:]))
    assert all(a<=b for a,b in zip(absorption,absorption[1:]))
    assert absorption[0]<.001
    assert atmosphere_absorption(.5)<atmosphere_absorption(.75)<.94
    assert absorption[-1]==.94
    assert lengths[-1]>1.6


def test_orbit_goes_from_overhead_to_oblique_side_view():
    assert math.degrees(orbit_angle(0))==22
    assert math.isclose(math.degrees(orbit_angle(1)),76)
    assert orbit_angle(.2)<orbit_angle(.3)<orbit_angle(.44)


def test_single_incoming_ray_arrives_from_distant_star():
    assert abs(incoming_ray_head(0))<1e-9
    assert math.isclose(incoming_ray_head(.365),2332)
    values=[incoming_ray_head(i/100) for i in range(101)]
    assert all(a<=b for a,b in zip(values,values[1:]))
