import math
import pytest
from video_harness.blender_renderer.eclipse_math import angular_diameter, orbit_position, shadow_radii


def test_equal_size_distance_ratio_preserves_angular_size():
    assert angular_diameter(400,172000)==pytest.approx(angular_diameter(1,430))
    assert angular_diameter(1,460)<angular_diameter(1,430)


def test_shadow_cone_crosses_into_antumbra_after_apex():
    apex=24*.9/(2.5-.9)
    assert shadow_radii(2.5,.9,24,apex)[0]==pytest.approx(0)
    assert shadow_radii(2.5,.9,24,apex+1)[0]<0
    u,p=shadow_radii(2.5,.9,24,8)
    assert 0<u<.9<p


def test_inclination_preserves_radius_and_has_two_nodes():
    for a in [0,.4,math.pi/2,math.pi,1.8*math.pi]:
        xyz=orbit_position(a)
        assert math.sqrt(sum(v*v for v in xyz))==pytest.approx(6)
    assert orbit_position(0)[2]==pytest.approx(0)
    assert orbit_position(math.pi)[2]==pytest.approx(0,abs=1e-12)
    assert orbit_position(math.pi/2)[2]==pytest.approx(6*math.sin(math.radians(5)))


def test_invalid_observer_and_shadow_geometry_rejected():
    with pytest.raises(ValueError):angular_diameter(1,.5)
    with pytest.raises(ValueError):shadow_radii(2,1,0,3)


def test_northern_solar_occultation_enters_from_right():
    from video_harness.blender_renderer.eclipse_math import northern_solar_offset
    positions=[northern_solar_offset(p/100,3.7) for p in range(101)]
    assert positions[0] == 3.7
    assert positions[-1] == 0
    assert all(a > b for a,b in zip(positions,positions[1:]))
