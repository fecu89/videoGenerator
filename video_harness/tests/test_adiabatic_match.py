import pytest
from video_harness.blender_renderer.adiabatic_match_math import zoom_weight, match_distance


def test_zoom_starts_and_finishes_on_matched_sphere_then_reveals_context():
    assert zoom_weight(0,600,60,60)==1
    assert zoom_weight(60,600,60,60)==0
    assert zoom_weight(300,600,60,60)==0
    assert zoom_weight(599,600,60,60)==1
    assert zoom_weight(30,600,60,60)==pytest.approx(.5)
    assert zoom_weight(569,600,60,60)==pytest.approx(.5)
    assert abs(zoom_weight(60,600,60,60)-zoom_weight(59,600,60,60))<.001


def test_different_sized_real_spheres_have_identical_projected_size():
    for radius in (.105,.29,2):
        distance=match_distance(radius)
        assert distance>radius
        assert radius/(distance*36/85)==pytest.approx(.9)
