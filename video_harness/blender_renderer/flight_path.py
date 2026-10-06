"""Camera motion in illustrative distance units, not a physical travel speed."""
def _hermite(q, a, b, va, vb, duration):
    return (2*q**3-3*q**2+1)*a + (q**3-2*q**2+q)*va*duration + (-2*q**3+3*q**2)*b + (q**3-q**2)*vb*duration


def flight_distance(progress, profile="original"):
    p = max(0., min(1., progress))
    if profile == "rapid":
        if p <= .10:
            return 24 + 7*(p/.10)**2
        if p <= .39:
            return _hermite((p-.10)/.29, 31, 2350, 140, 250, .29)
        if p <= .68:
            return _hermite((p-.39)/.29, 2350, 2400, 250, 0, .29)
        return 2400.
    if p <= .23:
        return 24 + 12*(p/.23)**2
    if p <= .78:
        return _hermite((p-.23)/.55, 36, 2360, 24/.23, 160, .55)
    return _hermite((p-.78)/.22, 2360, 2400, 160, 0, .22)


def flight_speed(progress, profile="original"):
    step = .00001
    return (flight_distance(progress+step,profile)-flight_distance(progress-step,profile))/(2*step)
