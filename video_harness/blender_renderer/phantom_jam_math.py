"""Frame-independent state for the approved 17-beat phantom-jam film.

Cars follow an optimal-velocity car-following model, dv/dt = a (V(h) - v),
with h the front-to-front headway (the model family used by Sugiyama et al.
2008). Parameters are tuned so a 230 m ring of 22 cars starts at ~30 km/h and
settles into a single ~6-car jam that drifts backward at ~23 km/h while free
cars run at ~38 km/h. Everything is integrated once, deterministically, and every
frame is looked up from the stored trajectories.

The plan's simulation_time is film time. Model time (tau) is tuned so the
first full stop lands on its sentence, jumps forward at the "a few minutes
later" cut, and runs faster in beat 16; rate changes are smooth here.

Ring coordinates: centre at the origin, cars drive counterclockwise seen from
above (+Z). The highway lies along +X, far from the ring.
"""
import math
import random

GRAPH = 'phantom-jam-blender-v1'
CONTROLLER = 'phantom-jam'
BEAT_COUNT = 17

# Car-following model (tuned; see research.md of the run).
VMAX, H_STOP, H_C, WIDTH, SENS = 10.6717, 5.173, 9.322, 1.7189, 2.1254
CAR = 3.9          # model car length after the 85 % scale
MIN_GAP = 1.2      # bumper gap drivers never go below
CAR_SCALE = 0.85

RING_L = 230.0
RING_N = 22
RING_R = RING_L / (2 * math.pi)
RING_DT = 0.02

HWY_L = 1000.0
HWY_N = 93
HWY_DT = 0.04
HWY_PRE = 420.0
HWY_Y = {'L': 1.8, 'R': -1.8}
HWY_ORIGIN = (0.0, 600.0)     # highway runs along +X at this y offset

CAR_A = 0                      # the car that first slows down
LANE_W = 4.4


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def window(t, a, b, fade=0.5):
    """1 inside [a, b] with smooth fade-in after a and fade-out before b."""
    return smooth((t - a) / fade) * (1 - smooth((t - (b - fade)) / fade))


_K = math.tanh((H_C - H_STOP) / WIDTH)


def optimal_velocity(h):
    return max(0.0, VMAX * (math.tanh((h - H_C) / WIDTH) + _K) / (1 + _K))


class Traffic:
    """Periodic single-lane road integrated with explicit Euler."""

    def __init__(self, length, count, dt, positions=None):
        self.L, self.N, self.dt = length, count, dt
        h0 = length / count
        self.x = list(positions) if positions else [i * h0 for i in range(count)]
        self.v = [optimal_velocity(h0)] * count
        self.t = 0.0
        self.events = []      # (car, t0, duration, target reduction)
        self.av = None        # dict(car, U, gap_time, gain)
        self.times, self.xs, self.vs = [], [], []
        self.record()

    def record(self):
        self.times.append(self.t)
        self.xs.append(list(self.x))
        self.vs.append(list(self.v))

    def headways(self):
        x, n = self.x, self.N
        return [x[(i + 1) % n] + (self.L if i == n - 1 else 0) - x[i] for i in range(n)]

    def step(self):
        h = self.headways()
        dt, t = self.dt, self.t
        for i in range(self.N):
            target, gain = optimal_velocity(h[i]), SENS
            for car, t0, duration, dv in self.events:
                if car == i and t0 <= t < t0 + duration:
                    target -= dv * math.sin(math.pi * (t - t0) / duration)
            if self.av and i == self.av['car']:
                target = min(self.av['U'], max(0.0, (h[i] - CAR - MIN_GAP) / self.av['gap_time']))
                gain = self.av['gain']
            v = max(0.0, self.v[i] + gain * (target - self.v[i]) * dt)
            self.v[i] = min(v, max(0.0, (h[i] - CAR - MIN_GAP) / dt * 0.5))
        for i in range(self.N):
            self.x[i] += self.v[i] * dt
        self.t += dt
        self.record()

    def run_until(self, t):
        while self.t < t - 1e-9:
            self.step()

    def pedal(self, t):
        """How hard each driver is deliberately pressing the brake (0..1)."""
        level = [0.0] * self.N
        for car, t0, duration, dv in self.events:
            if t0 <= t < t0 + duration:
                level[car] = max(level[car], min(1.0, .35 + dv) * math.sin(math.pi * (t - t0) / duration))
        return level

    def sample(self, t):
        """Unwrapped positions, speeds and accelerations at model time t."""
        k = clamp((t - self.times[0]) / self.dt, 0, len(self.times) - 1.000001)
        i = int(k)
        f = k - i
        j = min(i + 1, len(self.times) - 1)
        x = [a + (b - a) * f for a, b in zip(self.xs[i], self.xs[j])]
        v = [a + (b - a) * f for a, b in zip(self.vs[i], self.vs[j])]
        lo, hi = max(0, i - 5), min(len(self.times) - 1, i + 6)
        span = self.times[hi] - self.times[lo]
        acc = [(b - a) / span for a, b in zip(self.vs[lo], self.vs[hi])]
        return x, v, acc


