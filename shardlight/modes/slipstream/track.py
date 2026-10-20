"""Seeded closed-loop tracks with validation, checkpoints, hazards and an optional risky shortcut.

Pipeline: perturbed ellipse control points -> closed Catmull-Rom spline -> uniform arc-length resampling ->
curvature / width profile -> validation (length, minimum radius, no self-overlap, usable start straight) ->
checkpoints, surfaces, hazards, shortcut.  Generation retries deterministically (seed, attempt) and falls back
to a plain oval, so every seed yields a drivable track.

World units are pixels.  Lateral offset ``d`` is signed (positive = to the right of travel on screen,
because y points down).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...core.rng import Rng
from .physics import DUST, OIL, ROUGH, SALT, TARMAC

SPACING = 10.0
SHOULDER = 30.0
MIN_LEN, MAX_LEN = 2600.0, 6200.0
MIN_RADIUS = 52.0
GATE_EVERY = 52              # samples between checkpoints (~520 px)
CELL = 64


@dataclass
class Hazard:
    kind: str                # oil | boulder | dust
    x: float
    y: float
    r: float


@dataclass
class Cut:
    ia: int                  # centerline index where the shortcut leaves the track
    ib: int                  # ... and rejoins
    ax: float
    ay: float
    bx: float
    by: float
    half: float = 25.0

    def length(self) -> float:
        return math.hypot(self.bx - self.ax, self.by - self.ay)

    def lateral(self, x: float, y: float) -> tuple[float, float]:
        """(distance to the corridor segment, parameter 0..1)."""
        dx, dy = self.bx - self.ax, self.by - self.ay
        l2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((x - self.ax) * dx + (y - self.ay) * dy) / l2))
        px, py = self.ax + dx * t, self.ay + dy * t
        return math.hypot(x - px, y - py), t


@dataclass
class Track:
    seed: int
    name: str
    pts: list[tuple[float, float]]
    width: list[float]
    tang: list[tuple[float, float]] = field(default_factory=list)
    norm: list[tuple[float, float]] = field(default_factory=list)
    kappa: list[float] = field(default_factory=list)
    s: list[float] = field(default_factory=list)
    length: float = 0.0
    surface: list[int] = field(default_factory=list)       # per-sample surface of the main track
    start: int = 0
    gates: list[int] = field(default_factory=list)         # required checkpoints (sample indices, in order)
    hazards: list[Hazard] = field(default_factory=list)
    cut: Cut | None = None
    grid: dict = field(default_factory=dict)
    bounds: tuple[float, float, float, float] = (0, 0, 0, 0)
    stats: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ geometry queries
    @property
    def n(self) -> int:
        return len(self.pts)

    def _build_grid(self) -> None:
        g: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(self.pts):
            g.setdefault((int(x // CELL), int(y // CELL)), []).append(i)
        self.grid = g

    def nearest(self, x: float, y: float, hint: int | None = None, window: int = 70) -> tuple[int, float]:
        """Index of the closest centerline sample and its distance (windowed around ``hint`` for continuity)."""
        pts = self.pts
        if hint is not None:
            best, bd = hint, 1e18
            for k in range(-window, window + 1):
                i = (hint + k) % self.n
                d = (pts[i][0] - x) ** 2 + (pts[i][1] - y) ** 2
                if d < bd:
                    best, bd = i, d
            return best, math.sqrt(bd)
        cx, cy = int(x // CELL), int(y // CELL)
        for ring in range(1, 14):
            best, bd = -1, 1e18
            for gx in range(cx - ring, cx + ring + 1):
                for gy in range(cy - ring, cy + ring + 1):
                    for i in self.grid.get((gx, gy), ()):
                        d = (pts[i][0] - x) ** 2 + (pts[i][1] - y) ** 2
                        if d < bd:
                            best, bd = i, d
            if best >= 0 and math.sqrt(bd) <= ring * CELL * 0.7:
                return best, math.sqrt(bd)
        i = min(range(self.n), key=lambda k: (pts[k][0] - x) ** 2 + (pts[k][1] - y) ** 2)
        return i, math.hypot(pts[i][0] - x, pts[i][1] - y)

    def lateral(self, i: int, x: float, y: float) -> float:
        nx, ny = self.norm[i]
        return (x - self.pts[i][0]) * nx + (y - self.pts[i][1]) * ny

    def probe(self, x: float, y: float, hint: int | None = None) -> tuple[str, int, float, int]:
        """Classify a point.  Returns (zone, index, lateral, surface) with zone in track|rough|cut|wall."""
        i, dist = self.nearest(x, y, hint)
        d = self.lateral(i, x, y)
        half = self.width[i] * 0.5
        if abs(d) <= half:
            return "track", i, d, self.surface[i]
        if abs(d) <= half + SHOULDER:
            zone, surf = "rough", ROUGH
        else:
            zone, surf = "wall", ROUGH
        if self.cut is not None:
            cd, _ = self.cut.lateral(x, y)
            if cd <= self.cut.half + 12:
                if cd <= self.cut.half:
                    return "cut", i, d, ROUGH
                if zone == "wall":
                    return "rough", i, d, ROUGH
        return zone, i, d, surf

    def hazard_surface(self, x: float, y: float) -> int | None:
        for h in self.hazards:
            if h.kind in ("oil", "dust") and (x - h.x) ** 2 + (y - h.y) ** 2 <= h.r * h.r:
                return OIL if h.kind == "oil" else DUST
        return None

    def point_at(self, s: float, lateral: float = 0.0) -> tuple[float, float, float]:
        i = int((s % self.length) / SPACING) % self.n
        nx, ny = self.norm[i]
        return self.pts[i][0] + nx * lateral, self.pts[i][1] + ny * lateral, math.atan2(self.tang[i][1], self.tang[i][0])

    def start_grid(self, count: int) -> list[tuple[float, float, float]]:
        """Staggered grid behind the start line (pole first)."""
        out = []
        for k in range(count):
            back = 22 + (k // 2) * 44
            lat = (-14 if k % 2 == 0 else 14) * (self.width[self.start] / 86.0)
            idx = (self.start - int(back / SPACING)) % self.n
            nx, ny = self.norm[idx]
            x, y = self.pts[idx]
            h = math.atan2(self.tang[idx][1], self.tang[idx][0])
            out.append((x + nx * lat, y + ny * lat, h))
        return out

    def gate_segment(self, gate: int) -> tuple[tuple[float, float], tuple[float, float]]:
        x, y = self.pts[gate]
        nx, ny = self.norm[gate]
        h = self.width[gate] * 0.5 + SHOULDER
        return (x - nx * h, y - ny * h), (x + nx * h, y + ny * h)

    def arc(self, i: int) -> float:
        return self.s[i]


# ---------------------------------------------------------------------------------------- generation
def _catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 +
                        (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1))


def _spline(ctrl: list[tuple[float, float]], per: int = 24) -> list[tuple[float, float]]:
    n = len(ctrl)
    out = []
    for i in range(n):
        p0, p1, p2, p3 = ctrl[(i - 1) % n], ctrl[i], ctrl[(i + 1) % n], ctrl[(i + 2) % n]
        for k in range(per):
            out.append(_catmull(p0, p1, p2, p3, k / per))
    return out


def _resample(poly: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    n = len(poly)
    seg = [math.hypot(poly[(i + 1) % n][0] - poly[i][0], poly[(i + 1) % n][1] - poly[i][1]) for i in range(n)]
    total = sum(seg)
    count = max(8, int(round(total / spacing)))
    step = total / count
    out = []
    acc = 0.0
    j = 0
    for k in range(count):
        target = k * step
        while acc + seg[j] < target:
            acc += seg[j]
            j = (j + 1) % n
        f = (target - acc) / max(seg[j], 1e-9)
        a, b = poly[j], poly[(j + 1) % n]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out


def _smooth(vals: list[float], k: int, circular: bool = True) -> list[float]:
    n = len(vals)
    out = []
    for i in range(n):
        acc = 0.0
        for d in range(-k, k + 1):
            acc += vals[(i + d) % n]
        out.append(acc / (2 * k + 1))
    return out


def _derive(t: Track) -> None:
    n = len(t.pts)
    t.tang, t.norm = [], []
    for i in range(n):
        a, b = t.pts[(i - 1) % n], t.pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1.0
        tx, ty = dx / d, dy / d
        t.tang.append((tx, ty))
        t.norm.append((-ty, tx))          # right-hand side on screen (y down)
    kap = []
    for i in range(n):
        h0, h1 = math.atan2(t.tang[i][1], t.tang[i][0]), math.atan2(t.tang[(i + 1) % n][1], t.tang[(i + 1) % n][0])
        dh = (h1 - h0 + math.pi) % math.tau - math.pi
        kap.append(dh / SPACING)
    t.kappa = _smooth(kap, 3)
    t.s = [i * SPACING for i in range(n)]
    t.length = n * SPACING
    xs = [p[0] for p in t.pts]
    ys = [p[1] for p in t.pts]
    m = 140
    t.bounds = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
    t._build_grid()


def _validate(t: Track) -> tuple[bool, str]:
    if not MIN_LEN <= t.length <= MAX_LEN:
        return False, f"length {t.length:.0f}"
    kmax = max(abs(k) for k in t.kappa)
    if kmax > 1.0 / MIN_RADIUS:
        return False, f"radius {1 / kmax:.0f}"
    n = t.n
    need = max(t.width) + 2 * SHOULDER + 8
    skip = int(380 / SPACING)
    for i in range(0, n, 2):
        xi, yi = t.pts[i]
        for j in range(i + skip, n, 2):
            if min(j - i, n - (j - i)) < skip:
                continue
            if abs(t.pts[j][0] - xi) < need and abs(t.pts[j][1] - yi) < need:
                if math.hypot(t.pts[j][0] - xi, t.pts[j][1] - yi) < need:
                    return False, "self-overlap"
    return True, "ok"


def _oval(rng: Rng, seed: int) -> Track:
    n = 210
    rx, ry = 560.0, 360.0
    pts = [(rx * math.cos(math.tau * i / n), ry * math.sin(math.tau * i / n)) for i in range(n)]
    pts = _resample(pts, SPACING)
    t = Track(seed, "Fallback Oval", pts, [90.0] * len(pts))
    _derive(t)
    return t


def _width_profile(t: Track, base: float, rng: Rng) -> list[float]:
    ph = rng.uniform(0, math.tau)
    w = []
    for i in range(t.n):
        wob = 0.5 + 0.5 * math.sin(i * 0.035 + ph)
        w.append(base - 22 * wob - 40 * min(1.0, abs(t.kappa[i]) * 60) * 0.4)
    w = _smooth(w, 6)
    return [max(66.0, min(110.0, v)) for v in w]


def _surfaces(t: Track, rng: Rng) -> list[int]:
    surf = [SALT] * t.n
    # tarmac service strips: the start straight plus a few stretches that reward the clean line
    def paint(a: int, b: int) -> None:
        for k in range(a, b):
            surf[k % t.n] = TARMAC
    paint(t.start - 20, t.start + 45)
    for _ in range(rng.randint(2, 4)):
        a = rng.randrange(t.n)
        paint(a, a + rng.randint(25, 60))
    return surf


def _pick_start(t: Track) -> int:
    best, score = 0, 1e9
    for i in range(0, t.n, 2):
        s = sum(abs(t.kappa[(i + k) % t.n]) for k in range(-14, 22))
        if s < score:
            best, score = i, s
    return best


def _add_gates(t: Track) -> None:
    t.gates = [(t.start + k * GATE_EVERY) % t.n for k in range(1, t.n // GATE_EVERY + 1)]
    if t.gates and (t.start - t.gates[-1]) % t.n < GATE_EVERY // 2:
        t.gates.pop()


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def _add_shortcut(t: Track, rng: Rng) -> None:
    """Find a chord across the infield that is much shorter than the lap section it replaces."""
    n = t.n
    best = None
    for span, a in ((sp, a0) for sp in (int(v / SPACING) for v in (420, 560, 700)) for a0 in range(0, n, 3)):
        if (a - t.start) % n < 60 or (t.start - a) % n < span + 60:
            continue                                   # keep the start/finish area clean
        b = (a + span) % n
        ax, ay = t.pts[a]
        bx, by = t.pts[b]
        ratio = math.hypot(bx - ax, by - ay) / (span * SPACING)
        if ratio > 0.8:
            continue
        ok = True
        for i in range(0, n, 2):
            rel = (i - a) % n
            if rel <= span + 26 or rel >= n - 26:      # the replaced span and its junctions
                continue
            if _seg_dist(t.pts[i][0], t.pts[i][1], ax, ay, bx, by) < t.width[i] * 0.5 + SHOULDER + 25 + 24:
                ok = False
                break
        if ok and (best is None or ratio < best[0]):
            best = (ratio, a, b, span)
    if best is None:
        return
    _, a, b, span = best
    t.cut = Cut(a, b, t.pts[a][0], t.pts[a][1], t.pts[b][0], t.pts[b][1])
    span_len = (b - a) % n
    t.gates = [g for g in t.gates if not 14 < (g - a) % n < span_len - 14]
    c = t.cut
    nx, ny = -(c.by - c.ay), c.bx - c.ax
    d = math.hypot(nx, ny) or 1.0
    for k in range(3, 18):                             # boulders flank the corridor: rough and risky
        f = k / 18
        if rng.chance(0.55):
            side = rng.pick((-1, 1)) * rng.uniform(8, 16)
            t.hazards.append(Hazard("boulder", c.ax + (c.bx - c.ax) * f + nx / d * side,
                                    c.ay + (c.by - c.ay) * f + ny / d * side, 6.0))


def _hazards(t: Track, rng: Rng) -> None:
    n = t.n
    straight = [i for i in range(n) if abs(t.kappa[i]) < 0.0035 and (i - t.start) % n > 80 and (t.start - i) % n > 40]
    for _ in range(min(4, len(straight) // 30)):
        i = rng.pick(straight)
        nx, ny = t.norm[i]
        lat = rng.uniform(-0.3, 0.3) * t.width[i]
        t.hazards.append(Hazard("oil", t.pts[i][0] + nx * lat, t.pts[i][1] + ny * lat, rng.uniform(14, 20)))
    for _ in range(rng.randint(1, 2)):
        i = rng.randrange(n)
        t.hazards.append(Hazard("dust", t.pts[i][0], t.pts[i][1], rng.uniform(70, 100)))
    for _ in range(rng.randint(3, 6)):
        i = rng.randrange(n)
        if (i - t.start) % n < 30 or (t.start - i) % n < 30:
            continue
        nx, ny = t.norm[i]
        lat = (t.width[i] * 0.5 - 5) * rng.pick((-1, 1))
        t.hazards.append(Hazard("boulder", t.pts[i][0] + nx * lat, t.pts[i][1] + ny * lat, 6.5))


def _attempt(seed: int, attempt: int) -> Track | None:
    rng = Rng(seed).child("track", attempt)
    n = rng.randint(9, 13)
    base_r = rng.uniform(380, 520)
    aspect = rng.uniform(1.15, 1.7)
    h2, h3 = rng.uniform(0.2, 0.42), rng.uniform(0.1, 0.3)
    p2, p3 = rng.uniform(0, math.tau), rng.uniform(0, math.tau)
    ctrl = []
    for i in range(n):
        a = math.tau * i / n + rng.uniform(-0.12, 0.12)
        r = base_r * (1 + h2 * math.sin(2 * a + p2) + h3 * math.sin(3 * a + p3) + rng.uniform(-0.16, 0.16))
        ctrl.append((r * aspect * math.cos(a), r * math.sin(a)))
    pts = _resample(_spline(ctrl), SPACING)
    t = Track(seed, f"Salt Run {seed % 1000:03d}", pts, [90.0] * len(pts))
    _derive(t)
    t.width = _width_profile(t, 96.0, rng)
    ok, why = _validate(t)
    t.stats["attempt"] = attempt
    t.stats["validation"] = why
    return t if ok else None


def generate(seed: int, max_attempts: int = 40, shortcut: bool = True) -> Track:
    """Deterministic, validated track for ``seed``."""
    track: Track | None = None
    for attempt in range(max_attempts):
        track = _attempt(seed, attempt)
        if track is not None:
            break
    rng = Rng(seed).child("decor")
    if track is None:
        track = _oval(rng, seed)
        track.width = [92.0] * track.n
        track.stats["fallback"] = True
    track.start = _pick_start(track)
    track.surface = _surfaces(track, rng)
    _add_gates(track)
    if shortcut:
        _add_shortcut(track, rng)
    _hazards(track, rng)
    track.stats.update(length=track.length, min_radius=1.0 / max(1e-6, max(abs(k) for k in track.kappa)),
                       shortcut=track.cut is not None, gates=len(track.gates))
    return track


def validate(t: Track) -> list[str]:
    """Independent re-check used by tests and by the scene before accepting a mod-supplied seed."""
    issues = []
    ok, why = _validate(t)
    if not ok:
        issues.append(why)
    if len(t.gates) < 4:
        issues.append("too few checkpoints")
    if t.cut is not None:
        for g in t.gates:
            rel = (g - t.cut.ia) % t.n
            if 14 < rel < (t.cut.ib - t.cut.ia) % t.n - 14:
                issues.append("required gate inside the shortcut span")
        if t.cut.length() < 120:
            issues.append("shortcut too short")
    for h in t.hazards:
        z = t.probe(h.x, h.y)[0]
        if h.kind == "oil" and z != "track":
            issues.append("oil patch off the track")
    sx, sy, sh = t.start_grid(1)[0]
    if t.probe(sx, sy)[0] != "track":
        issues.append("start grid off the track")
    return issues
