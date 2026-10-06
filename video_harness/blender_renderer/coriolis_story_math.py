"""Frame-independent state for the approved 23-beat Coriolis (plane) story.

Coordinates follow the vorticity globe: globe-local +Y is north, +X is
longitude 0 and longitude grows toward -Z (eastward). Rotating by +angle
about Y turns the globe eastward, which is counterclockwise seen from above
the north pole.

Two frames of reference are shown with one scene graph:
  view root  = Rx(tilt) @ Ry(-psi)          (the observer; camera stays put)
  inertial   = children of the view root   (fixed in space)
  ground     = Ry(Phi) under the view root (turns with the Earth)
The apparent globe angle is A = Phi - psi. In the inertial view psi is
constant, so the globe visibly turns; in the ground view A is held, so the
globe looks still and inertial objects drift westward.

Everything here is a teaching model with compressed time: the first flight
(North Pole to Seoul's latitude) lasts FLIGHT_SECONDS of film while the Earth
turns FLIGHT_TURN degrees, matching ~5.8 h at 1000 km/h. While the ground
view hides the Earth's turn, its rate is chosen so the closing shot returns
to the opening composition with the track's end near the front.
"""
import math

GRAPH = 'coriolis-story-blender-v1'
CONTROLLER = 'coriolis-story'
BEAT_COUNT = 23
R = 3.0
PLANE_ALT = 0.14
SEOUL = (37.57, 126.98)
FLIGHT_TURN = 88.0
ARRIVAL = (SEOUL[0], SEOUL[1] - FLIGHT_TURN)
EQUATOR_START = (0.0, 80.0)   # Indian Ocean; keeps the second track clear of the first
SECOND_FLIGHT_LAT = 60.0
SECOND_FLIGHT_SECONDS = 20.0
SECOND_SETUP_FRONT = 115.0
TRACK2_FRONT = 95.0           # second track near centre so its eastward bend reads
ROUTE_FRONT = 120.0          # Seoul's meridian near centre for the straight-vs-actual contrast
COMPASS_FRONT = 40.0
LATITUDE_FRONT = 80.0
TYPHOON = (20.0, 135.0)
EQUATOR_LOW = (0.0, 150.0)
OPENING_SPIN = 10.0      # deg/s while the plane waits on the pole
PRE_SECOND_SPIN = 1.8    # deg/s while the plane waits on the equator
RESTING_SPIN = 0.3       # deg/s while the ground view hides the turn
RETURN_SPIN = 1.5        # deg/s while Scene 7 shows the inertial view again
SWIRL_SPIN = 40.0        # deg/s, counterclockwise from above
TAKEOFF = 0.8
PSI_RETURN = 4.5         # seconds to orbit back to the opening composition


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def smooth_integral(x):
    """Integral of smooth() from 0 to x (x may exceed 1)."""
    if x <= 0:
        return 0.0
    if x <= 1:
        return x ** 3 - x ** 4 / 2
    return 0.5 + (x - 1)


def hermite(a0, m0, a1, m1, duration, tau):
    s = clamp(tau / duration)
    h00 = 2 * s ** 3 - 3 * s ** 2 + 1
    h10 = s ** 3 - 2 * s ** 2 + s
    h01 = -2 * s ** 3 + 3 * s ** 2
    h11 = s ** 3 - s ** 2
    return h00 * a0 + h10 * duration * m0 + h01 * a1 + h11 * duration * m1


def point(lat, lon, r=R):
    """Globe-local position for latitude/longitude in degrees."""
    p, l = math.radians(lat), math.radians(lon)
    return (r * math.cos(p) * math.cos(l), r * math.sin(p), -r * math.cos(p) * math.sin(l))


def east(lat, lon):
    l = math.radians(lon)
    return (-math.sin(l), 0.0, -math.cos(l))


def north(lat, lon):
    p, l = math.radians(lat), math.radians(lon)
    return (-math.sin(p) * math.cos(l), math.cos(p), math.sin(p) * math.sin(l))


def up(lat, lon):
    return point(lat, lon, 1.0)


def rot_y(v, degrees):
    a = math.radians(degrees)
    x, y, z = v
    return (x * math.cos(a) + z * math.sin(a), y, -x * math.sin(a) + z * math.cos(a))