def first_stop(traffic, after):
    for t, v in zip(traffic.times, traffic.vs):
        if t > after:
            slow = [i for i, s in enumerate(v) if s < 0.05]
            if slow:
                return t, slow[0]
    raise ValueError('the ring never jams')


def circular_mean(angles):
    return math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))


def solve_rate(base_rate, frames, target):
    """Bisection on the free rate parameter so that the model time covered by
    `frames` film frames equals `target`; base_rate(frame, r) gives tau/sec."""
    lo, hi = 0.02, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2
        covered = sum(base_rate(f, mid) for f in frames) / 30.0
        if covered < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


class Story:
    def __init__(self, timeline, fps):
        self.fps = fps
        beats = {b['controller_options']['beat_number']: b for b in timeline}
        self.start = {n: b['start_frame'] for n, b in beats.items()}
        self.end = {n: b['end_frame'] for n, b in beats.items()}
        self.total = self.end[BEAT_COUNT]
        s = lambda n: self.start[n] / fps
        self.s = {n: s(n) for n in beats}
        self.e = {n: self.end[n] / fps for n in beats}
        self._ring()
        self._highway()

    # ----- ring -------------------------------------------------------------
    def _ring(self):
        s, e, fps = self.s, self.e, self.fps
        ring0 = s[3]
        self.tap_small = s[5] + 3.6 - ring0          # the light touch on the brake
        self.hesitation = s[5] + 1.0 - ring0          # the car ahead re-accelerates late
        self.f_main = s[6] + 0.6                      # car A slows to ~28 km/h
        self.tau_main = self.f_main - ring0
        ring = Traffic(RING_L, RING_N, RING_DT)
        ring.events = [(CAR_A + 1, self.hesitation, 1.5, 0.05), (CAR_A, self.tap_small, 1.0, 0.04),
                       (CAR_A, self.tau_main, 2.0, 1.2)]
        ring.run_until(self.tau_main + 60)
        self.tau_stop, self.stopper = first_stop(ring, self.tau_main)
        # Film time of the full stop: the end of the first sentence of scene 9.
        self.f_stop = s[9] + 2.6
        start_slow, stop_frame = round(self.f_main * fps), round(self.f_stop * fps)

        def slow_rate(f, r):
            t = f / fps
            return 1 - (1 - r) * smooth((t - self.f_main) / 1.0)
        self.slow = solve_rate(slow_rate, range(start_slow, stop_frame), self.tau_stop - self.tau_main)
        # Jump a few minutes ahead at the cut into scene 10.
        self.tau_skip = self.tau_stop + 150.0
        self.f_av = s[15] + 0.3
        ring.run_until(self.tau_skip + (self.f_av - s[11]))
        self.tau_av = ring.t
        x, v, _ = ring.sample(self.tau_av)
        stopped = [i for i in range(RING_N) if v[i] < 0.5]
        tail = next(i for i in stopped if (i - 1) % RING_N not in stopped)
        # A car a few places upstream of the jam's tail, never car A itself.
        self.av_car = next(c for c in ((tail - k) % RING_N for k in (3, 4, 5)) if c != CAR_A)
        recent = [sum(vs) / RING_N for t, vs in zip(ring.times, ring.vs) if t > self.tau_av - 30]
        self.av_speed = sum(recent) / len(recent)
        ring.av = dict(car=self.av_car, U=self.av_speed, gap_time=1.2, gain=0.4)
        ring.run_until(self.tau_av + 60)
        self.ring = ring

        # Film -> model time for every ring frame.
        fast_start, fast_end = self.start[16], self.end[16]

        def fast_rate(f, r):
            t = f / fps
            return 1 + (r - 1) * smooth((t - s[16]) / 1.5)
        before = (fast_start - round(self.f_av * fps)) / fps
        self.fast = solve_rate(fast_rate, range(fast_start, fast_end), 50.0 - before)
        tau = {}
        t = 0.0
        for f in range(self.start[3], self.end[10]):
            tau[f] = t
            ft = f / fps
            if ft < self.f_main:
                rate = 1.0
            elif ft < self.f_stop:
                rate = slow_rate(f, self.slow)
            else:
                rate = self.slow + (1 - self.slow) * smooth((ft - self.f_stop) / 2.0)
            t += rate / fps
        t = self.tau_skip
        for f in range(self.start[11], self.end[16]):
            tau[f] = t
            t += (fast_rate(f, self.fast) if f >= fast_start else 1.0) / fps
        self.tau = tau

    # ----- highway ------------------------------------------------------------
    def _highway(self):
        rng = random.Random(20260925)
        self.lanes, starts = {}, {}
        h0 = HWY_L / HWY_N
        tap_f = self.s[17] + 3.0
        for lane in ('L', 'R'):
            starts[lane] = [i * h0 + rng.uniform(-.6, .6) for i in range(HWY_N)]
            traffic = Traffic(HWY_L, HWY_N, HWY_DT, starts[lane])
            traffic.run_until(HWY_PRE + self.total / self.fps + 1)
            self.lanes[lane] = traffic
        # Camera 1 chases the lane-R car that is rolling into a jam at frame 0.
        x, v, _ = self.lanes['R'].sample(HWY_PRE)
        ahead = lambda i: v[(i + 1) % HWY_N] < 1.0 and v[(i + 2) % HWY_N] < 1.0
        self.chase = next(i for i in range(HWY_N) if 3.0 < v[i] < 8.0 and ahead(i))
        # Final shot: a free-flowing stretch; one car ahead taps its brake.
        t_end = HWY_PRE + self.s[17]
        x, v, _ = self.lanes['R'].sample(t_end)
        order = sorted(range(HWY_N), key=lambda i: x[i] % HWY_L)
        best = None
        for k in range(HWY_N):
            stretch = [order[(k + j) % HWY_N] for j in range(12)]
            score = min(v[j] for j in stretch)
            if best is None or score > best[0]:
                best = (score, order[k], order[(k + 7) % HWY_N])
        _, self.final_car, self.tapper = best
        self.final_x0 = x[self.final_car]
        self.base_final = HWY_L * math.floor(self.final_x0 / HWY_L)
        x0 = self.lanes['R'].sample(HWY_PRE)[0][self.chase]
        self.base_open = HWY_L * math.floor(x0 / HWY_L)
        # Re-integrate lane R with the far brake tap included.
        tapped = Traffic(HWY_L, HWY_N, HWY_DT, starts['R'])
        tapped.events = [(self.tapper, HWY_PRE + tap_f, 1.2, 1.4)]
        tapped.run_until(HWY_PRE + self.total / self.fps + 1)
        self.lanes['R'] = tapped

    # ----- helpers --------------------------------------------------------------
    def ring_point(self, s, lift=0.0):
        a = s / RING_R
        return (RING_R * math.cos(a), RING_R * math.sin(a), lift), (-math.sin(a), math.cos(a), 0.0)

    def highway_base(self, beat):
        """Whole laps removed from unwrapped positions so each shot sits near x = 0."""
        return self.base_final if beat == 17 else self.base_open

    def highway_point(self, lane, s, reference, base=0.0):
        """Straightened lane position nearest to `reference` (camera x after `base`)."""
        x = s - base
        x -= HWY_L * round((x - reference) / HWY_L)
        return (HWY_ORIGIN[0] + x, HWY_ORIGIN[1] + HWY_Y[lane], 0.0)

    def ring_speed_field(self, x, v):
        cars = sorted(((xi % RING_L, vi) for xi, vi in zip(x, v)))
        def at(s):
            for (a, va), (b, vb) in zip(cars, cars[1:] + [(cars[0][0] + RING_L, cars[0][1])]):
                if a <= s < b or a <= s + RING_L < b:
                    s2 = s if a <= s < b else s + RING_L
                    return va + (vb - va) * (s2 - a) / (b - a)
            return cars[0][1]
        return at

    # ----- per-frame state --------------------------------------------------------
    def beat(self, frame):
        return next(n for n in range(1, BEAT_COUNT + 1) if self.start[n] <= frame < self.end[n])

    def state(self, frame):
        n = self.beat(frame)
        t = frame / self.fps
        st = dict(beat=n, film_time=t)
        if n in (1, 2, 17):
            st['place'] = 'highway'
            tau = HWY_PRE + t
            st['tau'] = tau
            lanes = {}
            for lane, traffic in self.lanes.items():
                x, v, a = traffic.sample(tau)
                lanes[lane] = (x, v, a, traffic.pedal(tau))
            st['lanes'] = lanes
            st['camera'] = self.highway_camera(n, t, lanes)
            st['camera_x'] = st['camera'][0][0] - HWY_ORIGIN[0]
            st['highway_base'] = self.highway_base(n)
            return st
        st['place'] = 'ring'
        tau = self.tau[frame]
        st['tau'] = tau
        x, v, a = self.ring.sample(tau)
        st.update(x=x, v=v, a=a, pedal=self.ring.pedal(tau))
        s = self.s
        st['markers'] = dict(
            a=window(t, s[5] + 3.0, self.e[10] + 1, .5) if n <= 10 else 0.0,
            stop=window(t, self.f_stop - .2, self.e[10] + 1, .4) if n <= 10 else 0.0,
            av=window(t, s[15] + 0.2, self.e[16] + 1, .6) if n >= 15 else 0.0)
        st['band'] = window(t, s[12] + 0.5, self.e[16] + 1, 1.0) if n >= 12 else 0.0
        st['arrows'] = window(t, s[12] + 2.0, self.e[12] - 0.3, .8) if n == 12 else 0.0
        st['jam_angle'] = self.jam_angle(tau)
        field = self.ring_speed_field(x, v)
        st['band_levels'] = [clamp((5.0 - field((k + .5) * RING_L / 96)) / 4.0) for k in range(96)]
        st['camera'] = self.ring_camera(n, t, frame, x)
        return st

    def raw_jam_angle(self, tau):
        """Angle of the slow cars' centre; steps whenever a car joins or leaves."""
        key = round(tau / RING_DT)
        cache = self.__dict__.setdefault('_jam_cache', {})
        if key not in cache:
            x, v, _ = self.ring.sample(tau)
            slow = [xi / RING_R for xi, vi in zip(x, v) if vi < 1.5]
            cache[key] = circular_mean(slow) if slow else x[self.stopper] / RING_R
        return cache[key]

    def jam_angle(self, tau):
        """Continuous jam position: the stepwise centre averaged over +-2 s."""
        samples = [self.raw_jam_angle(tau + .25 * k) for k in range(-8, 9)]
        total, base = 0.0, samples[0]
        for a in samples:
            total += base + wrap(a - base)
        return total / len(samples)

    # ----- cameras ------------------------------------------------------------------
    def smoothed(self, traffic, car, tau, span=1.2):
        xs = [traffic.sample(tau + d)[0][car] for d in (-span, -span / 2, 0, span / 2, span)]
        return sum(xs) / len(xs)

    def highway_camera(self, n, t, lanes):
        if n == 17:
            # Ride along the shoulder at the free-flow speed, looking far ahead.
            x0 = self.final_x0 - self.base_final - 25 + 10.0 * (t - self.s[17])
            eye = (HWY_ORIGIN[0] + x0, HWY_ORIGIN[1] - 9.0, 5.0)
            look = (HWY_ORIGIN[0] + x0 + 150, HWY_ORIGIN[1] - 0.5, 0.8)
            return eye, look, 45.0
        c = self.smoothed(self.lanes['R'], self.chase, HWY_PRE + t) - self.base_open
        cx = HWY_ORIGIN[0] + c
        low = ((cx - 10.5, HWY_ORIGIN[1] - 0.6, 1.9), (cx + 40, HWY_ORIGIN[1] - 1.0, 0.7), 35.0)
        high = ((cx - 30, HWY_ORIGIN[1] - 42, 38), (cx + 85, HWY_ORIGIN[1], 0.0), 32.0)
        u = smooth((t - self.s[2] - 0.3) / 7.0) if n == 2 else 0.0
        return blend(low, high, u)

    def ring_track(self, x, car, side=9.0, up=2.2, back=2.0, ahead=2.0, lens=35.0, lift=0.6):
        p, d = self.ring_point(x[car])
        n = (p[0] / RING_R, p[1] / RING_R, 0.0)
        eye = tuple(p[i] + n[i] * side - d[i] * back for i in range(3))
        eye = (eye[0], eye[1], up)
        look = (p[0] + d[0] * ahead, p[1] + d[1] * ahead, lift)
        return eye, look, lens

    def ring_arc_camera(self, arc, side, up, lens, back=0.0):
        p, d = self.ring_point(arc)
        n = (p[0] / RING_R, p[1] / RING_R, 0.0)
        eye = (p[0] + n[0] * side - d[0] * back, p[1] + n[1] * side - d[1] * back, up)
        return eye, (p[0], p[1], 0.5), lens

    def behind_arc(self, arc, back, side, up, ahead, lens=35.0):
        """Rear three-quarter view: behind `arc`, outside the ring, looking forward."""
        p, d = self.ring_point(arc - back)
        n = (p[0] / RING_R, p[1] / RING_R, 0.0)
        eye = (p[0] + n[0] * side, p[1] + n[1] * side, up)
        q, _ = self.ring_point(arc + ahead)
        return eye, (q[0], q[1], 0.6), lens

    def queue_arc(self, x, k):
        """Arc position k cars behind car A (fractional k interpolates cars)."""
        i = math.floor(k)
        f = k - i
        a = x[(CAR_A - i) % RING_N]
        b = x[(CAR_A - i - 1) % RING_N]
        # unwrap so both lie within one lap of car A
        a = x[CAR_A] - ((x[CAR_A] - a) % RING_L)
        b = x[CAR_A] - ((x[CAR_A] - b) % RING_L)
        return a + (b - a) * f

    def rig(self, n, t, frame, x):
        s, e = self.s, self.e
        behind = (CAR_A - self.stopper) % RING_N
        if n == 3:
            phi = math.radians(-60) + 0.035 * (t - s[3])
            return orbit(phi, 106.0, 38.0, 35.0)
        if n == 4:
            return self.ring_track(x, (CAR_A + 2) % RING_N, side=17.0, up=7.5, back=-4.0, ahead=-6.0, lens=35.0)
        if n == 5:
            return self.ring_track(x, CAR_A, side=6.0, up=2.6, back=8.0, ahead=4.0)
        if n == 6:
            return self.behind_arc(self.queue_arc(x, 0.5), 11.0, 5.5, 3.0, 8.0)
        if n == 7:
            k = 1 + 3 * smooth((t - s[7]) / (e[7] - s[7]))
            return self.behind_arc(self.queue_arc(x, k + 1.5), 13.0, 6.0, 4.2, 14.0)
        if n == 8:
            k = 4 + (behind - 5) * smooth((t - s[8]) / (e[8] - s[8]))
            return self.behind_arc(self.queue_arc(x, k + 1.5), 13.0, 6.0, 4.2, 14.0)
        if n == 9:
            k = (behind - 1) + smooth((t - s[9]) / 2.5)
            return self.behind_arc(self.queue_arc(x, k), 11.0 - 2.5 * smooth((t - s[9]) / 4), 5.5, 3.8, 3.0)
        if n == 10:
            a = x[CAR_A] / RING_R
            b = x[self.stopper] / RING_R
            mid = circular_mean([a, b]) + math.pi / 2
            return orbit(mid, 112.0, 50.0, 35.0)
        if n == 11:
            base = self.jam_angle(self.tau[self.start[11]])
            now = self.jam_angle(self.tau[frame])
            look_angle = base + 0.7 * wrap(now - base)
            eye = (15.0 * math.cos(base - 0.35), 15.0 * math.sin(base - 0.35), 8.5)
            p = (RING_R * math.cos(look_angle), RING_R * math.sin(look_angle), 0.0)
            return eye, p, 30.0
        if n in (12, 13):
            rot = 0.0 if n == 12 else 0.02 * (t - s[13])
            return top_down(self.top_heading + rot)
        if n == 14:
            tail = self.jam_tail_arc(self.tau[frame])
            return self.ring_arc_camera(tail - 13.0, 7.5, 4.2, 35.0, back=4.0)
        if n == 15:
            return self.ring_track(x, self.av_car, side=8.0, up=2.8, back=5.0, ahead=4.0)
        if n == 16:
            return top_down(self.top_heading + 0.02 * (e[13] - s[13]))
        raise ValueError(n)

    @property
    def top_heading(self):
        return 0.0

    def jam_tail_arc(self, tau):
        """A point just behind the jam, a smooth function of time."""
        return self.jam_angle(tau) * RING_R - 15.0

    def ring_camera(self, n, t, frame, x):
        """Each beat has a rig; the next rig takes over smoothly across boundaries."""
        s, e = self.s, self.e
        cam = self.rig(n, t, frame, x)
        blends = {3: 0, 4: 4.0, 5: 3.0, 6: 2.5, 7: 2.5, 8: 2.0, 9: 2.0, 10: 5.0,
                  11: 0, 12: 5.0, 13: 2.0, 14: 4.0, 15: 3.0, 16: 5.0}
        # Blends that start before the boundary, in the previous scene's pause.
        # The top-down view must settle early in beat 12: its direction check
        # measures the jam's turn on screen and a moving camera would swamp it.
        leads = {12: 3.5}
        following = n + 1
        if following in leads and t >= s[following] - leads[following]:
            u = smooth((t - (s[following] - leads[following])) / blends[following])
            return blend(cam, self.rig(following, t, frame, x), u)
        width = blends[n]
        start = s[n] - leads.get(n, 0.0)
        if width and t - start < width and n not in (3, 11):
            previous = self.rig(n - 1, t, frame, x)
            return blend(previous, cam, smooth((t - start) / width))
        return cam


