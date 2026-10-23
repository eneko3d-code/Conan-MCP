"""16-bit heightmaps: PNG I/O (pure Python), world<->grid mapping and sculpting brushes.

Unreal landscapes store heights as uint16 where 32768 is the actor's Z and one
unit equals ``scale_z / 128`` centimetres. Brushes operate on a rectangular
``HeightGrid`` region so the same code drives the native C++ path (region
read/write) and the heightmap-file path.
"""

import math
import random
import struct
import zlib
from array import array
from typing import Optional, Tuple

MID = 32768
MAX_H = 65535
LANDSCAPE_ZSCALE = 1.0 / 128.0


class HeightGrid:
    """Row-major uint16 grid covering quads [x0, x0+width) x [y0, y0+height)."""

    def __init__(self, width: int, height: int, data=None, x0: int = 0, y0: int = 0):
        self.width, self.height, self.x0, self.y0 = int(width), int(height), int(x0), int(y0)
        n = self.width * self.height
        self.data = array("H", data if data is not None else [MID] * n)
        if len(self.data) != n:
            raise ValueError(f"Height data has {len(self.data)} values, expected {n}")

    def get(self, x: int, y: int) -> int:
        return self.data[(y - self.y0) * self.width + (x - self.x0)]

    def set(self, x: int, y: int, v: float):
        self.data[(y - self.y0) * self.width + (x - self.x0)] = max(0, min(MAX_H, int(round(v))))

    def copy(self) -> "HeightGrid":
        return HeightGrid(self.width, self.height, array("H", self.data), self.x0, self.y0)

    def crop(self, x0: int, y0: int, x1: int, y1: int) -> "HeightGrid":
        """Sub-grid with inclusive bounds, clamped to this grid."""
        x0, y0 = max(x0, self.x0), max(y0, self.y0)
        x1, y1 = min(x1, self.x0 + self.width - 1), min(y1, self.y0 + self.height - 1)
        if x1 < x0 or y1 < y0:
            raise ValueError("Region is outside the heightmap")
        out = HeightGrid(x1 - x0 + 1, y1 - y0 + 1, None, x0, y0)
        for y in range(y0, y1 + 1):
            row = (y - self.y0) * self.width
            out.data[(y - y0) * out.width:(y - y0 + 1) * out.width] = self.data[row + x0 - self.x0: row + x1 - self.x0 + 1]
        return out

    def paste(self, other: "HeightGrid"):
        for y in range(other.y0, other.y0 + other.height):
            src = (y - other.y0) * other.width
            dst = (y - self.y0) * self.width + (other.x0 - self.x0)
            self.data[dst:dst + other.width] = other.data[src:src + other.width]


# ---------------------------------------------------------------------------
# World <-> heightmap transform
# ---------------------------------------------------------------------------

class LandscapeTransform:
    """Maps world centimetres to heightmap quads (assumes an unrotated landscape, the norm)."""

    def __init__(self, origin=(0.0, 0.0, 0.0), scale=(100.0, 100.0, 100.0)):
        self.ox, self.oy, self.oz = (float(v) for v in origin)
        self.sx, self.sy, self.sz = (float(v) for v in scale)

    def world_to_grid(self, x: float, y: float) -> Tuple[float, float]:
        return (x - self.ox) / self.sx, (y - self.oy) / self.sy

    def grid_to_world(self, gx: float, gy: float) -> Tuple[float, float]:
        return self.ox + gx * self.sx, self.oy + gy * self.sy

    def height_to_z(self, h: float) -> float:
        return self.oz + (h - MID) * self.sz * LANDSCAPE_ZSCALE

    def z_to_height(self, z: float) -> float:
        return (z - self.oz) / (self.sz * LANDSCAPE_ZSCALE) + MID

    def cm_to_units(self, cm: float) -> float:
        return cm / (self.sz * LANDSCAPE_ZSCALE)

    def units_to_cm(self, units: float) -> float:
        return units * self.sz * LANDSCAPE_ZSCALE