def rot_x(v, degrees):
    a = math.radians(degrees)
    x, y, z = v
    return (x, y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a))


def add(a, b, k=1.0):
    return tuple(x + k * y for x, y in zip(a, b))


def scale(a, k):
    return tuple(x * k for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    n = math.sqrt(dot(a, a))
    return tuple(x / n for x in a) if n > 1e-12 else a


def tangent(v, normal):
    return norm(add(v, normal, -dot(v, normal)))


def slerp(a, b, k):
    a, b = norm(a), norm(b)
    c = clamp(dot(a, b), -1, 1)
    w = math.acos(c)
    if w < 1e-6:
        return a
    s = math.sin(w)
    return add(scale(a, math.sin((1 - k) * w) / s), b, math.sin(k * w) / s)


def front_to_angle(lon):
    """Apparent globe angle that puts `lon` on the camera-facing meridian."""
    return -90.0 - lon


def angle_to_front(angle):
    return ((-90.0 - angle + 180.0) % 360.0) - 180.0


def nearest(value, reference):
    """value + 360k closest to reference."""
    return value + 360.0 * round((reference - value) / 360.0)


def track1(u):
    """First flight, ground frame: lat/lon at progress u in [0, 1]."""
    return 90.0 - (90.0 - SEOUL[0]) * u, SEOUL[1] - FLIGHT_TURN * u


def progress(t, start, duration):
    """Constant-speed progress with a short smooth takeoff; 1 at start+duration."""
    tau = t - start
    if tau <= 0:
        return 0.0
    v = 1.0 / (duration - TAKEOFF / 2)
    if tau < TAKEOFF:
        return v * tau * tau / (2 * TAKEOFF)
    return clamp(v * (tau - TAKEOFF / 2))


class Story:
    """Pure timing and geometry for one timeline; evaluated per frame."""

    def __init__(self, timeline, fps):
        self.fps = fps
        beats = sorted(timeline, key=lambda b: b['start_frame'])
        self.s = {i + 1: b['start_frame'] / fps for i, b in enumerate(beats)}
        self.e = {i + 1: b['end_frame'] / fps for i, b in enumerate(beats)}
        self.beats = beats
        s, e = self.s, self.e
        self.t_depart = s[2] + 1.8
        self.t_arrive = s[4] + 7.0
        self.flight_seconds = self.t_arrive - self.t_depart
        self.flight_spin = FLIGHT_TURN / self.flight_seconds
        self.t_depart2 = s[11] + 3.0
        self.t_land2 = self.t_depart2 + SECOND_FLIGHT_SECONDS
        # Earth spin knots (time, new rate, blend seconds); ground_spin solved below.
        self.ground_spin = 1.0
        # In the ground view the turn is invisible; slowing it after the gold
        # path has drifted away lets Scene 7 return to the opening framing
        # with the track still facing the camera.
        self.knots = [(self.t_depart - 2.0, self.flight_spin, 2.0),
                      (s[5] + 5.0, RESTING_SPIN, 1.0),
                      (s[7], RETURN_SPIN, 1.0),
                      (s[9], PRE_SECOND_SPIN, 1.5),
                      (self.t_depart2 - 1.0, self.flight_spin, 1.0),
                      (s[12] + 2.5, None, 1.0),
                      (s[22] - 1.5, self.flight_spin, 1.0)]
        self._solve_ground_spin()
        self._build_view()

    # ----- Earth rotation -----------------------------------------------
    def spin_rate(self, t):
        rate = OPENING_SPIN
        for t0, new, width in self.knots:
            new = self.ground_spin if new is None else new
            rate += (new - rate) * smooth((t - t0) / width)
        return rate

    def phi(self, t):
        """Integral of spin_rate from 0 to t (degrees)."""
        total = OPENING_SPIN * t
        rate = OPENING_SPIN
        for t0, new, width in self.knots:
            new = self.ground_spin if new is None else new
            total += (new - rate) * width * smooth_integral((t - t0) / width)
            rate = new
        return total

    def _solve_ground_spin(self):
        s = self.s
        end = s[22] + PSI_RETURN
        self.ground_spin = 0.0
        base = self.phi(end) - self.phi(self.t_depart)
        self.ground_spin = 1.0
        per = self.phi(end) - self.phi(self.t_depart) - base
        # The closing view (inertial again, psi back to the opening) shows
        # front longitude 127 - turned; aim for ~60E so the track end is near.
        wanted = SEOUL[1] - 60.0
        m = math.ceil((1.0 * per + base - wanted) / 360.0)
        while (wanted + 360 * m - base) / per < 1.0:
            m += 1
        self.ground_spin = (wanted + 360 * m - base) / per

    # ----- observer (apparent angle A, psi) -------------------------------
    def _build_view(self):
        s, e = self.s, self.e
        a_depart = front_to_angle(SEOUL[1])
        segs = []
        segs.append((0.0, ('inertial_abs', a_depart - self.phi(self.t_depart))))
        segs.append((s[5], ('freeze', 2.0)))
        segs.append((s[5] + 2.0, ('hold',)))
        segs.append((s[6], ('goto', front_to_angle(ROUTE_FRONT), 5.0, 'still')))
        segs.append((s[6] + 5.0, ('hold',)))
        target9 = front_to_angle(SECOND_SETUP_FRONT) - (self.phi(e[9]) - self.phi(s[9] + 6.0))
        segs.append((s[9], ('goto', target9, 6.0, 'spin')))
        segs.append((s[9] + 6.0, ('inertial',)))
        segs.append((s[12], ('goto', front_to_angle(TRACK2_FRONT), 3.5, 'still')))
        segs.append((s[12] + 3.5, ('hold',)))
        segs.append((s[14], ('goto', front_to_angle(COMPASS_FRONT), 2.5, 'still')))
        segs.append((s[14] + 2.5, ('hold',)))
        segs.append((s[16], ('goto', front_to_angle(LATITUDE_FRONT), 3.0, 'still')))
        segs.append((s[16] + 3.0, ('hold',)))
        segs.append((s[19], ('goto', front_to_angle(TYPHOON[1]), 4.0, 'still')))
        segs.append((s[19] + 4.0, ('hold',)))
        segs.append((s[20] + 6.0, ('goto', front_to_angle(EQUATOR_LOW[1]), 3.0, 'still')))
        segs.append((s[20] + 9.0, ('hold',)))
        segs.append((s[22], ('psi_goto', PSI_RETURN)))
        segs.append((s[22] + PSI_RETURN, ('psi_hold',)))
        segs.append((s[23], ('freeze', 2.0)))
        segs.append((s[23] + 2.0, ('hold',)))
        self.psi0 = self.phi(self.t_depart) - a_depart
        self.segments = []
        for i, (t0, rule) in enumerate(segs):
            if i == 0:
                anchor = (rule[1], None)
            else:
                prev = self.segments[-1]
                h = 1e-4
                a0 = self._eval(prev, t0)
                m0 = (self._eval(prev, t0) - self._eval(prev, t0 - h)) / h
                anchor = (a0, m0)
            self.segments.append((t0, rule, anchor))

    def _eval(self, seg, t):
        t0, rule, (a0, m0) = seg
        kind = rule[0]
        if kind == 'inertial_abs':
            return a0 + self.phi(t)
        if kind == 'inertial':
            return a0 + self.phi(t) - self.phi(t0)
        if kind == 'hold':
            return a0
        if kind == 'freeze':
            d = rule[1]
            return hermite(a0, m0, a0 + m0 * d / 2, 0.0, d, t - t0)
        if kind == 'ramp':
            d = rule[1]
            return a0 + self.spin_rate(t0) * d * smooth_integral((t - t0) / d)
        if kind == 'goto':
            target, d, end_slope = rule[1], rule[2], rule[3]
            target = nearest(target, a0 + m0 * d / 2)
            m1 = self.spin_rate(t0 + d) if end_slope == 'spin' else 0.0
            return hermite(a0, m0, target, m1, d, t - t0)
        if kind == 'psi_goto':
            d = rule[1]
            psi_a = self.phi(t0) - a0
            psi_m = self.spin_rate(t0) - m0
            target = nearest(self.psi0, psi_a + psi_m * d / 2)
            return self.phi(t) - hermite(psi_a, psi_m, target, 0.0, d, t - t0)
        if kind == 'psi_hold':
            return self.phi(t) - nearest(self.psi0, self.phi(t0) - a0)
        raise ValueError(kind)

    def apparent(self, t):
        seg = max((sg for sg in self.segments if sg[0] <= t), key=lambda sg: sg[0])
        return self._eval(seg, t)

    def psi(self, t):
        return self.phi(t) - self.apparent(t)

    # ----- camera ----------------------------------------------------------
    def keyed(self, t, start, keys):
        value = start
        for t0, target, width in keys:
            value += (target - value) * smooth((t - t0) / width)
        return value

    def tilt(self, t):
        s = self.s
        return self.keyed(t, 50.0, [(s[9], 30.0, 4.0), (s[14], 40.0, 2.5), (s[15], -40.0, 3.0),
                                    (s[16], 12.0, 3.0), (s[19], 20.0, 4.0), (s[20] + 6.0, 8.0, 3.0),
                                    (s[22], 50.0, PSI_RETURN)])

    def ortho(self, t):
        s = self.s
        return self.keyed(t, 16.0, [(s[4] + 2.0, 13.5, 5.0), (s[5], 16.0, 2.0), (s[14], 6.5, 2.5),
                                    (s[16], 16.0, 3.0), (s[19], 7.5, 4.0), (s[20] + 6.0, 12.0, 3.0),
                                    (s[22], 16.0, PSI_RETURN)])

    def screen(self, ground_point, t):
        p = rot_y(ground_point, self.phi(t))
        p = rot_y(p, -self.psi(t))
        return rot_x(p, self.tilt(t))

    def camera_center(self, t):
        s = self.s
        arrival = self.screen(point(*ARRIVAL), self.t_arrive)
        target = (0.45 * arrival[0], 0.45 * arrival[1])
        k = smooth((t - (s[4] + 2.0)) / 5.0) * (1 - smooth((t - s[5]) / 2.0))
        return (target[0] * k, target[1] * k)

    # ----- flights -----------------------------------------------------------
    def flight1(self, t):
        return progress(t, self.t_depart, self.flight_seconds)

    def flight2(self, t):
        return progress(t, self.t_depart2, SECOND_FLIGHT_SECONDS)

    def second_offset(self, lat):
        """Eastward lead (deg) from angular momentum about the axis.

        Northward at a steady rate dphi/dt with conserved angular momentum,
        the ground-relative eastward drift obeys dlambda/dphi = Omega tan^2(phi)
        / (dphi/dt), so lambda = (Omega / dphi/dt)(tan phi - phi)."""
        steady = SECOND_FLIGHT_LAT / (SECOND_FLIGHT_SECONDS - TAKEOFF / 2)
        p = math.radians(lat)
        return math.degrees(self.flight_spin / steady * (math.tan(p) - p))

    def track2(self, w):
        lat = SECOND_FLIGHT_LAT * w
        return lat, EQUATOR_START[1] + self.second_offset(lat)

    # ----- plane pose (inertial coordinates of the view root) ---------------
    def plane(self, t):
        s = self.s
        rp = R + PLANE_ALT
        phi = self.phi
        lam0 = SEOUL[1] + phi(self.t_depart)
        g_arrive = point(*ARRIVAL, rp)
        head_arrive_i = tuple(-x for x in north(ARRIVAL[0], lam0))
        head_arrive_g = rot_y(head_arrive_i, -phi(self.t_arrive))
        g_eq = point(*EQUATOR_START, rp)
        end2 = self.track2(1.0)
        g_end2 = point(*end2, rp)

        def ground(p, h):
            return rot_y(p, phi(t)), rot_y(h, phi(t))

        def head2(w):
            a, b = self.track2(max(0.0, w - .002)), self.track2(min(1.0, w + .002))
            if w <= 0:
                return north(*EQUATOR_START)
            return tangent(add(point(*b, 1), point(*a, 1), -1), up(*self.track2(w)))

        inertial_end = point(ARRIVAL[0], lam0, rp)
        if t < self.t_depart:
            lam = math.radians(SEOUL[1] + phi(t))
            return (0.0, rp, 0.0), (math.cos(lam), 0.0, -math.sin(lam))
        if t < self.t_arrive:
            lat, _ = track1(self.flight1(t))
            return point(lat, lam0, rp), tuple(-x for x in north(lat, lam0))
        if t < s[9] + 1.0:
            return ground(g_arrive, head_arrive_g)
        if t < s[9] + 6.0:
            k = smooth((t - s[9] - 1.0) / 5.0)
            p = scale(slerp(g_arrive, g_eq, k), rp)
            h = tangent(add(scale(head_arrive_g, 1 - k), north(*EQUATOR_START), k), norm(p))
            return ground(p, h)
        if t < s[22] + 1.0:
            w = self.flight2(t)
            lat, lon = self.track2(w)
            return ground(point(lat, lon, rp), head2(w))
        final_g = (rot_y(g_end2, phi(t)), rot_y(head2(1.0), phi(t)))
        south_end = tuple(-x for x in north(ARRIVAL[0], lam0))
        if t < s[23] + 1.0:
            k = smooth((t - s[22] - 1.0) / 2.5)
            p = scale(slerp(final_g[0], inertial_end, k), rp)
            h = tangent(add(scale(final_g[1], 1 - k), south_end, k), norm(p))
            return p, h
        k = smooth((t - s[23] - 1.0) / 2.0)
        target = rot_y(g_arrive, phi(t))
        p = scale(slerp(inertial_end, target, k), rp)
        h = tangent(add(scale(south_end, 1 - k), rot_y(head_arrive_g, phi(t)), k), norm(p))
        return p, h

    # ----- fades and reveals ------------------------------------------------
    def fade(self, t, start, events):
        value = start
        for t0, width, target in events:
            value += (target - value) * smooth((t - t0) / width)
        return value

    def state(self, frame):
        t = frame / self.fps
        s = self.s
        n = max(i for i in s if s[i] <= t + 1e-9)
        f = self.fade
        u1 = self.flight1(t)
        w2 = self.flight2(t)
        compass_front = angle_to_front(self.apparent(s[14] + 2.5))
        latitude_front = angle_to_front(self.apparent(s[16] + 3.0))
        st = dict(
            t=t, beat=n, phi=self.phi(t), psi=self.psi(t), apparent=self.apparent(t),
            tilt=self.tilt(t), ortho=self.ortho(t), center=self.camera_center(t),
            aim_lon=SEOUL[1] + self.phi(min(t, self.t_depart)),
            inertial_lon=SEOUL[1] + self.phi(self.t_depart),
            flight1=u1, flight2=w2, compass_lon=compass_front, latitude_lon=latitude_front,
            swirl=SWIRL_SPIN * max(0.0, t - s[20]),
            marker=smooth((t - s[8] - 1.5) / 9.5),
            fades=dict(
                aim=f(t, 1, [(self.t_depart, 3, 0)]),
                inertial=f(t, 0, [(self.t_depart, .6, 1), (s[5] + 2, 6, 0),
                                  (s[22] + 1, 2, 1), (s[23] + 2, 4, 0)]),
                seoul=f(t, 1, [(s[9], 1.5, 0)]),
                axis=f(t, 0, [(s[3], 1, 1), (s[19], 1.5, 0)]),
                # Spin direction is shown while the Earth is seen turning, and
                # again while the axis is compared with the local vertical.
                spin_arrow=f(t, 0, [(s[3], 1, 1), (s[5], 1, 0),
                                    (s[9] + 6, 1, 1), (s[12], 1, 0), (s[17], 1, 1), (s[19], 1.5, 0)]),
                arrival=f(t, 0, [(self.t_arrive, 1, 1), (s[9], 1.5, 0)]),
                route=f(t, 0, [(s[7], .4, 1), (s[9], 1.5, 0)]),
                track1=f(t, 0, [(s[6] + 4.5, .5, 1), (s[9], 1.5, 0), (s[13], 1, 1), (s[14], 1.5, 0), (s[23] + .5, 2, 1)]),
                marker=f(t, 0, [(s[8] + 1, .5, 1), (s[9], 1.5, 0)]),
                plane=f(t, 1, [(s[14], 1, 0), (s[22] + 3.0, 1, 1)]),
                aim2=f(t, 0, [(s[9] + 6, 2, 1), (s[13], 1, 0)]),
                ground_speed=[f(t, 0, [(s[10] + .5, 1, 1), (s[12], 1.5, 0)])] +
                             [f(t, 0, [(s[11] + .2 + .8 * k, .8, 1), (s[12], 1.5, 0)]) for k in range(3)],
                plane_east=f(t, 0, [(s[10] + 1, 1, 1), (s[12], 1.5, 0)]),
                track2=f(t, 0, [(s[12], 1.5, 1), (s[14], 1.5, 0)]),
                plane_arrow=f(t, 0, [(s[12] + 2, 1, 1), (s[13], .6, 0)]),
                pair_a=f(t, 0, [(s[13], .4, 1), (s[13] + 1.6, .4, .35), (s[13] + 3.2, .4, 1), (s[14], 1, 0)]),
                pair_b=f(t, 0, [(s[13], .4, .35), (s[13] + 1.6, .4, 1), (s[13] + 3.2, .4, 1), (s[14], 1, 0)]),
                compass_n=f(t, 0, [(s[14] + .8, .4, 1), (s[16], 1.5, 0)]),
                compass_s=f(t, 0, [(s[15] + 2.8, .4, 1), (s[16], 1.5, 0)]),
                latitudes=f(t, 0, [(s[16] + 2.8, .4, 1), (s[17], 1, .35), (s[18], .8, 1), (s[19], 1.5, 0)]),
                forces=f(t, 0, [(s[16] + 5.3, .4, 1), (s[17], 1, .35), (s[18], .8, 1), (s[19], 1.5, 0)]),
                verticals=f(t, 0, [(s[17] + .5, 1, 1), (s[19], 1.5, 0)]),
                components=f(t, 0, [(s[17] + 1.8, .4, 1), (s[18], .4, .55), (s[18] + .6, .5, 1), (s[19], 1.5, 0)]),
                inflow=f(t, 0, [(s[19] + 3.8, .4, 1), (s[20] + 1, 1, .35), (s[22], 1.5, 0)]),
                swirl=f(t, 0, [(s[20], 1.5, 1), (s[22], 1.5, 0)]),
                band=f(t, 0, [(s[20] + 7, 2, .13), (s[22], 1.5, 0)]),
                equator_inflow=f(t, 0, [(s[21] + .8, .4, 1), (s[22], 1.5, 0)]),
            ),
            reveals=dict(
                track1=smooth((t - s[6] - 5.0) / 5.0) if t < s[23] else 1.0,
                route=smooth((t - s[7]) / 1.5),
                track2=w2,
                compass_n=smooth((t - s[14] - 1) / 3.0),
                compass_s=smooth((t - s[15] - 3) / 2.5),
                latitudes=smooth((t - s[16] - 3) / 2.5),
                forces=smooth((t - s[16] - 5.5) / 2.5),
                components=smooth((t - s[17] - 2) / 4.0),
                inflow=smooth((t - s[19] - 4) / 4.0),
                equator_inflow=smooth((t - s[21] - 1) / 4.0),
            ),
        )
        pos, head = self.plane(t)
        st['plane_pos'], st['plane_head'] = pos, head
        st['axis_width'] = 1 + .6 * smooth((t - s[17]) / 1.0) * (1 - smooth((t - s[19]) / 1.5))
        return st


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported coriolis story graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid ' + key)
    for key in ('width', 'height', 'fps'):
        if not isinstance(job.get('output', {}).get(key), int) or job['output'][key] <= 0:
            raise ValueError('invalid output ' + key)
    timeline = job.get('timeline', [])
    numbers = [b.get('controller_options', {}).get('beat_number') for b in timeline]
    if numbers != list(range(1, BEAT_COUNT + 1)):
        raise ValueError('coriolis story requires the approved 23-beat order')
    cursor = 0
    for beat in timeline:
        if beat['controller'] != CONTROLLER or beat['start_frame'] != cursor or beat['end_frame'] <= cursor:
            raise ValueError('coriolis timeline must have contiguous registered beats')
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
