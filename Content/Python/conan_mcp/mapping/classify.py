"""Heuristic classification of level actors into map-design categories (pure Python)."""

import re

CATEGORIES = (
    "landscape", "water", "foliage", "structure", "spawner", "resource", "light", "atmosphere",
    "volume", "audio", "decal", "gameplay", "static_mesh", "blueprint", "other",
)

def _words(*words):
    """Regex matching any word not glued to other letters (so 'SM_Wall_01' matches 'wall')."""
    return "|".join(rf"(?<![a-z]){w}(?![a-z])" for w in words)


# Order matters: first match wins. Patterns are tested against "Class Label" (case-insensitive).
_RULES = (
    ("landscape", r"^landscape|landscapespline|landscapestreamingproxy"),
    ("water", r"waterbody|waterzone|" + _words("water", "ocean", "river", "lake", "waterfall")),
    ("foliage", r"instancedfoliage|" + _words("foliage", "grass")),
    ("spawner", r"spawn|playerstart"),
    ("light", r"(point|spot|rect|directional|sky)light|" + _words("light", "lamp", "torch", "brazier")),
    ("atmosphere", r"skyatmosphere|heightfog|volumetriccloud|postprocess|skysphere|" + _words("sky", "fog")),
    ("volume", r"volume|navmesh|levelbounds|killz|" + _words("trigger")),
    ("audio", r"ambientsound|audio|" + _words("sound")),
    ("decal", r"decal"),
    ("gameplay", r"worldsettings|gamemode|textrender|" + _words("camera", "note", "brush")),
    ("structure", r"building|structure|placeable|foundation|fortress|palisade|" + _words(
        "wall", "walls", "pillar", "ceiling", "stairs", "stair", "ruin", "ruins", "house", "tower", "gate",
        "temple", "camp", "bridge", "fence", "hut", "tent", "door", "roof", "floor", "arch", "city", "village",
        "castle", "keep", "dock", "pier", "statue", "altar")),
    ("resource", r"resource|harvest|" + _words(
        "node", "ore", "tree", "trees", "bush", "rock", "rocks", "boulder", "iron", "stone", "wood", "plant",
        "plants", "cliff", "crystal")),
    ("static_mesh", r"staticmeshactor"),
)
_COMPILED = tuple((cat, re.compile(p, re.I)) for cat, p in _RULES)


def classify(class_name: str, label: str = "") -> str:
    text = f"{class_name} {label}"
    for cat, rx in _COMPILED:
        if rx.search(text):
            return cat
    if class_name.endswith("_C"):
        return "blueprint"
    return "other"


# Actors a bulk delete must never touch unless explicitly allowed
PROTECTED_CLASS_PATTERN = re.compile(
    r"^(WorldSettings|Landscape|LandscapeStreamingProxy|LandscapeProxy|InstancedFoliageActor|LevelBounds|"
    r"WorldDataLayers|WorldPartitionMiniMap|Brush|DefaultPhysicsVolume|AbstractNavData|RecastNavMesh.*)$"
)


def is_protected(class_name: str) -> bool:
    return bool(PROTECTED_CLASS_PATTERN.match(class_name or ""))