# ---------------------------------------------------------------------------
# Brushes
# ---------------------------------------------------------------------------

def falloff_weight(dist: float, radius: float, falloff: float, kind: str = "smooth") -> float:
    """1 inside radius*(1-falloff), easing to 0 at radius."""
    if dist >= radius:
        return 0.0
    if kind == "none" or falloff <= 0:
        return 1.0
    inner = radius * (1.0 - min(max(falloff, 0.0), 1.0))
    if dist <= inner:
        return 1.0
    t = 1.0 - (dist - inner) / max(radius - inner, 1e-6)
    if kind == "linear":
        return t
    return t * t * (3.0 - 2.0 * t)  # smoothstep


def _value_noise(seed: int):
    rnd = random.Random(seed)
    perm = list(range(256))
    rnd.shuffle(perm)
    vals = [rnd.uniform(-1.0, 1.0) for _ in range(256)]

    def lattice(ix, iy):
        return vals[perm[(perm[ix & 255] + iy) & 255]]

    def noise(x, y):
        ix, iy = math.floor(x), math.floor(y)
        fx, fy = x - ix, y - iy
        sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a = lattice(ix, iy) + sx * (lattice(ix + 1, iy) - lattice(ix, iy))
        b = lattice(ix, iy + 1) + sx * (lattice(ix + 1, iy + 1) - lattice(ix, iy + 1))
        return a + sy * (b - a)

    return noise


def brush_region(cx: float, cy: float, radius: float) -> Tuple[int, int, int, int]:
    """Inclusive quad bounds (x0, y0, x1, y1) covering a circular brush in grid space."""
    return (int(math.floor(cx - radius)), int(math.floor(cy - radius)),
            int(math.ceil(cx + radius)), int(math.ceil(cy + radius)))


def apply_brush(grid: HeightGrid, op: str, cx: float, cy: float, radius: float, *,
                amount: float = 0.0, target: Optional[float] = None, falloff: float = 0.5,
                falloff_kind: str = "smooth", iterations: int = 1, seed: int = 0,
                noise_scale: float = 8.0, end: Optional[Tuple[float, float, float]] = None,
                start_height: Optional[float] = None) -> dict:
    """Applies a brush in grid units (radius in quads, amount in height units) and returns stats.

    ops: raise, lower, flatten, smooth, noise, ramp.
      raise/lower: +-amount at the centre.
      flatten: blend towards ``target`` height (defaults to the centre height).
      smooth: ``iterations`` passes of a 3x3 box blur weighted by the brush.
      noise: value noise of amplitude ``amount`` and wavelength ``noise_scale`` quads.
      ramp: straight ramp from (cx, cy, start_height) to end=(ex, ey, end_height), ``radius`` = half width.
    """
    original = grid.copy()
    if op not in ("raise", "lower", "flatten", "smooth", "noise", "ramp"):
        raise ValueError(f"Unknown brush operation '{op}'")

    def each_cell():
        for y in range(grid.y0, grid.y0 + grid.height):
            for x in range(grid.x0, grid.x0 + grid.width):
                yield x, y

    if op in ("raise", "lower"):
        sign = 1.0 if op == "raise" else -1.0
        for x, y in each_cell():
            w = falloff_weight(math.hypot(x - cx, y - cy), radius, falloff, falloff_kind)
            if w > 0:
                grid.set(x, y, grid.get(x, y) + sign * amount * w)
    elif op == "flatten":
        if target is None:
            target = original.get(min(max(int(round(cx)), grid.x0), grid.x0 + grid.width - 1),
                                  min(max(int(round(cy)), grid.y0), grid.y0 + grid.height - 1))
        for x, y in each_cell():
            w = falloff_weight(math.hypot(x - cx, y - cy), radius, falloff, falloff_kind)
            if w > 0:
                h = grid.get(x, y)
                grid.set(x, y, h + (target - h) * w)
    elif op == "smooth":
        for _ in range(max(1, int(iterations))):
            src = grid.copy()
            for x, y in each_cell():
                w = falloff_weight(math.hypot(x - cx, y - cy), radius, falloff, falloff_kind)
                if w <= 0:
                    continue
                total, n = 0, 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if grid.x0 <= nx < grid.x0 + grid.width and grid.y0 <= ny < grid.y0 + grid.height:
                            total += src.get(nx, ny)
                            n += 1
                h = src.get(x, y)
                grid.set(x, y, h + (total / n - h) * w)
    elif op == "noise":
        noise = _value_noise(seed)
        for x, y in each_cell():
            w = falloff_weight(math.hypot(x - cx, y - cy), radius, falloff, falloff_kind)
            if w > 0:
                grid.set(x, y, grid.get(x, y) + amount * w * noise(x / noise_scale, y / noise_scale))
    elif op == "ramp":
        if end is None:
            raise ValueError("ramp requires 'end' (x, y, height)")
        ex, ey, eh = end
        sh = start_height if start_height is not None else original.get(
            min(max(int(round(cx)), grid.x0), grid.x0 + grid.width - 1),
            min(max(int(round(cy)), grid.y0), grid.y0 + grid.height - 1))
        dx, dy = ex - cx, ey - cy
        length2 = dx * dx + dy * dy
        if length2 <= 0:
            raise ValueError("ramp start and end must differ")
        for x, y in each_cell():
            t = ((x - cx) * dx + (y - cy) * dy) / length2
            if t < 0 or t > 1:
                continue
            px, py = cx + t * dx, cy + t * dy
            w = falloff_weight(math.hypot(x - px, y - py), radius, falloff, falloff_kind)
            if w > 0:
                h = grid.get(x, y)
                grid.set(x, y, h + ((sh + (eh - sh) * t) - h) * w)

    return diff_stats(original, grid)


