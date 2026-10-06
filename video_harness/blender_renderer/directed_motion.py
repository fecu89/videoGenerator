"""Deterministic staging of the single ray and orbit; scales are illustrative."""
import math
try:
    from .spectra import smooth
except ImportError:
    from spectra import smooth


def atmosphere_ray_length(p):
    return .02 + .25*smooth((p-.11)/.20) + 1.33*smooth((p-.32)/.50) + .90*smooth((p-.82)/.18)


def atmosphere_absorption(p):
    return .94*smooth(atmosphere_ray_length(p)/1.60)


def orbit_angle(p):
    return math.radians(22+50*smooth((p-.18)/.26)+4*smooth((p-.50)/.50))


def incoming_ray_head(p):
    q=smooth((p-.025)/.34)
    return 2400 - 68*(2400/68)**(1-q)
