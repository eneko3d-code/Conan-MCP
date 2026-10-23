"""Attack / ability timing templates and key generation from a few key poses."""

from typing import Dict, List, Optional

# Phase fractions of the total duration. Strike + impact are short on purpose: speed reads as power.
TEMPLATES = {
    "light_attack": {"duration": 0.8, "phases": [("anticipation", 0.30), ("strike", 0.10), ("impact", 0.05),
                                                 ("follow_through", 0.20), ("recovery", 0.35)]},
    "heavy_attack": {"duration": 1.5, "phases": [("anticipation", 0.38), ("strike", 0.08), ("impact", 0.06),
                                                 ("follow_through", 0.18), ("recovery", 0.30)]},
    "thrust": {"duration": 0.9, "phases": [("anticipation", 0.30), ("strike", 0.08), ("impact", 0.07),
                                           ("follow_through", 0.15), ("recovery", 0.40)]},
    "spin_attack": {"duration": 1.3, "phases": [("anticipation", 0.25), ("strike", 0.30), ("impact", 0.05),
                                                ("follow_through", 0.15), ("recovery", 0.25)]},
    "cast": {"duration": 1.4, "phases": [("anticipation", 0.35), ("strike", 0.10), ("impact", 0.20),
                                         ("follow_through", 0.10), ("recovery", 0.25)]},
    "slam": {"duration": 1.6, "phases": [("anticipation", 0.40), ("strike", 0.07), ("impact", 0.10),
                                         ("follow_through", 0.13), ("recovery", 0.30)]},
}

# Which key pose each phase ends on
PHASE_END_POSE = {"anticipation": "anticipation", "strike": "impact", "impact": "impact",
                  "follow_through": "follow_through", "recovery": "start"}


def phase_frames(template: str, duration: Optional[float] = None, fps: int = 30) -> List[dict]:
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template '{template}'. Available: {sorted(TEMPLATES)}")
    t = TEMPLATES[template]
    total = float(duration or t["duration"])
    frames_total = max(int(round(total * fps)), len(t["phases"]))
    out, cursor = [], 0
    for i, (name, frac) in enumerate(t["phases"]):
        length = max(1, int(round(frac * frames_total)))
        end = frames_total if i == len(t["phases"]) - 1 else min(cursor + length, frames_total - 1)
        out.append({"phase": name, "start_frame": cursor, "end_frame": end,
                    "start_s": round(cursor / fps, 3), "end_s": round(end / fps, 3)})
        cursor = end
    return out


def _scale(pose: Dict[str, dict], factor: float) -> Dict[str, dict]:
    return {bone: {"rotation": {k: v * factor for k, v in spec.get("rotation", {}).items()}} for bone, spec in pose.items()}


def generate_keys(poses: Dict[str, Dict[str, dict]], template: str, duration: Optional[float] = None, fps: int = 30,
                  overshoot: float = 0.12, settle: bool = True) -> dict:
    """Keys for a whole attack from key poses.

    ``poses`` maps 'start' (optional, default rest), 'anticipation', 'impact' (required) and
    'follow_through' (optional) to {target: {"rotation": {...}}}. Adds an overshoot key just after
    the impact and a settle key during recovery for weight.
    """
    if "impact" not in poses:
        raise ValueError("poses needs at least 'impact' (and usually 'anticipation')")
    phases = phase_frames(template, duration, fps)
    start = poses.get("start", {})
    targets = set(start) | set().union(*[set(p) for p in poses.values()])
    zero = {t: {"rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}} for t in targets}
    resolved = {name: {**zero, **poses.get(name, {})} for name in ("start", "anticipation", "impact", "follow_through")}
    if "follow_through" not in poses:
        resolved["follow_through"] = _blend(resolved["impact"], resolved["start"], 0.35)
    if "anticipation" not in poses:
        resolved["anticipation"] = _blend(resolved["start"], _scale(resolved["impact"], -0.3), 1.0)

    keys = [{"frame": 0, "phase": "start", "bones": resolved["start"]}]
    for ph in phases:
        pose_name = PHASE_END_POSE[ph["phase"]]
        if ph["phase"] == "strike":
            continue  # strike ends on the impact pose, keyed by the impact phase start
        if ph["phase"] == "impact":
            keys.append({"frame": ph["start_frame"], "phase": "impact", "bones": resolved["impact"]})
            if overshoot > 0 and ph["end_frame"] > ph["start_frame"]:
                keys.append({"frame": ph["end_frame"], "phase": "overshoot",
                             "bones": _blend(resolved["impact"], _scale(resolved["impact"], 1.0 + overshoot), 1.0)})
            continue
        if ph["phase"] == "recovery" and settle:
            mid = ph["start_frame"] + (ph["end_frame"] - ph["start_frame"]) // 2
            keys.append({"frame": mid, "phase": "settle",
                         "bones": _blend(resolved["follow_through"], resolved["start"], 0.75)})
        keys.append({"frame": ph["end_frame"], "phase": ph["phase"], "bones": resolved[pose_name]})
    dedup = {}
    for k in keys:
        dedup[k["frame"]] = k
    return {"fps": fps, "frames": phases[-1]["end_frame"], "phases": phases,
            "impact_frame": next(p["start_frame"] for p in phases if p["phase"] == "impact"),
            "keys": [dedup[f] for f in sorted(dedup)]}


def _blend(a: Dict[str, dict], b: Dict[str, dict], t: float) -> Dict[str, dict]:
    out = {}
    for bone in set(a) | set(b):
        ra = a.get(bone, {}).get("rotation", {})
        rb = b.get(bone, {}).get("rotation", {})
        out[bone] = {"rotation": {k: ra.get(k, 0.0) + (rb.get(k, 0.0) - ra.get(k, 0.0)) * t
                                  for k in ("pitch", "yaw", "roll")}}
    return out