def diff_stats(before: HeightGrid, after: HeightGrid) -> dict:
    changed, lo, hi, total = 0, 0, 0, 0
    for a, b in zip(before.data, after.data):
        d = b - a
        if d:
            changed += 1
            lo, hi = min(lo, d), max(hi, d)
            total += d
    return {"changed_vertices": changed, "min_delta_units": lo, "max_delta_units": hi,
            "mean_delta_units": (total / changed) if changed else 0.0}


# ---------------------------------------------------------------------------
# 16-bit grayscale PNG (no dependencies)
# ---------------------------------------------------------------------------

def _chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)


def encode_png16(grid: HeightGrid) -> bytes:
    raw = bytearray()
    for y in range(grid.height):
        raw.append(0)  # filter: none
        row = grid.data[y * grid.width:(y + 1) * grid.width]
        be = array("H", row)
        if struct.pack("=H", 1) == b"\x01\x00":  # little-endian host -> PNG is big-endian
            be.byteswap()
        raw += be.tobytes()
    ihdr = struct.pack(">IIBBBBB", grid.width, grid.height, 16, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b"")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png16(data: bytes) -> HeightGrid:
    """Decodes 16-bit (or 8-bit, scaled) grayscale PNGs as written by Unreal's Landscape export."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG file")
    pos, idat, ihdr = 8, bytearray(), None
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        raise ValueError("PNG has no IHDR chunk")
    width, height, depth, color, _, _, interlace = ihdr
    if color != 0 or depth not in (8, 16) or interlace != 0:
        raise ValueError("Heightmap must be a non-interlaced grayscale PNG (8 or 16 bit)")
    bpp = depth // 8
    stride = width * bpp
    raw = zlib.decompress(bytes(idat))
    out = array("H")
    prev = bytearray(stride)
    i = 0
    for _ in range(height):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ftype == 1:
                line[x] = (line[x] + a) & 0xFF
            elif ftype == 2:
                line[x] = (line[x] + b) & 0xFF
            elif ftype == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
        if depth == 16:
            row = array("H", bytes(line))
            if struct.pack("=H", 1) == b"\x01\x00":
                row.byteswap()
            out.extend(row)
        else:
            out.extend(v * 257 for v in line)
        prev = line
    return HeightGrid(width, height, out)
