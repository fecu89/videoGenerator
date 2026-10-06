"""Frame-independent state for the Saturn ring film (why the rings stay rings).

Lengths are Saturn equatorial radii. The ring plane is XY, north is +Z and
everything orbits counterclockwise seen from the north (prograde). Angular
rates follow Kepler's third law, omega ~ r^-1.5, on one compressed display
clock (the B ring turns once in 180 s of film).

Teaching exaggerations, recorded in the run's research.md:
- moons and ring particles are drawn far larger than to scale;
- the moon's inward drift is a thought experiment, not an orbital solution;
- arrow lengths compare gravity at the near and far side with a lever arm
  larger than the drawn body, so the difference is readable;
- debris spreads along the orbit by Keplerian shear, sped up for display.

Every value is a pure function of the frame, so frames can be rendered in any
order. No words are drawn; narration and subtitles carry them.
"""
import math
import random

GRAPH = 'saturn-rings-blender-v1'
CONTROLLER = 'saturn-rings'

SHOTS = ['s01a', 's01b', 's02a', 's02b', 's03a', 's03b', 's04a', 's04b', 's05a', 's05b',
         's06a', 's06b', 's07a', 's07b', 's08a', 's08b', 's09a', 's09b', 's10a', 's10b',
         's11a', 's11b', 's12a', 's12b', 's13a', 's13b', 's14a', 's14b', 's15a', 's15b',
         's16a', 's16b', 's17a', 's17b', 's17c', 's18a', 's18b', 's19a', 's19b', 's20a', 's20b']

OBLATE = 0.902
RING_IN, RING_OUT = 1.24, 2.27          # C ring inner edge .. A ring outer edge
ROCHE = 2.30                            # displayed Roche limit (just outside the A ring)
R_FOCUS = 1.75                          # B ring radius used for the close views
W0 = math.tau / 180.0                   # display angular rate at R_FOCUS
SPIN = math.tau / 165.0
SUN_AZ, SUN_EL = math.radians(-50), math.radians(24)

MOON_R = 0.20
MOON_FAR = 3.20
BREAK_R = 2.27
LEVER = 2.4 * MOON_R                    # display lever arm for near/far gravity
KG, KT, SELF_LEN = 3.2, 3.8, 0.20     # tide and self-gravity arrows cross near r = 2.63
SEED_SPREAD = 0.8 * MOON_R              # shard seed points fill this radius inside the moon
LAPSE_A, LAPSE_P = 0.08, 0.80           # extra orbital rate (rad/s) while debris spreads: time-lapse, all prograde
HEAD = 0.13                             # arrow head length
SHEAR = 0.12                            # close-view strip shear (1/s per unit radius)

N_LAYERS, N_HERO, N_FRAG, N_DEBRIS, N_OUT, N_IN = 6, 8, 36, 24, 12, 10


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def up(t, start, duration):
    return smooth((t - start) / duration)


def win(t, start, end, fade):
    """0 -> 1 after start, back to 0 by end."""
    return up(t, start, fade) * (1 - up(t, end - fade, fade))


def kepler(r):
    return W0 * (R_FOCUS / r) ** 1.5


def polar(r, phi, z=0.0):
    return (r * math.cos(phi), r * math.sin(phi), z)


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def mix(a, b, s):
    return tuple(x + (y - x) * s for x, y in zip(a, b))


def lerp(a, b, s):
    return a + (b - a) * s


def local(r, phi, dr=0.0, dt=0.0, dz=0.0):
    """Point offset from (r, phi) along outward radial, prograde tangent and north."""
    c, s = math.cos(phi), math.sin(phi)
    return (r * c + dr * c - dt * s, r * s + dr * s + dt * c, dz)


def orbit_eye(az_deg, el_deg, dist, look=(0.0, 0.0, 0.0)):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return add(look, (dist * math.cos(el) * math.cos(az), dist * math.cos(el) * math.sin(az), dist * math.sin(el)))