def wrap(a):
    return (a + math.pi) % math.tau - math.pi


def orbit(phi, distance, elevation_deg, lens):
    el = math.radians(elevation_deg)
    eye = (distance * math.cos(el) * math.cos(phi), distance * math.cos(el) * math.sin(phi), distance * math.sin(el))
    return eye, (0.0, 0.0, -2.0), lens


def top_down(heading):
    # Slightly off vertical so the view keeps a stable up direction.
    eye = (6.0 * math.sin(heading), -6.0 * math.cos(heading), 150.0)
    return eye, (0.0, 0.0, 0.0), 35.0


def blend(a, b, u):
    lerp = lambda p, q: tuple(pi + (qi - pi) * u for pi, qi in zip(p, q))
    return lerp(a[0], b[0]), lerp(a[1], b[1]), a[2] + (b[2] - a[2]) * u


def validate_job(job):
    if job.get('scene_graph') != GRAPH:
        raise ValueError('unsupported phantom jam graph')
    for key in ('frame_count', 'duration_frames', 'canonical_fps'):
        if not isinstance(job.get(key), int) or job[key] <= 0:
            raise ValueError('invalid ' + key)
    for key in ('width', 'height', 'fps'):
        if not isinstance(job.get('output', {}).get(key), int) or job['output'][key] <= 0:
            raise ValueError('invalid output ' + key)
    timeline = job.get('timeline', [])
    numbers = [b.get('controller_options', {}).get('beat_number') for b in timeline]
    if numbers != list(range(1, BEAT_COUNT + 1)):
        raise ValueError('phantom jam requires the approved 17-beat order')
    cursor = 0
    for beat in timeline:
        if beat['controller'] != CONTROLLER or beat['start_frame'] != cursor or beat['end_frame'] <= cursor:
            raise ValueError('phantom jam timeline must have contiguous registered beats')
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
