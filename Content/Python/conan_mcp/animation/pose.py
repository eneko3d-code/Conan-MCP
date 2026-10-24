"""Rotation math (Unreal conventions), additive pose composition, joint limits and key interpolation."""

import math
from typing import Dict, List, Optional, Tuple

Quat = Tuple[float, float, float, float]  # (x, y, z, w)

# Maximum additive rotation (degrees, per axis) a role may receive. Keeps the AI from breaking joints.
ROLE_LIMITS = {
    "pelvis": 60, "spine": 45, "neck": 60, "head": 70, "jaw": 35, "clavicle": 35,
    "upperarm": 170, "forearm": 150, "hand": 80, "thigh": 120, "calf": 150, "foot": 60, "toe": 50,
    "tail": 60, "wing": 120, "ear": 60, "weapon": 180, "root": 180,
}


def role_base(role: str) -> str:
    """'upperarm_r' -> 'upperarm', 'front_thigh_l' -> 'thigh', 'tail_3' -> 'tail'."""
    parts = [p for p in role.split("_") if p not in ("front", "back", "l", "r") and not p.isdigit()]
    return parts[0] if parts else role


def rotator_to_quat(pitch: float, yaw: float, roll: float) -> Quat:
    """FRotator::Quaternion (degrees)."""
    p, y, r = (math.radians(v) * 0.5 for v in (pitch, yaw, roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return (cr * sp * sy - sr * cp * cy,
            -cr * sp * cy - sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy)


def _norm_axis(a: float) -> float:
    a = math.fmod(a, 360.0)
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


def quat_to_rotator(q: Quat) -> Dict[str, float]:
    """FQuat::Rotator (degrees)."""
    x, y, z, w = q
    test = z * x - w * y
    yaw_y, yaw_x = 2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)
    thr = 0.4999995
    yaw = math.degrees(math.atan2(yaw_y, yaw_x))
    if test < -thr:
        pitch = -90.0
        roll = _norm_axis(-yaw - 2.0 * math.degrees(math.atan2(x, w)))
    elif test > thr:
        pitch = 90.0
        roll = _norm_axis(yaw - 2.0 * math.degrees(math.atan2(x, w)))
    else:
        pitch = math.degrees(math.asin(2.0 * test))
        roll = math.degrees(math.atan2(-2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
    return {"pitch": pitch, "yaw": yaw, "roll": roll}


def quat_inverse(q: Quat) -> Quat:
    x, y, z, w = q
    return (-x, -y, -z, w)


def offset_from_absolute(reference: Dict[str, float], absolute: Dict[str, float]) -> Dict[str, float]:
    """Additive offset such that compose_additive(reference, offset) == absolute."""
    r, a = rot_dict(reference), rot_dict(absolute)
    q = quat_mul(quat_inverse(rotator_to_quat(r["pitch"], r["yaw"], r["roll"])), rotator_to_quat(a["pitch"], a["yaw"], a["roll"]))
    return {k: round(v, 4) for k, v in quat_to_rotator(q).items()}


def quat_mul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def slerp(a: Quat, b: Quat, t: float) -> Quat:
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-v for v in b), -dot
    if dot > 0.9995:
        q = tuple(x + t * (y - x) for x, y in zip(a, b))
    else:
        th = math.acos(dot)
        s = math.sin(th)
        q = tuple((math.sin((1 - t) * th) * x + math.sin(t * th) * y) / s for x, y in zip(a, b))
    n = math.sqrt(sum(v * v for v in q))
    return tuple(v / n for v in q)


def rot_dict(d) -> Dict[str, float]:
    d = d or {}
    return {"pitch": float(d.get("pitch", 0.0)), "yaw": float(d.get("yaw", 0.0)), "roll": float(d.get("roll", 0.0))}


def clamp_offset(role: Optional[str], rotation: Dict[str, float]) -> Tuple[Dict[str, float], bool]:
    """Clamps an additive rotation to the role's limit. Returns (rotation, was_clamped)."""
    limit = ROLE_LIMITS.get(role_base(role), 180) if role else 180
    out, clamped = {}, False
    for k, v in rot_dict(rotation).items():
        c = max(-limit, min(limit, v))
        clamped |= c != v
        out[k] = c
    return out, clamped


def compose_additive(reference: Dict[str, float], offset: Dict[str, float]) -> Dict[str, float]:
    """Local rotation = reference * offset (offset expressed in the bone's local frame)."""
    r = rot_dict(reference)
    o = rot_dict(offset)
    q = quat_mul(rotator_to_quat(r["pitch"], r["yaw"], r["roll"]), rotator_to_quat(o["pitch"], o["yaw"], o["roll"]))
    return {k: round(v, 4) for k, v in quat_to_rotator(q).items()}


def sample_keys(keys: List[dict], bone: str, frame: float) -> Optional[Dict[str, float]]:
    """Additive rotation of ``bone`` at ``frame`` by slerping the surrounding keys (None if never keyed)."""
    pts = [(k["frame"], k["bones"][bone]["rotation"]) for k in keys if bone in k.get("bones", {})]
    if not pts:
        return None
    pts.sort(key=lambda p: p[0])
    if frame <= pts[0][0]:
        return rot_dict(pts[0][1])
    if frame >= pts[-1][0]:
        return rot_dict(pts[-1][1])
    for (f0, r0), (f1, r1) in zip(pts[:-1], pts[1:]):
        if f0 <= frame <= f1:
            t = 0.0 if f1 == f0 else (frame - f0) / (f1 - f0)
            t = t * t * (3 - 2 * t)  # ease in/out like auto tangents
            a, b = rot_dict(r0), rot_dict(r1)
            q = slerp(rotator_to_quat(a["pitch"], a["yaw"], a["roll"]), rotator_to_quat(b["pitch"], b["yaw"], b["roll"]), t)
            return quat_to_rotator(q)
    return rot_dict(pts[-1][1])


def merge_keys(existing: List[dict], new: List[dict]) -> List[dict]:
    """Merges new keys into the spec: same frame -> bones are merged (new values win)."""
    by_frame = {int(k["frame"]): {"frame": int(k["frame"]), "bones": dict(k.get("bones", {}))} for k in existing}
    for k in new:
        f = int(k["frame"])
        slot = by_frame.setdefault(f, {"frame": f, "bones": {}})
        slot["bones"].update(k.get("bones", {}))
    return [by_frame[f] for f in sorted(by_frame)]
