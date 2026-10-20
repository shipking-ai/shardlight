"""Pure-software 3D rasteriser helpers for the Lens finale.

This module deliberately avoids any GPU dependency: camera math, projection,
depth sorting, fog, flat shading and a post-processing pass all run on the
shared 480x270 frame using numpy + pygame primitives.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pygame

RENDER_W, RENDER_H = 480, 270
FOV_DEFAULT = 60.0
NEAR = 0.15
FAR = 60.0


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def wrap(v: float, lo: float, hi: float) -> float:
    span = hi - lo
    if span <= 0:
        return lo
    while v < lo:
        v += span
    while v >= hi:
        v -= span
    return v


def _to_vec3(v: Any) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64).reshape(-1)
    if a.size < 3:
        a = np.pad(a, (0, 3 - a.size))
    return a[:3].copy()


def _cam_params(cam: Any) -> tuple[float, float, Sequence[float]]:
    if hasattr(cam, "yaw") and hasattr(cam, "pitch") and hasattr(cam, "pos"):
        return float(cam.yaw), float(cam.pitch), cam.pos
    if isinstance(cam, (tuple, list)):
        if len(cam) == 3 and all(not isinstance(x, (tuple, list, np.ndarray)) for x in cam):
            # (yaw, pitch, pos)
            try:
                float(cam[0]); float(cam[1])
                return float(cam[0]), float(cam[1]), cam[2]
            except (TypeError, ValueError):
                pass
        # treat as a position
        return 0.0, 0.0, cam
    return 0.0, 0.0, (0.0, 0.0, 0.0)


@dataclass
class Camera:
    yaw: float = 0.0
    pitch: float = 0.0
    pos: Any = (0.0, 0.0, 0.0)
    fov: float = FOV_DEFAULT

    def position(self) -> np.ndarray:
        return _to_vec3(self.pos)


class ChaseCam(Camera):
    def __init__(self, yaw: float = 0.0, pitch: float = 0.0, pos: Any = (0.0, 0.0, 0.0),
                 target: Any = (0.0, 0.0, 0.0), speed: float = 6.0, smoothing: float = 0.12,
                 fov: float = FOV_DEFAULT):
        super().__init__(yaw=yaw, pitch=pitch, pos=pos, fov=fov)
        self._pos = _to_vec3(pos)
        self._yaw = float(yaw)
        self._pitch = float(pitch)
        self.target = _to_vec3(target)
        self.speed = float(speed)
        self.smoothing = float(smoothing)
        self._target_yaw = float(yaw)
        self._target_pitch = float(pitch)

    @property
    def pos(self):
        return tuple(float(x) for x in self._pos)

    @pos.setter
    def pos(self, value):
        self._pos = _to_vec3(value)

    @property
    def yaw(self):
        return self._yaw

    @yaw.setter
    def yaw(self, value):
        self._yaw = float(value)

    @property
    def pitch(self):
        return self._pitch

    @pitch.setter
    def pitch(self, value):
        self._pitch = float(value)

    def set_target(self, pos: Any, yaw: float | None = None, pitch: float | None = None) -> None:
        self.target = pos
        if yaw is not None:
            self._target_yaw = float(yaw)
        else:
            self._target_yaw = self._yaw
        if pitch is not None:
            self._target_pitch = float(pitch)

        else:
            self._target_pitch = self._pitch

    def follow(self, target: Any, yaw: float | None = None, pitch: float | None = None) -> None:
        self.set_target(target, yaw=yaw, pitch=pitch)

    def update(self, *args, **kwargs) -> None:
        dt = 1.0 / 60.0
        target = None
        if "dt" in kwargs:
            dt = float(kwargs["dt"])
        if "target" in kwargs:
            target = kwargs["target"]
        positional = list(args)
        if len(positional) == 1:
            if isinstance(positional[0], (int, float, np.integer, np.floating)):
                dt = float(positional[0])
            else:
                target = positional[0]
        elif len(positional) >= 2:
            a, b = positional[0], positional[1]
            if isinstance(a, (int, float, np.integer, np.floating)) and not isinstance(b, (int, float, np.integer, np.floating)):
                dt = float(a); target = b
            elif not isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
                target = a; dt = float(b)
            else:
                dt = float(a); target = b
        if target is not None:
            self.target = target
        tpos = _to_vec3(self.target)
        # ease position
        k = clamp(self.speed * dt, 0.0, 1.0)
        self._pos = self._pos + (tpos - self._pos) * k
        # ease yaw/pitch toward target if provided
        if hasattr(self, "_target_yaw"):
            self._yaw = self._yaw + (self._target_yaw - self._yaw) * k
        if hasattr(self, "_target_pitch"):
            self._pitch = self._pitch + (self._target_pitch - self._pitch) * k

    def snap(self, pos: Any, yaw: float = 0.0, pitch: float = 0.0) -> None:
        self._pos = _to_vec3(pos)
        self._yaw = float(yaw)
        self._pitch = float(pitch)


def project_point(v: Any, yaw: float = 0.0, pitch: float = 0.0, cam: Any = (0.0, 0.0, 0.0),
                  fov: float = FOV_DEFAULT, w: int = RENDER_W, h: int = RENDER_H,
                  near: float = NEAR) -> tuple[float, float, float]:
    """Project a 3D point to screen space.

    Returns (screen_x, screen_y, view_z). Points behind the camera are clamped
    to the near plane so callers can cull with ``z <= near``.
    """
    p = _to_vec3(v)
    c = _to_vec3(cam if not hasattr(cam, "pos") else cam.pos)
    # if cam is a Camera, honour its yaw/pitch defaults when not overridden
    if hasattr(cam, "yaw") and yaw == 0.0 and pitch == 0.0:
        yaw = float(cam.yaw)
        pitch = float(cam.pitch)
        c = _to_vec3(cam.pos)
    x, y, z = (p - c).tolist()
    # yaw about Y
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy + z * sy, -x * sy + z * cy
    # pitch about X
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    if z < near:
        z = near
    f = (w * 0.5) / math.tan(math.radians(fov) * 0.5)
    # use vertical fov based on height if fov given as horizontal; keep simple
    sx = w * 0.5 + (x / z) * f
    sy = h * 0.5 - (y / z) * f
    return (float(sx), float(sy), float(z))


def project(verts: Any, cam: Any = None, fov: float = FOV_DEFAULT, w: int = RENDER_W,
            h: int = RENDER_H) -> list[tuple[float, float, float]]:
    """Project a list/array of vertices. ``cam`` may be Camera or tuple."""
    yaw, pitch, pos = _cam_params(cam if cam is not None else Camera())
    if hasattr(cam, "yaw"):
        yaw, pitch, pos = float(cam.yaw), float(cam.pitch), cam.pos
    out = []
    for v in verts:
        out.append(project_point(v, yaw=yaw, pitch=pitch, cam=pos, fov=fov, w=w, h=h))
    return out


def sort_polys(polys: Sequence[Any]) -> list[Any]:
    """Sort polygons back-to-front by depth (largest z first)."""

    def depth(p: Any) -> float:
        if isinstance(p, dict):
            if "z" in p:
                return float(p["z"])
            if "depth" in p:
                return float(p["depth"])
            for key in ("verts", "vertices", "points"):
                v = p.get(key)
                if v:
                    vals = [ (x[2] if isinstance(x, (tuple, list, np.ndarray)) else 0.0) for x in v ]
                    return float(sum(vals) / len(vals))
        if hasattr(p, "z"):
            return float(p.z)
        if hasattr(p, "depth"):
            return float(p.depth)
        return 0.0

    return sorted(list(polys), key=depth, reverse=True)


def fog_blend(t: float, near_color: Any, far_color: Any) -> tuple[int, int, int]:
    t = clamp(float(t))
    out = []
    for a, b in zip(near_color, far_color):
        out.append(int(round(float(a) + (float(b) - float(a)) * t)))
    # preserve length if colors differ in arity
    if len(out) < len(near_color):
        out.extend(int(x) for x in list(near_color)[len(out):])
    return tuple(out)


def flat_shade(normal: Any, key: Any, fill: Any) -> tuple[int, int, int]:
    n = _to_vec3(normal)
    nn = float(np.linalg.norm(n))
    if nn > 1e-9:
        n = n / nn
    if isinstance(key, (tuple, list, np.ndarray)):
        lk = _to_vec3(key)
        ln = float(np.linalg.norm(lk))
        if ln > 1e-9:
            lk = lk / ln
        ndotl = float(np.dot(n, lk))
        shade = 0.22 + 0.78 * clamp(ndotl, 0.0, 1.0)
    else:
        try:
            shade = float(key)
        except (TypeError, ValueError):
            shade = 0.6
        shade = clamp(shade, 0.0, 1.0)
    out = []
    for c in fill:
        out.append(int(clamp(float(c) * shade, 0, 255)))
    return tuple(out)


def _poly_verts(poly: Any) -> list[Any]:
    if isinstance(poly, dict):
        for key in ("verts", "vertices", "points", "v"):
            if key in poly and poly[key] is not None:
                return list(poly[key])
    if hasattr(poly, "verts"):
        return list(poly.verts)
    if hasattr(poly, "vertices"):
        return list(poly.vertices)
    return []


def _poly_color(poly: Any) -> tuple[int, int, int]:
    if isinstance(poly, dict):
        c = poly.get("color", poly.get("colour", (180, 180, 200)))
    else:
        c = getattr(poly, "color", (180, 180, 200))
    return tuple(int(x) for x in c)


class HallMesh:
    """Procedural hall mesh: floor, walls, plinths, Lens, debris."""

    def __init__(self, debris: int = 40):
        self.debris = int(debris)
        self.polys: list[dict[str, Any]] = []
        self._build()

    def _add(self, verts, color, normal=None) -> None:
        self.polys.append({"verts": [tuple(v) for v in verts], "color": tuple(int(x) for x in color),
                           "normal": tuple(normal) if normal is not None else None})

    def _build(self) -> None:
        # floor tiles
        for x in range(-6, 7):
            for z in range(0, 16):
                self._add(
                    [(x, 0, z), (x + 1, 0, z), (x + 1, 0, z + 1), (x, 0, z + 1)],
                    (46, 40, 52), (0, 1, 0),
                )
        # ceiling
        for x in range(-6, 7):
            for z in range(0, 16):
                self._add(
                    [(x, 6, z), (x, 6, z + 1), (x + 1, 6, z + 1), (x + 1, 6, z)],
                    (24, 20, 34), (0, -1, 0),
                )
        # side walls (segmented)
        for z in range(0, 16):
            self._add([( -6, 0, z), (-6, 6, z), (-6, 6, z + 1), (-6, 0, z + 1)],
                      (34, 28, 46), (-1, 0, 0))
            self._add([(7, 0, z), (7, 0, z + 1), (7, 6, z + 1), (7, 6, z)],
                      (34, 28, 46), (1, 0, 0))
        # 8 plinths along the hall
        for i in range(8):
            px = -5 + i * 1.4
            pz = 4 + (i % 3) * 2
            for (x0, z0, x1, z1) in (((px, pz), (px + 0.6, pz), (px + 0.6, pz + 0.6), (px, pz + 0.6)),):
                pass
            self._add([(px, 0, pz), (px + 0.6, 0, pz), (px + 0.6, 1.2, pz), (px, 1.2, pz)],
                      (90, 74, 52), (-1, 0, 0))
            self._add([(px + 0.6, 0, pz), (px + 0.6, 0, pz + 0.6), (px + 0.6, 1.2, pz + 0.6), (px + 0.6, 1.2, pz)],
                      (90, 74, 52), (1, 0, 0))
            self._add([(px + 0.6, 0, pz + 0.6), (px, 0, pz + 0.6), (px, 1.2, pz + 0.6), (px + 0.6, 1.2, pz + 0.6)],
                      (90, 74, 52), (0, 0, 1))
            self._add([(px, 0, pz + 0.6), (px, 0, pz), (px, 1.2, pz), (px, 1.2, pz + 0.6)],
                      (90, 74, 52), (-1, 0, 0))
            self._add([(px, 1.2, pz), (px + 0.6, 1.2, pz), (px + 0.6, 1.2, pz + 0.6), (px, 1.2, pz + 0.6)],
                      (120, 100, 70), (0, 1, 0))
        # Lens (hexagonal prism) at the far end
        cx, cz = 0.5, 14.0
        r = 1.6
        ring = []
        for i in range(6):
            a = (i / 6.0) * (2 * math.pi)
            ring.append((cx + math.cos(a) * r, cz + math.sin(a) * r))
        for i in range(6):
            x0, z0 = ring[i]
            x1, z1 = ring[(i + 1) % 6]
            self._add([(x0, 2.0, z0), (x1, 2.0, z1), (x1, 5.5, z1), (x0, 5.5, z0)],
                      (230, 200, 120), (math.cos((i + 0.5) / 6 * 2 * math.pi), 0,
                                       math.sin((i + 0.5) / 6 * 2 * math.pi)))
        # lens top/bottom
        top = [(x, 5.5, z) for (x, z) in ring]
        self._add(top, (255, 235, 170), (0, 1, 0))
        bot = [(x, 2.0, z) for (x, z) in ring]
        self._add(list(reversed(bot)), (180, 150, 90), (0, -1, 0))
        # debris
        rng = random.Random(1234)
        for _ in range(self.debris):
            x = rng.uniform(-5.5, 6.0)
            z = rng.uniform(1.0, 15.0)
            y = rng.uniform(0.0, 4.5)
            s = rng.uniform(0.15, 0.45)
            col = (rng.randrange(60, 120), rng.randrange(50, 100), rng.randrange(80, 150))
            self._add(
                [(x, y, z), (x + s, y, z), (x + s, y + s, z), (x, y + s, z)],
                col, (0, 0, 1),
            )
            self._add(
                [(x, y, z + s), (x, y + s, z + s), (x + s, y + s, z + s), (x + s, y, z + s)],
                col, (0, 0, 1),
            )

    def poly_count(self) -> int:
        return len(self.polys)


def render(surf: pygame.Surface, mesh: Any, cam: Any, post: bool = True,
           fov: float = FOV_DEFAULT, fog_color: tuple[int, int, int] = (18, 16, 26)) -> None:
    """Render ``mesh`` into ``surf`` from ``cam``. ``post`` toggles the post pass."""
    w, h = surf.get_size()
    yaw, pitch, pos = _cam_params(cam)
    if hasattr(cam, "yaw"):
        yaw = float(cam.yaw)
        pitch = float(cam.pitch)
        pos = cam.pos

    polys = getattr(mesh, "polys", None)
    if polys is None:
        polys = list(mesh) if not isinstance(mesh, (str, bytes)) else []

    # transform + depth
    transformed: list[tuple[float, list[tuple[float, float]], tuple[int, int, int]]] = []
    for poly in polys:
        verts = _poly_verts(poly)
        if not verts:
            continue
        pts: list[tuple[float, float]] = []
        zs: list[float] = []
        skip = False
        for v in verts:
            sx, sy, sz = project_point(v, yaw=yaw, pitch=pitch, cam=pos, fov=fov, w=w, h=h)
            if sz <= NEAR:
                skip = True
                break
            pts.append((sx, sy))
            zs.append(sz)
        if skip or len(pts) < 3:
            continue
        avg_z = float(sum(zs) / len(zs))
        color = _poly_color(poly)
        normal = poly.get("normal") if isinstance(poly, dict) else getattr(poly, "normal", None)
        if normal is not None:
            color = flat_shade(normal, (0.3, 0.8, 0.6), color)
        # fog
        t = clamp((avg_z - 2.0) / (FAR - 2.0), 0.0, 1.0)
        color = fog_blend(t, color, fog_color)
        transformed.append((avg_z, pts, color))

    transformed.sort(key=lambda item: item[0], reverse=True)

    surf.fill(fog_color)
    for _avg_z, pts, color in transformed:
        try:
            pygame.draw.polygon(surf, color, pts)
        except (TypeError, ValueError):
            continue

    if post:
        _post_pass(surf)


def _post_pass(surf: pygame.Surface) -> None:
    w, h = surf.get_size()
    try:
        arr = pygame.surfarray.pixels3d(surf)
    except Exception:
        return
    try:
        f = arr.astype(np.float32)
        # warm grade
        f[:, :, 0] *= 1.06
        f[:, :, 1] *= 1.02
        f[:, :, 2] *= 0.94
        # vignette
        xs = (np.arange(w, dtype=np.float32) - (w * 0.5)) / (w * 0.5)
        ys = (np.arange(h, dtype=np.float32) - (h * 0.5)) / (h * 0.5)
        vig = 1.0 - 0.42 * (xs[:, None] ** 2 + ys[None, :] ** 2)
        vig = np.clip(vig, 0.35, 1.0)
        f *= vig[:, :, None]
        # bloom-ish bright lift (cheap): add a faint blurred bright layer
        bright = np.where(f > 170, f - 170, 0.0)
        # 3x3 box blur via slicing
        blurred = bright.copy()
        blurred[1:, :, :] += bright[:-1, :, :]
        blurred[:-1, :, :] += bright[1:, :, :]
        blurred[:, 1:, :] += bright[:, :-1, :]
        blurred[:, :-1, :] += bright[:, 1:, :]
        blurred *= 0.12
        f = f + blurred
        # grain
        rng = np.random.default_rng(12345)
        grain = rng.normal(0.0, 3.0, (w, h, 1)).astype(np.float32)
        f = f + grain
        f = np.clip(f, 0, 255).astype(np.uint8)
        arr[:] = f
    finally:
        del arr