def rock_table(seed, count, spread, sizes):
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        while True:
            p = [rng.uniform(-1, 1) for _ in range(3)]
            if sum(v * v for v in p) <= 1:
                break
        rows.append(dict(p=tuple(v * spread for v in p), size=rng.uniform(*sizes),
                         rot=tuple(rng.uniform(0, math.tau) for _ in range(3)),
                         rate=tuple(rng.uniform(-.5, .5) for _ in range(3))))
    return rows


class Story:
    def __init__(self, timeline, fps):
        self.fps = fps
        beats = {b['controller_options']['shot']: b for b in timeline}
        self.order = [b['controller_options']['shot'] for b in sorted(timeline, key=lambda b: b['start_frame'])]
        self.T = {k: b['start_frame'] / fps for k, b in beats.items()}
        self.E = {k: b['end_frame'] / fps for k, b in beats.items()}
        self.total = max(b['end_frame'] for b in timeline)
        T, E = self.T, self.E
        self.t_break = T['s10b']
        self.t_break_past = T['s16b'] + 0.3
        self.t_hit = T['s17a'] + 1.5
        self.focus_centres = ((T['s02a'] + T['s05a']) / 2, (T['s14a'] + T['s15b']) / 2, T['s20a'] + 2.0)
        self.focus_switch = (T['s09a'], T['s17a'])
        self.hero = rock_table(11, N_HERO, 1.0, (.008, .014))
        hero_pos = [(.000, .000, .000), (.020, .016, .003), (-.018, .022, -.002), (.012, -.026, .002),
                    (-.030, -.012, .004), (.034, -.006, -.003), (-.006, .046, .002), (.040, .034, -.002)]
        for row, p, size in zip(self.hero, hero_pos, (.020, .017, .015, .012, .011, .010, .010, .009)):
            row['p'], row['size'] = p, size
        self.frag = rock_table(23, N_FRAG, 1.0, (1.0, 1.0))
        self.debris = rock_table(37, N_DEBRIS, 1.0, (.045, .085))
        self.clump_out = rock_table(41, N_OUT, .38, (.04, .07))
        self.clump_in = rock_table(53, N_IN, .20, (.03, .05))
        self._integrate()
        self.shots = self._shots()

    # ----- orbits that change radius: integrate the angle once per frame --------------
    def moon_r(self, t):
        T = self.T
        return MOON_FAR - (MOON_FAR - BREAK_R) * smooth((t - T['s07a']) / (self.t_break - T['s07a']))

    def past_r(self, t):
        start = self.T['s16a'] + 0.2
        return 3.1 - (3.1 - BREAK_R) * smooth((t - start) / (self.t_break_past - start))

    def test_r(self, t):
        start, end = self.T['s18a'] + 0.8, self.E['s18b'] - 0.4
        return 3.4 - (3.4 - 2.60) * smooth((t - start) / (end - start))

    def _integrate(self):
        n, fps = self.total + 1, self.fps
        def table(radius, anchor_time, anchor_phi):
            phi, acc = [], 0.0
            for f in range(n):
                phi.append(acc)
                acc += kepler(radius(f / fps)) / fps
            k = clamp(round(anchor_time * fps), 0, n - 1)
            shift = anchor_phi - phi[k]
            return [p + shift for p in phi]
        self._phi_moon = table(self.moon_r, self.T['s05b'], math.radians(285))
        self._phi_past = table(self.past_r, self.T['s16a'], math.radians(292))
        self._phi_test = table(self.test_r, self.T['s18a'], math.radians(286))

    def _lookup(self, table, t):
        x = clamp(t * self.fps, 0, len(table) - 1.000001)
        i = int(x)
        return table[i] + (table[i + 1] - table[i]) * (x - i)

    @staticmethod
    def lapse(tau):
        """Smoothly starting clock for the sped-up spreading of debris."""
        return tau - (1 - math.exp(-tau)) if tau > 0 else 0.0

    def moon_phi(self, t):
        return self._lookup(self._phi_moon, t) + LAPSE_A * self.lapse(t - self.t_break)

    def past_phi(self, t):
        return self._lookup(self._phi_past, t) + LAPSE_P * self.lapse(t - self.t_break_past)

    def test_phi(self, t):
        return self._lookup(self._phi_test, t)

    @staticmethod
    def stretch(r, strength=0.62):
        return 1 + strength * clamp((MOON_FAR - r) / (MOON_FAR - BREAK_R))

    # ----- close-view patch ------------------------------------------------------------
    def focus_segment(self, t):
        return 0 if t < self.focus_switch[0] else 1 if t < self.focus_switch[1] else 2

    def focus_phi(self, t):
        return math.radians(305) + W0 * (t - self.focus_centres[self.focus_segment(t)])

    def focus(self, t, dr=0.0, dt=0.0, dz=0.0):
        return local(R_FOCUS, self.focus_phi(t), dr, dt, dz)

    def patch_visibility(self, t):
        T = self.T
        # the loose blocks show only while the camera is among them
        return clamp(win(t, T['s02a'] + .3, T['s05a'] + .5, .7) + win(t, T['s14a'] + .3, T['s15b'] + .5, .7)
                     + win(t, T['s20a'] - .2, T['s20b'] + .9, .7))

    def ring_visibility(self, t):
        return clamp(1 - up(t, self.T['s16a'], 1.0) + up(t, self.T['s17c'], 1.0))

    def hero_closeness(self, t):
        T, E = self.T, self.E
        if t < self.focus_switch[0]:
            return 1 - .62 * up(t, T['s03a'], E['s03b'] - T['s03a']) + .62 * up(t, T['s04b'], 2.5)
        if t < self.focus_switch[1]:
            return 1 - .65 * up(t, T['s14b'], 2.0) + .95 * up(t, T['s14b'] + 2.4, 3.0)
        return 1.0

    # ----- orbit centres ------------------------------------------------------------------
    def out_phi(self, t):
        return math.radians(298) + kepler(3.0) * (t - self.T['s12a'])

    def in_phi(self, t):
        return math.radians(318) + kepler(1.72) * (t - self.T['s12b'])

    def hit_phi(self, t):
        return math.radians(300) + kepler(2.75) * (t - self.T['s17a'])

    # ----- camera -------------------------------------------------------------------------
    def _shots(self):
        T = self.T
        moon = lambda t: (self.moon_r(t), self.moon_phi(t))
        test = lambda t: (self.test_r(t), self.test_phi(t))
        def wide(az0, az1, el0, el1, d0, d1, lens=50.0, look=(0, 0, 0)):
            return lambda t, u: (orbit_eye(lerp(az0, az1, u), lerp(el0, el1, u), lerp(d0, d1, u), look), look, lens)
        def near(a, b, look, lens):
            return lambda t, u: (self.focus(t, *mix(a, b, u)), self.focus(t, *look), lens)
        def follow(body, a, b, look, lens):
            def shot(t, u):
                r, phi = body(t)
                return local(r, phi, *mix(a, b, u)), local(r, phi, *look), lens
            return shot
        def aimed(az, el, d, target, lens):
            def shot(t, u):
                look = target(t)
                return orbit_eye(az + 3 * u, el, d, look), look, lens
            return shot
        break_az = math.degrees(self.moon_phi(T['s11a'])) + 40
        out_az = math.degrees(self.out_phi(T['s12a'])) - 6
        in_az = math.degrees(self.in_phi(T['s12b'])) - 4
        hit_az = math.degrees(self.hit_phi(self.t_hit))
        let_az = math.degrees(self.out_phi(T['s19a'])) - 20
        past_az = math.degrees(self.past_phi(self.t_break_past)) + 75
        return {
            's01a': wide(-74, -70, 20, 19, 8.2, 7.1),
            's01b': wide(-70, -66, 19, 5, 7.1, 6.3),
            's02a': near((.90, -.55, .34), (.42, -.28, .16), (0, 0, 0), 40.0),
            's02b': near((.17, -.11, .040), (.13, -.08, .032), (-.05, .02, 0), 35.0),
            's03a': near((.085, -.060, .024), (.070, -.050, .020), (.004, .004, 0), 40.0),
            's03b': near((.070, -.050, .020), (.056, -.034, .016), (.004, .004, 0), 40.0),
            's04a': near((.090, -.070, .028), (.110, -.080, .032), (0, 0, 0), 38.0),
            's04b': near((.25, -.16, .10), (.48, -.26, .22), (-.18, 0, 0), 35.0),
            's05a': wide(-88, -84, 32, 34, 8.4, 8.8, 45.0),
            's05b': follow(moon, (-1.1, -5.4, 1.7), (-1.0, -4.9, 1.5), (-1.75, 0, 0), 40.0),
            's06a': follow(moon, (-.20, -2.5, .62), (-.18, -2.3, .56), (-.42, 0, 0), 30.0),
            's06b': follow(moon, (-.18, -2.3, .56), (-.14, -2.1, .50), (-.40, 0, 0), 30.0),
            's07a': follow(moon, (-.50, -3.0, .85), (-.42, -2.7, .75), (-.75, 0, 0), 28.0),
            's07b': follow(moon, (-.30, -2.5, .60), (-.26, -2.3, .55), (-.50, 0, 0), 28.0),
            's08a': follow(moon, (-.16, -2.3, .55), (-.14, -2.15, .50), (-.28, 0, 0), 30.0),
            's08b': follow(moon, (-.10, -2.05, .48), (-.08, -1.95, .45), (-.20, 0, 0), 30.0),
            's09a': follow(moon, (-.10, -2.1, .50), (-.10, -2.0, .48), (-.22, 0, 0), 30.0),
            's09b': follow(moon, (-.20, -2.4, .60), (-.22, -2.5, .64), (-.35, 0, 0), 28.0),
            's10a': follow(moon, (-.12, -2.15, .52), (-.10, -2.05, .50), (-.24, 0, 0), 30.0),
            's10b': follow(moon, (-.30, -2.4, .90), (-.40, -3.0, 1.20), (-.30, .30, 0), 28.0),
            's11a': wide(break_az, break_az + 3, 48, 52, 9.9, 9.6, 45.0),
            's11b': wide(break_az + 3, break_az + 6, 52, 55, 9.6, 9.4, 45.0),
            's12a': aimed(out_az, 34, 3.4, lambda t: polar(2.80, self.out_phi(t)), 40.0),
            's12b': aimed(in_az, 36, 2.6, lambda t: polar(1.75, self.in_phi(t)), 40.0),
            's13a': wide(-90, -88, 70, 70, 10.9, 10.6, 45.0),
            's13b': wide(-88, -84, 70, 62, 10.6, 10.0, 45.0),
            's14a': near((.60, -.36, .24), (.30, -.18, .11), (0, 0, 0), 40.0),
            's14b': near((.085, -.058, .024), (.070, -.046, .020), (.004, .004, 0), 40.0),
            's15a': near((.050, -.095, .020), (.056, -.110, .024), (.004, .05, 0), 35.0),
            's15b': wide(-62, -58, 26, 25, 7.0, 7.4),
            's16a': aimed(past_az - 8, 38, 6.6, lambda t: polar(1.5, self.past_phi(t)), 42.0),
            's16b': wide(past_az - 4, past_az + 4, 60, 64, 10.2, 10.6, 45.0),
            's17a': aimed(hit_az - 4, 38, 3.4, lambda t: polar(2.45, self.hit_phi(t)), 40.0),
            's17b': wide(-64, -60, 34, 33, 9.8, 9.6, 45.0),
            's17c': wide(-60, -56, 33, 24, 9.6, 8.6, 45.0),
            's18a': follow(test, (-1.0, -4.8, 1.55), (-.95, -4.4, 1.4), (-1.55, 0, 0), 40.0),
            's18b': follow(test, (-.60, -3.4, 1.0), (-.50, -3.1, .92), (-.80, 0, 0), 38.0),
            's19a': aimed(let_az, 26, 4.4, lambda t: polar(2.45, self.out_phi(t)), 40.0),
            's19b': wide(-76, -72, 48, 50, 9.3, 9.0, 45.0),
            's20a': near((.17, -.11, .040), (.27, -.17, .085), (-.05, .02, 0), 35.0),
            's20b': wide(-66, -58, 17, 15, 7.3, 8.0),
        }

    def camera(self, t):
        index = 0
        for i, key in enumerate(self.order):
            if t >= self.T[key]:
                index = i
        key = self.order[index]
        def evaluate(k):
            return self.shots[k](t, (t - self.T[k]) / (self.E[k] - self.T[k]))
        eye, look, lens = evaluate(key)
        if index:
            # Ease out of the previous framing; long moves get a longer blend.
            length = self.E[key] - self.T[key]
            blend = min(1.6 if key in LONG_MOVES else 1.1, 0.7 * length)
            s = smooth((t - self.T[key]) / blend)
            if s < 1:
                e0, l0, n0 = evaluate(self.order[index - 1])
                eye, look, lens = mix(e0, eye, s), mix(l0, look, s), lerp(n0, lens, s)
        return eye, look, lens, key

    # ----- arrows ---------------------------------------------------------------------------
    @staticmethod
    def arrow(base, direction, length, thick=1.0):
        angle = math.atan2(direction[1], direction[0])
        head = HEAD * thick
        shaft = max(length - head, 0.001)
        head_scale = thick * (clamp(length / head) if length < head else 1.0)
        tip = add(base, (direction[0] * shaft, direction[1] * shaft, 0))
        return (base, (0, 0, angle), (shaft, thick, thick)), (tip, (0, 0, angle), (head_scale,) * 3)

    def arrows(self, t, xf, op, eye):
        T = self.T
        if t < T['s12a']:
            r, phi = self.moon_r(t), self.moon_phi(t)
            sx = self.stretch(r)
            vg = win(t, T['s05b'] + 0.4, T['s08a'] + 1.0, 0.6)
            vt = up(t, T['s08a'] + 0.5, 0.7) * (1 - up(t, self.t_break, 0.3))
            vs = up(t, T['s09a'] + 0.3, 0.6) * (1 - up(t, self.t_break - 0.1, 0.3))
        else:
            r, phi = self.test_r(t), self.test_phi(t)
            sx = self.stretch(r, 0.28)
            vg = win(t, T['s18a'] + 0.6, T['s19a'] + 0.5, 0.5)
            vt = vs = 0.0
        er = (math.cos(phi), math.sin(phi), 0.0)
        inward = (-er[0], -er[1], 0.0)
        c = polar(r, phi)
        edge = MOON_R * sx + 0.03
        g = lambda x: 1.0 / (x * x)
        near_len, far_len = KG * g(r - LEVER), KG * g(r + LEVER)
        # To first order the tide is the same size on both sides and points apart: 2 G M d / r^3.
        tide = KT * 2 * LEVER / r ** 3
        half = MOON_R * sx

        def at(k):
            return (c[0] + er[0] * k, c[1] + er[1] * k, 0.0)
        specs = {
            'GNear': (at(-edge), inward, near_len, 1.0),
            'GFar': (at(edge + far_len), inward, far_len, 1.0),
            'TNear': (at(-edge), inward, tide, 1.0),
            'TFar': (at(edge), er, tide, 1.0),
            'SNear': (at(-.94 * half), er, SELF_LEN, .5),
            'SFar': (at(.94 * half), inward, SELF_LEN, .5),
        }
        # Every arrow is laid out on the moon's own axis, then the whole set is shrunk toward the
        # camera eye. A scaling about the eye leaves the picture unchanged, so on screen all arrows
        # stay on one line through the moon's centre while sitting in front of the moon and the ring.
        distance = math.sqrt(sum((eye[k] - c[k]) ** 2 for k in range(3)))
        f = max(.2, (distance - (MOON_R + .16)) / distance)
        for name, (base, direction, length, thick) in specs.items():
            lifted = tuple(eye[k] + (base[k] - eye[k]) * f for k in range(3))
            xf[name + 'Shaft'], xf[name + 'Head'] = self.arrow(lifted, direction, length * f, thick * f)
        op['Gravity'], op['Tide'], op['Self'] = vg, vt, vs
        return dict(near=near_len, far=far_len, tide=tide, self=SELF_LEN)

    # ----- whole state -------------------------------------------------------------------------
    def state(self, frame):
        t = frame / self.fps
        T, E = self.T, self.E
        xf, op = {}, {}
        unit = (1.0, 1.0, 1.0)
        ring = self.ring_visibility(t)
        patch = self.patch_visibility(t)
        xf['Saturn'] = ((0, 0, 0), (0, 0, SPIN * t), (1, 1, OBLATE))
        xf['RingDisk'] = ((0, 0, 0), (0, 0, W0 * t), unit)
        op['RingDisk'] = ring * (1 - .93 * patch)

        # close-view strips shear past each other; individual rocks tumble
        f_phi = self.focus_phi(t)
        g = t - self.focus_centres[self.focus_segment(t)]
        for i in range(N_LAYERS):
            x = (i - (N_LAYERS - 1) / 2) * .03
            xf['Patch%d' % i] = ((0, 0, 0), (0, 0, f_phi - SHEAR * x * g / R_FOCUS), unit)
        op['Patch'] = patch
        k = self.hero_closeness(t)
        for i, row in enumerate(self.hero):
            x, y, z = row['p']
            xf['Hero%d' % i] = (local(R_FOCUS, f_phi, x * k, y * k, z),
                                tuple(a + b * t for a, b in zip(row['rot'], row['rate'])), (row['size'],) * 3)
        op['Hero'] = patch
        xf['Ghost'] = (local(R_FOCUS, f_phi, 0, 0, 0), (0, 0, f_phi), unit)
        op['Ghost'] = .30 * win(t, T['s04a'] + .2, E['s04a'] + .5, .8)

        # The moon of the thought experiment is built from shards that fit together exactly.
        # MoonA itself stays as an invisible tracking body for the camera and continuity checks.
        r, phi = self.moon_r(t), self.moon_phi(t)
        sx = self.stretch(r)
        xf['MoonA'] = (polar(r, phi), (0, 0, phi), (sx, sx ** -.5, sx ** -.5))
        op['MoonA'] = 0.0
        pr, pphi = self.past_r(t), self.past_phi(t)
        if t < T['s15b']:
            tb, lapse_rate, body_r, body_phi = self.t_break, LAPSE_A, r, phi
            # the moon enters only when the narration turns to it
            vis = up(t, T['s05a'] + .3, 1.2) * (1 - up(t, T['s11b'] - 1.2, 1.0))
            crack = .045 * up(t, T['s10a'] + .4, max(.5, tb - T['s10a'] - .4))
        else:
            tb, lapse_rate, body_r, body_phi = self.t_break_past, LAPSE_P, pr, pphi
            vis = up(t, T['s16a'] + .2, .8) * (1 - up(t, T['s17a'] - .6, .8))
            crack = .045 * up(t, tb - 1.2, 1.2)
        tau = max(0.0, t - tb)
        bsx = self.stretch(body_r if tau == 0 else BREAK_R)
        scale = (bsx, bsx ** -.5, bsx ** -.5)
        # After the break every shard keeps orbiting the same way; inner ones lead, outer ones lag.
        spread = 1 + crack + .9 * (1 - math.exp(-tau / 2))
        spin = tau * tau / (tau + 1)
        for i, row in enumerate(self.frag):
            sx_i, sy_i, sz_i = (row['p'][k] * SEED_SPREAD * scale[k] * spread for k in range(3))
            fr = body_r + sx_i
            base_phi = body_phi - lapse_rate * self.lapse(tau)
            fphi = base_phi + sy_i / body_r + lapse_rate * self.lapse(tau) * (body_r / fr) ** 1.5
            xf['Frag%02d' % i] = (polar(fr, fphi, sz_i * math.exp(-tau / 4)),
                                  (row['rate'][0] * spin, row['rate'][1] * spin, fphi - sy_i / body_r + row['rate'][2] * spin), scale)
        op['Frag'] = vis

        # two moons colliding (another hypothesis)
        hphi = self.hit_phi(t)
        gap = .42 * (1 - smooth((t - T['s17a']) / (self.t_hit - T['s17a'])))
        xf['MoonB'] = (polar(2.72, hphi - gap - .055), (0, 0, hphi), unit)
        xf['MoonC'] = (polar(2.78, hphi + gap + .055), (0, 0, hphi + 1.0), unit)
        op['MoonB'] = op['MoonC'] = up(t, T['s17a'], .5) * (1 - up(t, self.t_hit - .1, .3))
        tau = max(0.0, t - self.t_hit)
        for i, row in enumerate(self.debris):
            u, v, w = row['p']
            dr = .30 * u * (1 - math.exp(-tau / 1.5))
            dphi = 1.5 * v * (1 - math.exp(-tau / 2.0)) / 2.75
            xf['Debris%02d' % i] = (polar(2.75 + dr, hphi + dphi, .16 * w * (1 - math.exp(-tau / 1.2))),
                                    tuple(p + q * t for p, q in zip(row['rot'], row['rate'])), (row['size'],) * 3)
        op['Debris'] = up(t, self.t_hit - .05, .25) * (1 - up(t, T['s17b'] - .5, .8))
        xf['ProtoDisk'] = ((0, 0, -.004), (0, 0, .5 * W0 * t), unit)
        op['ProtoDisk'] = .8 * win(t, T['s17b'], T['s17c'] + .8, .9)

        # outside the limit material gathers into a moon; inside it is sheared apart
        ophi = self.out_phi(t)
        squeeze = 1 - .9 * up(t, T['s12a'] + .2, 2.6)
        for i, row in enumerate(self.clump_out):
            u, v, w = row['p']
            xf['Out%02d' % i] = (local(3.0, ophi, u * squeeze, v * squeeze, w * .4 * squeeze),
                                 tuple(p + q * t for p, q in zip(row['rot'], row['rate'])), (row['size'],) * 3)
        op['Out'] = up(t, T['s12a'] - .4, .8) * (1 - up(t, T['s12a'] + 2.3, .9))
        grown = up(t, T['s12a'] + 2.0, 1.2)
        xf['Moonlet'] = (polar(3.0, ophi), (0, 0, ophi), (.35 + .65 * grown,) * 3)
        op['Moonlet'] = clamp(win(t, T['s12a'] + 2.0, T['s12b'] + 1.1, .8) + win(t, T['s19a'] - .4, T['s19b'] + 1.0, .8))
        iphi = self.in_phi(t)
        squeeze = 1 - .7 * up(t, T['s12b'], 1.5)
        q = max(0.0, t - (T['s12b'] + 1.6))
        for i, row in enumerate(self.clump_in):
            u, v, w = row['p']
            shear = -1.6 * u * q * q / (q + .6)
            xf['In%02d' % i] = (polar(1.72 + u * squeeze, iphi + v * squeeze / 1.72 + shear, .012 + w * .15 * squeeze),
                                tuple(p + q2 * t for p, q2 in zip(row['rot'], row['rate'])), (row['size'],) * 3)
        op['In'] = up(t, T['s12b'] - .3, .8) * (1 - up(t, T['s13a'] - .6, .8))

        # the test body of the closing comparison
        tr, tphi = self.test_r(t), self.test_phi(t)
        tsx = self.stretch(tr, .28)
        xf['MoonT'] = (polar(tr, tphi), (0, 0, tphi), (tsx, tsx ** -.5, tsx ** -.5))
        op['MoonT'] = up(t, T['s18a'], .6) * (1 - up(t, T['s19a'], .7))

        eye, look, lens, shot = self.camera(t)
        forces = self.arrows(t, xf, op, eye)

        xf['RocheCircle'] = ((0, 0, .003), (0, 0, 0), unit)
        op['RocheCircle'] = clamp(win(t, T['s11a'] + .4, T['s14a'] + 1.0, 1.0) + win(t, T['s19b'] - .5, T['s20a'] + .8, .8))
        xf['RocheShell'] = ((0, 0, 0), (0, 0, 0), unit)
        op['RocheShell'] = .5 * win(t, T['s11b'] - .3, T['s12a'] + .9, 1.0)
        xf['RingGlow'] = ((0, 0, .002), (0, 0, 0), unit)
        op['RingGlow'] = .13 * win(t, T['s13a'] + .5, E['s13b'] + .4, .8) + .11 * win(t, T['s19b'], E['s19b'] + .3, .7)

        return dict(t=t, shot=shot, xf=xf, op=op, camera=(eye, look, lens), forces=forces,
                    moon=dict(r=r, stretch=sx), ring=ring, patch=patch)


