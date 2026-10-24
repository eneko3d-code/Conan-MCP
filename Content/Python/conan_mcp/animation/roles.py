"""Maps skeleton bone names to semantic roles (pelvis, upperarm_r, tail_2 ...).

Works with Unreal mannequin names (upperarm_r), 3ds Max Biped (Bip01 R UpperArm),
Mixamo (mixamorig:RightArm) and common creature rigs, so the AI can describe
poses with roles instead of guessing each skeleton's naming.
"""

import re
from typing import Dict, List, Optional

# Base roles, most specific first. Each regex runs on a normalized name with the side token removed.
_BASE_RULES = (
    ("root", r"^(root|bip\d*|armature|reference)$"),
    ("pelvis", r"pelvis|hips?$|^hip$|^cog$|center_?of_?gravity"),
    ("spine", r"spine|chest|torso|^back$"),
    ("neck", r"neck"),
    ("head", r"^head$|^head_?\d*$|head_?top|^head"),
    ("jaw", r"jaw|mouth"),
    ("clavicle", r"clavicle|collar|shoulder"),
    ("forearm", r"fore_?arm|lower_?arm|lowarm|elbow"),
    ("upperarm", r"upper_?arm|uparm|^arm$|^arm_?\d*$"),
    ("hand", r"^hand$|^hand_?\d*$|wrist|^palm"),
    ("thigh", r"thigh|up_?leg|upper_?leg"),
    ("calf", r"calf|shin|lower_?leg|knee|^leg$|^leg_?\d*$"),
    ("foot", r"foot|ankle|paw|hoof"),
    ("toe", r"toe|ball"),
    ("weapon", r"weapon|prop|sword|shield|hand_?r_?attach|grip"),
    ("tail", r"tail"),
    ("wing", r"wing"),
    ("ear", r"ear"),
)
_FINGERS = re.compile(r"finger|thumb|index|middle|ring|pinky|little|digit|claw|nail|metacarpal", re.I)
_IGNORE = re.compile(r"twist|ik_|_ik|^ik|roll|nub|end$|_end|dummy|helper|corrective|vb |virtual", re.I)
_COMPILED = tuple((role, re.compile(rx)) for role, rx in _BASE_RULES)
SIDED = {"clavicle", "upperarm", "forearm", "hand", "thigh", "calf", "foot", "toe", "wing", "ear", "weapon"}
CHAINS = {"spine", "neck", "tail"}
LEG_PARTS = {"thigh", "calf", "foot", "toe"}
_LIMB_PREFIX = re.compile(r"(^|_)(front|fore|back|hind|rear)(_|$)")


def _normalize(name: str):
    """(normalized base name, side 'l'/'r'/None)."""
    n = name.split(":")[-1]  # mixamorig:LeftArm
    n = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", n)  # camelCase -> snake
    n = n.lower().replace(" ", "_").replace(".", "_").replace("-", "_")
    n = re.sub(r"^bip\d*_", "", n)  # Bip01_
    side = None
    m = re.search(r"(^|_)(l|left)(_|$)", n)
    if m:
        side = "l"
    else:
        m = re.search(r"(^|_)(r|right)(_|$)", n)
        if m:
            side = "r"
    if side:
        n = (n[:m.start()] + "_" + n[m.end():]).strip("_")
    n = re.sub(r"_+", "_", n)
    return n, side


def classify_bone(name: str) -> Optional[str]:
    """Base role (without side/index) of a single bone, or None."""
    if _FINGERS.search(name) or _IGNORE.search(name):
        return None
    base, _ = _normalize(name)
    for role, rx in _COMPILED:
        if rx.search(base):
            return role
    return None


def map_roles(bone_names: List[str]) -> Dict[str, object]:
    """Roles for a whole skeleton (bones in hierarchy order).

    Sided roles get _l/_r suffixes; chains (spine, neck, tail) get _1.._n in order.
    The first bone found for a role wins.
    """
    roles: Dict[str, str] = {}
    chain_counts: Dict[str, int] = {}
    unmapped = []
    for bone in bone_names:
        role = classify_bone(bone)
        if role is None:
            unmapped.append(bone)
            continue
        _, side = _normalize(bone)
        if role in CHAINS:
            chain_counts[role] = chain_counts.get(role, 0) + 1
            key = f"{role}_{chain_counts[role]}"
        elif role in LEG_PARTS and _LIMB_PREFIX.search(_normalize(bone)[0]):
            # quadrupeds: front/back legs get their own roles (front_thigh_l, back_foot_r ...)
            prefix = "front" if re.search(r"front|fore|arm", _normalize(bone)[0]) else "back"
            key = f"{prefix}_{role}_{side}" if side else f"{prefix}_{role}"
        elif role in SIDED:
            if side is None:
                # unsided creature parts (e.g. a single 'jaw' or 'weapon') keep the bare role
                key = role
            else:
                key = f"{role}_{side}"
        else:
            key = role
        roles.setdefault(key, bone)
    # A single neck/head-style chain reads better without the index
    for chain in ("neck",):
        if chain_counts.get(chain) == 1 and f"{chain}_1" in roles:
            roles[chain] = roles.pop(f"{chain}_1")
    body = "biped" if {"upperarm_l", "upperarm_r", "thigh_l", "thigh_r"} <= set(roles) else (
        "creature" if any(k.startswith(("tail", "wing")) for k in roles) or "thigh_l" in roles else "unknown")
    return {"roles": roles, "unmapped_count": len(unmapped), "unmapped_examples": unmapped[:40], "body_type": body}


def resolve(target: str, roles: Dict[str, str], bones: List[str]) -> Optional[str]:
    """Bone name for a role, a bone name or a control name ('<bone>_CONTROL')."""
    if target in roles:
        return roles[target]
    if target in bones:
        return target
    if target.endswith("_CONTROL") and target[:-8] in bones:
        return target[:-8]
    low = {b.lower(): b for b in bones}
    return low.get(target.lower())
