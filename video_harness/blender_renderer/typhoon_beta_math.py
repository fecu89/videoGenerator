"""Frame-independent state for the typhoon beta-drift film (why typhoons head north-west).

The globe has radius 1 with north along +Z; longitude is measured eastward from +X.
The camera and every object live in the Earth-fixed frame, so the planet's spin is
shown by an axis with turning arrows instead of by moving the continents.

Teaching exaggerations, recorded in the run's research.md:
- the typhoon cloud, the wind darts and every arrow are drawn far larger than to scale;
- wind bands are single layers of darts on fixed headings, not a circulation model;
- the Coriolis strength is a violet tint growing with sin(latitude) plus sized glyphs;
- the Coriolis force on the north- and south-going air is a row of three arrows to the
  right of the motion, along the air's path, whose lengths follow sin(latitude);
- the beta gyres are two rings of darts, clockwise to the north-east and counterclockwise
  to the south-west, with a single arrow for the flow they drive across the centre;
- the storm's travel along its recurving track is a sped-up schematic, not a forecast.

Every value is a pure function of the frame, so frames can be rendered in any order.
No words are drawn; narration and subtitles carry them.
"""
import math
import random

GRAPH = 'typhoon-beta-blender-v1'
CONTROLLER = 'typhoon-beta'

SHOTS = ['s01a', 's02a', 's03a', 's04a', 's04b', 's05a', 's05b', 's06a', 's06b', 's07a',
         's08a', 's08b', 's09a', 's10a', 's11a', 's11b', 's12a', 's12b', 's13a', 's13b',
         's14a', 's14b', 's15a', 's15b', 's16a', 's17a', 's17b', 's18a']

LENS = 50.0
P0 = (12.0, 150.0)                         # where the typhoon forms (lat, lon in degrees)
TRACK = [(12, 150), (17, 142), (22, 134.5), (27, 129.5), (31.5, 129), (35.5, 133), (39, 140), (42, 148.5)]
TY_R = 0.13                                # drawn radius of the cloud shield (globe radii)
GHOST_R = 0.075
GYRE_R, GYRE_D = 0.100, 0.235              # gyre ring radius and its distance from the typhoon centre
FLOW_X = 0.185                             # east/west offset of the north- and south-going air
GYRE_ON_ROW = ((76.0, 0.315), (256.0, 0.295))   # (bearing, distance) of each gyre while it sits on its Coriolis row
GYRE_ROW_SCALE = 1.35                      # the rings are drawn larger there, to circle the three arrows
ARROW_HEAD = 0.075
CORIOLIS_LEN = 0.78                        # Coriolis arrow length per unit sin(latitude)
CORIOLIS_ROW, CORIOLIS_STEP = 3, 0.075     # arrows per side and their spacing along the air's path
TURN_LATS = (2.0, 15.0, 28.0, 41.0, 54.0)
TURN_LON = 170.0
SPIN_RATE = 1.1                            # turning arrows around the axis (rad/s, eastward)
TY_SPIN = 0.9                              # cloud rotation (rad/s, counterclockwise from above)
GYRE_SPIN = 1.3

# band name -> (count, lat start, lat end, lon change over one life, lon window, life in seconds, seed)
BANDS = {
    'Trade': (34, 27.0, 5.0, -24.0, (100.0, 222.0), 7.0, 3),      # north-east trades blow toward the south-west
    'West': (28, 33.0, 47.0, 44.0, (78.0, 186.0), 6.0, 5),        # westerlies blow toward the east-north-east
    'TradeS': (26, -27.0, -5.0, -24.0, (100.0, 222.0), 7.0, 7),   # south-east trades
    'WestS': (22, -33.0, -47.0, 44.0, (78.0, 186.0), 6.0, 9),
}
DART = 0.15                                # dart length


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


def lerp(a, b, s):
    return a + (b - a) * s


def mix(a, b, s):
    return tuple(x + (y - x) * s for x, y in zip(a, b))