LONG_MOVES = {'s02a', 's05a', 's05b', 's11a', 's13a', 's14a', 's15b', 's16a', 's18a', 's19b', 's20a', 's20b'}


def sun_direction():
    """Unit vector from the scene toward the Sun."""
    return (math.cos(SUN_EL) * math.cos(SUN_AZ), math.cos(SUN_EL) * math.sin(SUN_AZ), math.sin(SUN_EL))


def in_planet_shadow(point):
    """True if a ring-plane point lies in Saturn's shadow (sphere approximation)."""
    s = sun_direction()
    along = sum(p * q for p, q in zip(point, s))
    if along > 0:
        return False
    off = [p - along * q for p, q in zip(point, s)]
    return sum(v * v for v in off) < 1.0


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported saturn rings graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid ' + key)
    for key in ('width', 'height', 'fps'):
        if not isinstance(job.get('output', {}).get(key), int) or job['output'][key] <= 0:
            raise ValueError('invalid output ' + key)
    timeline = job.get('timeline', [])
    if [b.get('controller_options', {}).get('shot') for b in timeline] != SHOTS:
        raise ValueError('saturn rings requires the planned shot order')
    cursor = 0
    for beat in timeline:
        if beat['controller'] != CONTROLLER or beat['start_frame'] != cursor or beat['end_frame'] <= cursor:
            raise ValueError('saturn rings timeline must have contiguous registered beats')
        cursor = beat['end_frame']
    if cursor != job['duration_frames']:
        raise ValueError('timeline duration mismatch')
    cache = job.get('canonical_state_cache', [])
    if len(cache) != job['duration_frames']:
        raise ValueError('canonical cache length mismatch')
    previous = -math.inf
    ids = {b['beat_id'] for b in timeline}
    for i, item in enumerate(cache):
        if item['canonical_frame'] != i or not item['active_beat_ids'] or not set(item['active_beat_ids']) <= ids:
            raise ValueError('invalid canonical frame')
        if not math.isfinite(item['simulation_time']) or item['simulation_time'] < previous:
            raise ValueError('simulation time must be monotone')
        previous = item['simulation_time']
