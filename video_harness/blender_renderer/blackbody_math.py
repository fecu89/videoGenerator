"""Pure, unit-aware relations used by the blackbody film."""
import math

WIEN_NM_K = 2.897771955e6
C2_NM_K = 1.438776877e7


def spectrum_shape(wavelength_nm, temperature_k):
    if wavelength_nm <= 0 or temperature_k <= 0:
        raise ValueError('wavelength and temperature must be positive')
    exponent = C2_NM_K / (wavelength_nm * temperature_k)
    if exponent > 700:
        return 0.0
    return wavelength_nm ** -5 / math.expm1(exponent)


def normalized_spectrum(wavelength_nm, temperature_k):
    return spectrum_shape(wavelength_nm, temperature_k) / spectrum_shape(WIEN_NM_K / temperature_k, temperature_k)


def radius_ratio(luminosity_ratio, temperature_ratio):
    if luminosity_ratio <= 0 or temperature_ratio <= 0:
        raise ValueError('ratios must be positive')
    return math.sqrt(luminosity_ratio) / temperature_ratio ** 2


def received_flux_ratio(distance_ratio):
    if distance_ratio <= 0:
        raise ValueError('distance must be positive')
    return distance_ratio ** -2