def normal(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def point(lat, lon, radius=1.0):
    return tuple(radius * v for v in normal(lat, lon))


def offset(lat, lon, east, north):
    """Move a small distance (globe radii) east and north of a surface point."""
    lat2 = lat + math.degrees(north)
    return lat2, lon + math.degrees(east) / math.cos(math.radians((lat + lat2) / 2))


def heading(dlat, dlon, lat):
    """Angle from local east, counterclockwise, of a step (degrees of latitude and longitude)."""
    return math.degrees(math.atan2(dlat, dlon * math.cos(math.radians(lat))))


def bearing_to_psi(bearing):
    """Compass bearing (clockwise from north) -> angle from east, counterclockwise."""
    return 90.0 - bearing


def catmull(points, samples=48):
    out = []
    ext = [points[0], *points, points[-1]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for k in range(samples):
            u = k / samples
            out.append(tuple(.5 * ((2 * b) + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u * u + (-a + 3 * b - 3 * c + d) * u ** 3)
                             for a, b, c, d in zip(p0, p1, p2, p3)))
    out.append(tuple(float(v) for v in points[-1]))
    return out


class Track:
    """The recurving path, parameterised by distance travelled (0 at genesis, 1 at the end)."""
    def __init__(self):
        self.pts = catmull(TRACK)
        acc, self.s = 0.0, [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            pa, pb = normal(*a), normal(*b)
            acc += math.sqrt(sum((x - y) ** 2 for x, y in zip(pa, pb)))
            self.s.append(acc)
        self.length = acc
        self.s = [v / acc for v in self.s]

    def at(self, s):
        s = clamp(s)
        lo, hi = 0, len(self.s) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.s[mid] <= s:
                lo = mid
            else:
                hi = mid
        span = self.s[hi] - self.s[lo]
        u = 0.0 if span <= 0 else (s - self.s[lo]) / span
        (la0, lo0), (la1, lo1) = self.pts[lo], self.pts[hi]
        return lerp(la0, la1, u), lerp(lo0, lo1, u), heading(la1 - la0, lo1 - lo0, (la0 + la1) / 2)


def dart_table():
    rows = {}
    for band, (count, lat0, lat1, dlon, (w0, w1), life, seed) in BANDS.items():
        rng = random.Random(seed)
        rows[band] = [dict(lon=lerp(w0, w1, (i + rng.uniform(.1, .9)) / count), phase=(i * .381966 + rng.uniform(0, .08)) % 1.0,
                           jitter=rng.uniform(-1.5, 1.5)) for i in range(count)]
    return rows


class Story:
    def __init__(self, timeline, fps):
        self.fps = fps
        beats = {b['controller_options']['shot']: b for b in timeline}
        self.order = [b['controller_options']['shot'] for b in sorted(timeline, key=lambda b: b['start_frame'])]
        self.T = {k: b['start_frame'] / fps for k, b in beats.items()}
        self.E = {k: b['end_frame'] / fps for k, b in beats.items()}
        self.total = max(b['end_frame'] for b in timeline)
        self.track = Track()
        self.darts = dart_table()
        T, E = self.T, self.E
        # (time, distance along the track) of the real typhoon
        self.travel = [(T['s16a'] + .6, 0.0), (T['s17a'], .40), (T['s17b'], .60), (T['s18a'], .86), (E['s18a'] - .8, 1.0)]
        self.shots = self._shots()

    # ----- the typhoon -------------------------------------------------------------------
    def travelled(self, t):
        keys = self.travel
        if t <= keys[0][0]:
            return 0.0
        if t >= keys[-1][0]:
            return 1.0
        for i, ((t0, s0), (t1, s1)) in enumerate(zip(keys, keys[1:])):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                if i == 0:
                    u = u * u * (2 - u)             # ease in, leave at full speed
                elif i == len(keys) - 2:
                    u = 1 - (1 - u) ** 2            # ease out
                return lerp(s0, s1, u)
        return 1.0

    def typhoon(self, t):
        lat, lon, psi = self.track.at(self.travelled(t))
        return lat, lon, psi

    def ghost_s(self, t):
        T, E = self.T, self.E
        a = .60 * up(t, T['s04a'] + .3, E['s04a'] - T['s04a'] - .3)
        b = .12 * up(t, T['s04b'], E['s04b'] - T['s04b'])
        c = .24 * up(t, T['s05a'], E['s05b'] - T['s05a'])
        return a + b + c

    # ----- camera ------------------------------------------------------------------------
    def _shots(self):
        def fixed(eye0, eye1, look0, look1):
            """eye = (lat, lon, distance from the globe centre); look = (lat, lon) on the surface."""
            def shot(t, u):
                e, l = mix(eye0, eye1, smooth(u)), mix(look0, look1, smooth(u))
                return point(e[0], e[1], e[2]), point(l[0], l[1])
            return shot

        def chase(dist0, dist1, tilt, lead=(0.0, 0.0)):
            def shot(t, u):
                lat, lon, _ = self.typhoon(t)
                lat, lon = lat + lead[0], lon + lead[1]
                return point(lat - tilt, lon, lerp(dist0, dist1, smooth(u))), point(lat, lon)
            return shot
        la, lo = P0
        return {
            's01a': fixed((13, 153, 4.3), (13, 151, 3.9), (16, 153), (16, 151)),
            's02a': fixed((16, 150, 6.9), (18, 148, 7.4), (10, 150), (8, 148)),
            's03a': fixed((la - 4, lo, 3.6), (la - 3, lo, 3.1), (la + 1, lo), (la + 1, lo)),
            's04a': fixed((17, 143, 4.0), (20, 140, 4.1), (22, 143), (25, 140)),
            's04b': fixed((20, 140, 4.1), (23, 139, 4.2), (25, 140), (28, 139)),
            's05a': fixed((27, 138, 3.7), (29, 139, 3.5), (33, 138), (35, 139)),
            's05b': fixed((29, 139, 3.5), (30, 141, 3.4), (35, 139), (36, 141)),
            's06a': fixed((la - 2, lo - 2, 3.3), (la - 2, lo - 2, 3.1), (la + 3, lo - 2), (la + 3, lo - 2)),
            's06b': fixed((la - 2, lo - 2, 3.1), (la - 1, lo - 3, 3.0), (la + 3, lo - 2), (la + 4, lo - 3)),
            's07a': fixed((la - 1, lo - 3, 3.0), (la - 1, lo - 3, 2.75), (la + 3, lo - 3), (la + 3, lo - 3)),
            's08a': fixed((22, 156, 6.6), (24, 158, 6.9), (18, 156), (18, 158)),
            's08b': fixed((24, 158, 6.9), (26, 160, 6.6), (18, 158), (22, 160)),
            's09a': fixed((22, 164, 3.9), (28, 166, 3.7), (27, 166), (34, 168)),
            's10a': fixed((la - 3, lo, 2.9), (la - 2, lo, 2.36), (la, lo), (la, lo)),
            's11a': fixed((la - 2, lo, 2.36), (la - 2, lo, 2.42), (la, lo), (la, lo)),
            's11b': fixed((la - 2, lo, 2.42), (la - 2, lo, 2.46), (la, lo), (la, lo)),
            's12a': fixed((la - 2, lo, 2.46), (la - 1, lo, 2.60), (la, lo), (la + 1, lo)),
            's12b': fixed((la - 1, lo, 2.60), (la - 2, lo, 2.62), (la + 1, lo), (la, lo)),
            's13a': fixed((la - 2, lo, 2.62), (la - 2, lo, 2.60), (la, lo), (la, lo)),
            's13b': fixed((la - 2, lo, 2.60), (la - 2, lo, 2.64), (la, lo), (la, lo)),
            's14a': fixed((la - 2, lo, 2.64), (la - 2, lo, 2.62), (la, lo), (la, lo)),
            's14b': fixed((la - 2, lo, 2.62), (la - 1.5, lo - .5, 2.58), (la, lo), (la + .5, lo - .5)),
            's15a': fixed((la - 2, lo - 1, 3.0), (la - 2, lo - 2, 3.1), (la + 1, lo - 1), (la + 1, lo - 2)),
            's15b': fixed((la - 2, lo - 2, 3.1), (la - 2, lo - 2, 3.05), (la + 1, lo - 2), (la + 1, lo - 2)),
            's16a': chase(3.1, 3.6, 4.0, (2.0, -2.0)),
            's17a': fixed((22, 137, 4.1), (25, 137, 4.2), (27, 137), (30, 137)),
            's17b': fixed((25, 137, 4.2), (26, 139, 4.4), (30, 137), (31, 139)),
            's18a': fixed((22, 140, 4.9), (20, 141, 5.6), (27, 140), (26, 141)),
        }

    def camera(self, t):
        index = 0
        for i, key in enumerate(self.order):
            if t >= self.T[key]:
                index = i
        key = self.order[index]

        def evaluate(k):
            return self.shots[k](t, (t - self.T[k]) / (self.E[k] - self.T[k]))
        eye, look = evaluate(key)
        if index:
            previous = self.order[index - 1]
            length = self.E[key] - self.T[key]
            far = math.dist(self.shots[previous](self.T[key], 1.0)[0], self.shots[key](self.T[key], 0.0)[0])
            blend = min(1.5 if far > 1.5 else 1.0, .75 * length)
            s = smooth((t - self.T[key]) / blend)
            if s < 1:
                e0, l0 = evaluate(previous)
                eye, look = mix(e0, eye, s), mix(l0, look, s)
                # keep the eye outside the globe while it swings between two framings
                r = math.sqrt(sum(v * v for v in eye))
                floor = min(math.sqrt(sum(v * v for v in e0)), math.sqrt(sum(v * v for v in evaluate(key)[0])))
                if r < floor:
                    eye = tuple(v * floor / r for v in eye)
        return eye, look, key

    # ----- arrows --------------------------------------------------------------------------
    @staticmethod
    def arrow(xf, name, lat, lon, psi, length, alt, thick=1.0, back=0.0):
        """Shaft and head on the tangent plane; the tail sits `back` behind (lat, lon)."""
        rad = math.radians(psi)
        head = ARROW_HEAD * thick
        shaft = max(length - head, .001)
        head_scale = thick * (clamp(length / head) if length < head else 1.0)
        tail = offset(lat, lon, -back * math.cos(rad), -back * math.sin(rad))
        tip = offset(tail[0], tail[1], shaft * math.cos(rad), shaft * math.sin(rad))
        xf[name + 'Shaft'] = ('S', tail[0], tail[1], alt, psi, (shaft, thick, 1.0))
        xf[name + 'Head'] = ('S', tip[0], tip[1], alt, psi, (head_scale, head_scale, 1.0))

    # ----- everything ------------------------------------------------------------------------
    def state(self, frame):
        t = frame / self.fps
        T, E = self.T, self.E
        xf, op = {}, {}
        unit = (1.0, 1.0, 1.0)
        mech0, mech1 = T['s10a'], T['s15a']          # close study of the vortex
        inside = up(t, mech0 - .2, 1.0) * (1 - up(t, mech1, 1.0))

        xf['Earth'] = ('W', (0, 0, 0), (0, 0, 0), unit)

        # wind bands: every dart rides a fixed heading and is reborn upstream
        band_op = {
            'Trade': (1 - .55 * win(t, T['s08a'], T['s10a'] + 1.0, 1.0)) * (1 - inside),
            'West': up(t, T['s02a'] + .2, 1.0) * (1 - .5 * win(t, T['s08a'], T['s10a'] + 1.0, 1.0)) * (1 - inside),
            'TradeS': .8 * (win(t, T['s02a'] + .4, T['s03a'] + 1.0, .9) + .6 * win(t, T['s08a'] + .3, T['s10a'] + .6, .9)
                            + up(t, T['s18a'] + .5, 1.2)),
        }
        band_op['WestS'] = band_op['TradeS']
        for band, (count, lat0, lat1, dlon, window, life, seed) in BANDS.items():
            op[band] = clamp(band_op[band])
            psi = heading(lat1 - lat0, dlon, (lat0 + lat1) / 2)
            for i, row in enumerate(self.darts[band]):
                s = (t / life + row['phase']) % 1.0
                size = math.sin(math.pi * s) ** .6
                xf['%s%02d' % (band, i)] = ('S', lerp(lat0, lat1, s) + row['jitter'], row['lon'] + dlon * (s - .5), .014, psi,
                                           (size, size, 1.0))

        # the typhoon and the typical route sketched ahead of it
        lat, lon, track_psi = self.typhoon(t)
        grow = up(t, T['s03a'] + .5, 1.7)
        xf['Typhoon'] = ('S', lat, lon, .022, math.degrees(TY_SPIN * t), (grow, grow, 1.0))
        op['Typhoon'] = up(t, T['s03a'] + .4, .8)
        gs = self.ghost_s(t)
        glat, glon, _ = self.track.at(gs)
        xf['Ghost'] = ('S', glat, glon, .030, math.degrees(TY_SPIN * 1.3 * t), unit)
        op['Ghost'] = .85 * win(t, T['s04a'] + .2, T['s06a'] + .5, .5)
        xf['TrackDim'] = ('W', (0, 0, 0), (0, 0, 0), unit)
        op['TrackDim'] = .75 * win(t, T['s04a'] + .1, T['s08a'] + .6, .6)
        op['TrackDimReveal'] = .56 * up(t, T['s04a'] + .2, E['s04a'] - T['s04a'] - .2) + .44 * up(t, T['s04b'], E['s04b'] - T['s04b'] - .3)
        xf['TrackHot'] = ('W', (0, 0, 0), (0, 0, 0), unit)
        travelled = self.travelled(t)
        if t < T['s06a']:                             # the easy half: the north-east leg
            op['TrackHot'] = win(t, T['s05b'], T['s06a'], .5)
            op['HotLo'], op['HotHi'] = .55, 1.0
        elif t < T['s10a']:                           # the odd half: the north-west leg
            op['TrackHot'] = win(t, T['s06b'] + .3, T['s08a'] + .5, .5)
            op['HotLo'], op['HotHi'] = 0.0, .50
        else:                                         # the real storm leaves its trail
            op['TrackHot'] = up(t, T['s16a'] + .5, .5)
            op['HotLo'], op['HotHi'] = 0.0, travelled

        # wind against motion (scenes 6-7)
        swell = 1 + .07 * math.sin(4.0 * (t - T['s07a'])) * win(t, T['s07a'], E['s07a'], .5)
        self.arrow(xf, 'Wind', lat, lon, bearing_to_psi(225), .27 * up(t, T['s06a'] + .5, .7), .060, back=-.02)
        op['Wind'] = win(t, T['s06a'] + .5, T['s08a'] + .4, .5)
        self.arrow(xf, 'Move', lat, lon, bearing_to_psi(302), .27 * swell * up(t, T['s06b'] + .2, .7), .064, back=-.02)
        op['Move'] = win(t, T['s06b'] + .2, T['s08a'] + .4, .5) + up(t, T['s16a'] + .2, .6) * (1 - up(t, T['s17a'] - .3, .6))
        if t >= T['s10a']:                            # reused as the combined motion in scene 16
            self.arrow(xf, 'Move', lat, lon, track_psi, .26 * up(t, T['s16a'] + .2, .6), .064, back=-.02)

        # the spinning planet and how strongly it turns moving air at each latitude
        xf['Axis'] = ('W', (0, 0, 0), (0, 0, 0), unit)
        xf['Spin'] = ('W', (0, 0, 1.22), (0, 0, SPIN_RATE * t), unit)
        op['Axis'] = op['Spin'] = win(t, T['s08a'] + .6, T['s10a'] + .5, .7)
        xf['Coriolis'] = ('W', (0, 0, 0), (0, 0, 0), unit)
        op['Coriolis'] = up(t, T['s08b'], 1.1) * (1 - .35 * inside) * (1 - up(t, T['s15a'] + .2, 1.0))
        step = (E['s09a'] - T['s09a'] - .8) / len(TURN_LATS)
        for i, tl in enumerate(TURN_LATS):
            k = math.sin(math.radians(tl)) / math.sin(math.radians(TURN_LATS[-1]))
            size = (.25 + .75 * k) * up(t, T['s09a'] + .2 + i * step, .45)
            xf['Turn%d' % i] = ('S', tl, TURN_LON, .020, 0.0, (size, size, 1.0))
        op['Turn'] = win(t, T['s09a'], T['s10a'] + .6, .5)

        # air on the east side goes north, air on the west side goes south (scenes 11-12)
        e_shift = .15 * up(t, T['s12a'] + 1.0, E['s12a'] - T['s12a'] - 1.25)
        w_shift = .15 * up(t, T['s12b'] + 1.0, E['s12b'] - T['s12b'] - 1.25)
        e_lat, e_lon = offset(lat, lon, FLOW_X, -.095 + e_shift)
        w_lat, w_lon = offset(lat, lon, -FLOW_X, .095 - w_shift)
        self.arrow(xf, 'FlowE', e_lat, e_lon, 90.0, .19 * up(t, T['s11a'] + .3, .6), .050)
        self.arrow(xf, 'FlowW', w_lat, w_lon, -90.0, .19 * up(t, T['s11b'] + .2, .6), .050)
        gone = T['s13b'] + .6                         # the arrows stay while the gyres appear beside them
        op['FlowE'] = win(t, T['s11a'] + .3, gone, .5)
        op['FlowW'] = win(t, T['s11b'] + .2, gone, .5)
        # The Coriolis force points to the right of the motion and grows with sin(latitude).
        # One arrow per side in scene 11 (equal lengths); before the air moves, two more snap
        # into place along its path, so each side shows a row of three: longer toward the north,
        # shorter toward the south. The air then travels along its row.
        for side, sign, psi, first, row in (('CorE', 1.0, 0.0, T['s11a'] + 1.3, T['s12a']),
                                            ('CorW', -1.0, 180.0, T['s11b'] + 1.1, T['s12b'])):
            for k in range(CORIOLIS_ROW):
                c_lat, c_lon = offset(lat, lon, sign * FLOW_X, sign * CORIOLIS_STEP * k)
                if k == 0:
                    grow, slide = up(t, first, .6) * (1 + .22 * win(t, row, row + .34, .15)), 0.0
                else:
                    s = clamp((t - (row + .34 * k)) / .20)
                    grow, slide = (1 - (1 - s) ** 3) * (1 + .30 * math.sin(math.pi * s)), .10 * (1 - s) ** 2
                b_lat, b_lon = offset(c_lat, c_lon, sign * (.040 + slide), 0.0)
                self.arrow(xf, '%s%d' % (side, k), b_lat, b_lon, psi,
                           CORIOLIS_LEN * math.sin(math.radians(max(c_lat, 0.0))) * grow, .054)
            op[side] = win(t, first, gone, .5)

        # The pair of gyres first turns right on top of the Coriolis rows (the uneven arrows are
        # the turning), then swings round the storm to the north-east and south-west (scene 13).
        swing = up(t, T['s13b'], E['s13b'] - T['s13b'] - .3)
        show = up(t, T['s13a'] + .3, .9)
        for name, (b0, d0), b1, sense in (('GyreNE', GYRE_ON_ROW[0], 45.0, -1.0), ('GyreSW', GYRE_ON_ROW[1], 225.0, 1.0)):
            rad = math.radians(bearing_to_psi(lerp(b0, b1, swing)))
            dist = lerp(d0, GYRE_D, swing)
            size = show * lerp(GYRE_ROW_SCALE, 1.0, swing)
            g_lat, g_lon = offset(lat, lon, dist * math.cos(rad), dist * math.sin(rad))
            xf[name] = ('S', g_lat, g_lon, .060, math.degrees(sense * GYRE_SPIN * (t - T['s13a'])), (size, size, 1.0))
        op['Gyre'] = show * (1 - up(t, T['s15a'], .8))

        # the flow between the gyres pushes the centre north-west (scene 14), then stands
        # beside the westward steering by the trades (scene 15)
        settle = up(t, T['s15a'] + .1, .9)
        push_len = lerp(.32, .26, settle) * up(t, T['s14a'] + .4, 1.0) * (1 + .06 * math.sin(5.0 * t) * win(t, T['s14b'], E['s14b'], .4))
        self.arrow(xf, 'Push', lat, lon, bearing_to_psi(315), push_len, .070, thick=1.25, back=lerp(.16, -.07, settle))
        op['Push'] = win(t, T['s14a'] + .4, T['s16a'] + .7, .5)
        self.arrow(xf, 'Steer', lat, lon, bearing_to_psi(268), .27 * up(t, T['s15a'] + .5, .7), .066, thick=1.25, back=-.07)
        op['Steer'] = win(t, T['s15a'] + .5, T['s16a'] + .7, .5)

        eye, look, shot = self.camera(t)
        return dict(t=t, shot=shot, xf=xf, op=op, camera=(eye, look, LENS),
                    typhoon=(round(lat, 4), round(lon, 4), round(travelled, 5)))


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported typhoon beta graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid ' + key)
    for key in ('width', 'height', 'fps'):
        if not isinstance(job.get('output', {}).get(key), int) or job['output'][key] <= 0:
            raise ValueError('invalid output ' + key)
    timeline = job.get('timeline', [])
    if [b.get('controller_options', {}).get('shot') for b in timeline] != SHOTS:
        raise ValueError('typhoon beta requires the planned shot order')
    cursor = 0
    for beat in timeline:
        if beat['controller'] != CONTROLLER or beat['start_frame'] != cursor or beat['end_frame'] <= cursor:
            raise ValueError('typhoon beta timeline must have contiguous registered beats')
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
