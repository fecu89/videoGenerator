import math

import pytest

from video_harness.blender_renderer.virial_galaxy_math import spin_quaternion


@pytest.mark.parametrize('turns', [0, 1, 2, 7])
def test_spin_quaternion_stays_continuous_through_odd_multiples_of_pi(turns):
    # mathutils.Quaternion(axis, angle) folds the angle into (-pi, pi], so the
    # quaternion flips to -q at every odd multiple of pi; keyframes interpolated
    # across that flip whirl the star shell for a few frames.
    angle = math.pi * (2 * turns + 1)
    before, after = spin_quaternion(angle - 1e-3), spin_quaternion(angle + 1e-3)
    assert max(abs(a - b) for a, b in zip(before, after)) < 1e-2


def test_spin_quaternion_is_a_unit_rotation_about_z():
    w, x, y, z = spin_quaternion(1.2)
    assert (x, y) == (0.0, 0.0)
    assert w == pytest.approx(math.cos(0.6)) and z == pytest.approx(math.sin(0.6))


def test_absorption_line_broadens_with_mixing_and_dispersion_and_gets_shallower():
    from video_harness.blender_renderer.virial_galaxy_math import line_profile
    narrow, _ = line_profile(sigma=1.0, mixed=0.0)
    s_half, d_half = line_profile(sigma=1.0, mixed=0.5)
    s_full, d_full = line_profile(sigma=1.0, mixed=1.0)
    assert narrow < s_half < s_full                     # one star's line widens as the light mixes
    assert d_full < d_half                              # a broadened line is shallower
    slow, _ = line_profile(sigma=0.45, mixed=1.0)
    fast, _ = line_profile(sigma=1.5, mixed=1.0)
    assert fast / slow == pytest.approx(1.5 / 0.45, rel=0.05)   # width tracks the velocity dispersion
