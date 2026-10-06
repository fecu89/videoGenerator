import pytest
from video_harness.blender_renderer.blackbody_math import normalized_spectrum, radius_ratio, received_flux_ratio, WIEN_NM_K


def test_wien_peak_and_hotter_peak_shift():
    for temperature in [3500, 5800, 15000]:
        peak = WIEN_NM_K / temperature
        assert normalized_spectrum(peak, temperature) == pytest.approx(1)
        assert normalized_spectrum(peak * .8, temperature) < 1
        assert normalized_spectrum(peak * 1.2, temperature) < 1
    assert WIEN_NM_K / 15000 < WIEN_NM_K / 3500


def test_hypothetical_radius_and_luminosity_reconstruction():
    radius = radius_ratio(100, .5)
    assert radius == 40
    assert radius ** 2 * .5 ** 4 == 100
    assert received_flux_ratio(2) == .25


def test_nonphysical_inputs_fail():
    with pytest.raises(ValueError):
        radius_ratio(100, 0)
    with pytest.raises(ValueError):
        received_flux_ratio(0)
