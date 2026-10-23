"""Tool logic tests against the fake Unreal engine (tests/fake_unreal.py)."""

import json
import math
import os
import random
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "Content", "Python"))
sys.path.insert(0, HERE)

import fake_unreal as fu  # noqa: E402
import conan_mcp_server  # noqa: E402,F401  (registers everything)
from conan_mcp.core import config, ue  # noqa: E402
from conan_mcp.core.protocol import call_tool  # noqa: E402
from conan_mcp.mapping import heightmap as hm  # noqa: E402
from conan_mcp.mapping.classify import classify, is_protected  # noqa: E402
from conan_mcp.mapping.placement import bbox_overlaps, evaluate_placement, path_points, scatter_points  # noqa: E402
from conan_mcp.mapping.terrain import analyze_grid  # noqa: E402


def hill(x, y):
    """A 20 m hill centred at (5000, 5000) on flat ground."""
    d = math.hypot(x - 5000, y - 5000)
    return 2000.0 * math.exp(-(d / 1500.0) ** 2)


@pytest.fixture()
def engine(monkeypatch, tmp_path):
    eng = fu.reset(hill)
    monkeypatch.setattr(ue, "unreal", fu)
    monkeypatch.setattr(fu, "ConanMCPEditorLibrary", None, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ENABLE_WRITE_TOOLS", True)
    land = eng.add_actor(fu.Landscape("Landscape", (0, 0, 0), extent=(50, 50, 20)))
    land.set_actor_scale3d(fu.Vector(100, 100, 100))  # bounds +-5000 cm, 100 cm per quad
    eng.add_actor(fu.WorldSettings("WorldSettings"))
    eng.add_actor(fu.StaticMeshActor("SM_Wall_01", (1000, 1000, 50)))
    eng.add_actor(fu.StaticMeshActor("SM_Wall_02", (1200, 1000, 50)))
    eng.add_actor(fu.Actor("BP_NPCSpawner", (3000, 3000, 0), cls_name="BP_NPCSpawner_C"))
    eng.add_actor(fu.PointLight("Torch_Light", (1000, 1100, 200)))
    eng.add_asset("/Game/Mods/MyMod/Meshes/SM_Rock", fu.StaticMesh("SM_Rock", "/Game/Mods/MyMod/Meshes/SM_Rock"))
    return eng


def call(name, **args):
    res = call_tool(name, args)
    text = res["content"][0]["text"]
    if res["isError"]:
        raise AssertionError(text)
    return json.loads(text)


def call_err(name, **args):
    res = call_tool(name, args)
    assert res["isError"], res
    return res["content"][0]["text"]


# --- pure mapping helpers -----------------------------------------------------

def test_classifier_categories():
    assert classify("StaticMeshActor", "SM_Wall_01") == "structure"
    assert classify("StaticMeshActor", "SM_Rock_02") == "resource"
    assert classify("BP_NPCSpawner_C", "Spawner") == "spawner"
    assert classify("InstancedFoliageActor", "") == "foliage"
    assert classify("BP_Thing_C", "Thing") == "blueprint"
    assert is_protected("Landscape") and is_protected("WorldSettings") and not is_protected("StaticMeshActor")


def test_scatter_points_respect_spacing():
    pts = scatter_points(random.Random(3), (0, 0, 10000, 10000), 40, min_distance=800)
    assert len(pts) > 10
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert math.hypot(a[0] - b[0], a[1] - b[1]) >= 800


def test_path_points_spacing_and_yaw():
    pts = path_points([(0, 0), (1000, 0), (1000, 1000)], 250)
    assert len(pts) == 9
    assert pts[0][2] == 0 and pts[-1][2] == 90


def test_placement_and_overlap_rules():
    assert evaluate_placement(150, 50, 0, 5) == ["floating"]
    assert evaluate_placement(-200, 50, 0, 5) == ["buried"]
    assert evaluate_placement(0, 50, 0, 60) == ["steep_ground"]
    assert evaluate_placement(0, 50, None, None) == ["no_ground"]
    boxes = [{"id": "a", "min": (0, 0, 0), "max": (100, 100, 100)},
             {"id": "b", "min": (10, 10, 10), "max": (110, 110, 110)},
             {"id": "c", "min": (500, 500, 0), "max": (600, 600, 100)}]
    assert [(a, b) for a, b, _ in bbox_overlaps(boxes)] == [("a", "b")]


def test_terrain_analysis_finds_flat_regions():
    rows = [[{"x": c * 100.0, "y": r * 100.0, "z": 0.0 if c < 5 else c * 50.0, "slope": 2.0 if c < 5 else 40.0}
             for c in range(10)] for r in range(10)]
    stats = analyze_grid(rows, 100.0)
    assert stats["flat_regions"][0]["cells"] == 50
    assert stats["slope_histogram"]["steep"]["cells"] == 50
    assert stats["walkable_percent"] == 50.0


# --- heightmap ------------------------------------------------------------------

def test_png16_roundtrip():
    g = hm.HeightGrid(5, 3, [0, 1, 2, 3, 65535, 100, 200, 300, 400, 500, 32768, 1, 2, 3, 4])
    back = hm.decode_png16(hm.encode_png16(g))
    assert (back.width, back.height) == (5, 3) and list(back.data) == list(g.data)


def test_brushes():
    g = hm.HeightGrid(21, 21)
    st = hm.apply_brush(g, "raise", 10, 10, 5, amount=1000, falloff=0)
    assert g.get(10, 10) == 32768 + 1000 and g.get(0, 0) == 32768 and st["changed_vertices"] > 50
    hm.apply_brush(g, "flatten", 10, 10, 8, target=32768, falloff=0)
    assert g.get(10, 10) == 32768
    g.set(10, 10, 40000)
    hm.apply_brush(g, "smooth", 10, 10, 3, iterations=3)
    assert g.get(10, 10) < 40000
    g2 = hm.HeightGrid(21, 21)
    hm.apply_brush(g2, "ramp", 0, 10, 2, end=(20, 10, 34768), start_height=32768, falloff=0)
    assert g2.get(0, 10) == 32768 and g2.get(20, 10) == 34768 and 33600 < g2.get(10, 10) < 33900


def test_landscape_transform():
    tr = hm.LandscapeTransform((1000, 2000, 500), (100, 100, 100))
    assert tr.world_to_grid(1500, 2500) == (5.0, 5.0)
    assert tr.height_to_z(32768) == 500
    assert abs(tr.units_to_cm(128) - 100.0) < 1e-9


# --- level tools ---------------------------------------------------------------

def test_classify_and_find(engine):
    out = call("classify_level_actors")
    assert out["by_category"]["structure"] == 2 and out["by_category"]["spawner"] == 1
    near = call("find_actors_in_area", area={"center": {"x": 1000, "y": 1000}, "radius": 300})
    assert {a["label"] for a in near["actors"]} == {"SM_Wall_01", "SM_Wall_02", "Torch_Light"}


def test_spawn_snaps_to_ground_and_is_transactional(engine):
    out = call("spawn_actor", asset_path="/Game/Mods/MyMod/Meshes/SM_Rock", location={"x": 5000, "y": 5000},
               snap_to_ground=True, label="Peak_Rock")
    a = ue.find_actor("Peak_Rock")
    origin, extent = a.get_actor_bounds()
    assert abs((origin.z - extent.z) - hill(5000, 5000)) < 1.0  # bottom rests on the hill top
    assert out["spawned"]["folder"] == "ConanMCP"
    assert engine.transactions[-1].startswith("ConanMCP: Spawn")


def test_spawn_dry_run_does_not_spawn(engine):
    n = len(engine.actors)
    out = call("spawn_actor", class_name="PointLight", location={"x": 1, "y": 2, "z": 3}, dry_run=True)
    assert out["dry_run"] and len(engine.actors) == n


def test_scatter_respects_slope(engine):
    plan = call("scatter_actors", asset_path="/Game/Mods/MyMod/Meshes/SM_Rock", count=15, min_distance=200,
                max_slope=5, area={"center": {"x": 5000, "y": 5000}, "radius": 3000}, seed=7, dry_run=True)
    for p in plan["points"]:
        x, y = p["location"]["x"], p["location"]["y"]
        e = 1.0
        g = math.hypot((hill(x + e, y) - hill(x - e, y)) / 2, (hill(x, y + e) - hill(x, y - e)) / 2)
        assert math.degrees(math.atan(g)) <= 5.5
    real = call("scatter_actors", asset_path="/Game/Mods/MyMod/Meshes/SM_Rock", count=5,
                area={"center": {"x": 8000, "y": 8000}, "radius": 1000}, seed=1)
    assert real["spawned"] == 5


def test_place_along_path(engine):
    out = call("place_actors_along_path", path=[{"x": 0, "y": 0}, {"x": 2000, "y": 0}], spacing=500,
               class_name="PointLight")
    assert out["count"] == 5 and not out["errors"]


def test_delete_requires_filter_and_protects(engine):
    assert "Refusing" in call_err("delete_actors")
    plan = call("delete_actors", class_filter="", category="structure", dry_run=True)
    assert plan["count"] == 2
    out = call("delete_actors", name_filter="", class_filter="Landscape")
    assert out["deleted"] == 0 and "Landscape" in out["skipped_protected"]
    out = call("delete_actors", actors=["SM_Wall_01"])
    assert out["deleted"] == 1 and ue.find_actor("SM_Wall_01") is None


def test_delete_respects_max_count(engine):
    for i in range(10):
        engine.add_actor(fu.StaticMeshActor(f"SM_Wall_X{i}", (i * 10, 0, 0)))
    assert "max_count" in call_err("delete_actors", category="structure", max_count=5)


def test_duplicate_and_snap(engine):
    call("duplicate_actors", actors=["SM_Wall_01"], offset={"x": 0, "y": 5000, "z": 900})
    copy = ue.find_actor("SM_Wall_01_Copy")
    assert copy is not None
    report = call("validate_placement", actors=["SM_Wall_01_Copy"])
    assert report["issues"][0]["issues"] == ["floating"]
    call("snap_actors_to_ground", actors=["SM_Wall_01_Copy"])
    origin, extent = copy.get_actor_bounds()
    assert abs(origin.z - extent.z - hill(1000, 6000)) < 1.0


def test_transform_relative_and_property(engine):
    call("set_actor_transform", actor="SM_Wall_02", location={"x": 100, "y": 0, "z": 0}, relative=True)
    assert ue.find_actor("SM_Wall_02").get_actor_location().x == 1300
    out = call("set_actor_property", actor="SM_Wall_02", property="hidden", value=True)
    assert out["new"] is True


def test_focus_and_select(engine):
    call("select_actors", category="structure")
    assert len(engine.selected) == 2
    call("focus_viewport", actor="SM_Wall_01")
    assert engine.camera is not None


def test_undo_uses_console_without_native(engine):
    call("undo", steps=2)
    assert engine.console == ["TRANSACTION UNDO", "TRANSACTION UNDO"]


# --- mapping tools -------------------------------------------------------------

def test_terrain_analysis_tool(engine):
    out = call("analyze_terrain", area={"min": {"x": 0, "y": 0}, "max": {"x": 10000, "y": 10000}}, resolution=24)
    assert out["height"]["max"] > 1500 and out["flat_regions"]
    assert out["recommendations"]
    samples = call("sample_terrain", points=[{"x": 5000, "y": 5000}])
    assert abs(samples["samples"][0]["hit"]["location"]["z"] - 2000) < 1


def test_map_layout(engine):
    out = call("get_map_layout", area={"min": {"x": 0, "y": 0}, "max": {"x": 10000, "y": 10000}}, cells=4)
    assert out["totals_by_category"]["structure"] == 2
    assert sum(sum(r) for r in out["density"]["counts"]) == 4


# --- landscape -----------------------------------------------------------------

def test_sculpt_native(engine, monkeypatch):
    lib = fu.FakeNativeLibrary(size=64)
    monkeypatch.setattr(fu, "ConanMCPEditorLibrary", lib, raising=False)
    dry = call("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=800, amount=200, dry_run=True)
    assert dry["backend"] == "native" and dry["stats"]["max_delta_cm"] == pytest.approx(200, abs=1)
    assert lib.writes == 0
    call("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=800, amount=200, falloff=0)
    assert lib.heights[32 * 64 + 32] == 32768 + 256  # 200 cm at scale 100 = 256 units
    call("sculpt_terrain", operation="flatten", center={"x": 3200, "y": 3200}, radius=1500, target_z=0, falloff=0)
    assert lib.heights[32 * 64 + 32] == 32768


def test_sculpt_heightmap_file(engine):
    folder = ue.saved_dir("heightmaps")
    with open(os.path.join(folder, "base.png"), "wb") as f:
        f.write(hm.encode_png16(hm.HeightGrid(101, 101)))
    out = call("sculpt_terrain", operation="raise", center={"x": -5000 + 5000, "y": -5000 + 5000}, radius=1000,
               amount=100, heightmap_file="base.png", output_file="edited.png", falloff=0)
    assert out["backend"] == "heightmap_file" and out["stats"]["changed_vertices"] > 0
    with open(os.path.join(folder, "edited.png"), "rb") as f:
        g = hm.decode_png16(f.read())
    assert g.get(50, 50) == 32768 + 128  # landscape extent starts at -5000 => (0,0) world is pixel 50


def test_sculpt_without_backend_explains(engine):
    assert "Export the heightmap" in call_err("sculpt_terrain", operation="raise", center={"x": 0, "y": 0})


def test_paint_requires_native(engine):
    assert "ConanMCPNative" in call_err("paint_landscape_layer", layer="Grass", center={"x": 0, "y": 0})


# --- datatables ----------------------------------------------------------------

@pytest.fixture()
def tables(engine):
    cols = ["DisplayName", "Weight", "Stats"]
    rows = [{"Name": "Sword", "DisplayName": "Iron Sword", "Weight": 2.5, "Stats": {"Damage": 30}},
            {"Name": "Axe", "DisplayName": "Stone Axe", "Weight": 3.0, "Stats": {"Damage": 20}}]
    engine.add_asset("/Game/Mods/MyMod/DataTables/DT_Items", fu.DataTable("DT_Items", "/Game/Mods/MyMod/DataTables/DT_Items", rows, cols))
    engine.add_asset("/Game/Systems/ItemTable", fu.DataTable("ItemTable", "/Game/Systems/ItemTable", [dict(r) for r in rows], cols))
    return engine


def test_datatable_read_and_search(tables):
    row = call("get_datatable_row", datatable_path="/Game/Mods/MyMod/DataTables/DT_Items", row_name="Sword")
    assert row["row_data"]["Stats"]["Damage"] == 30  # real data, not the old stub
    schema = call("get_datatable_schema", datatable_path="/Game/Systems/ItemTable")
    assert set(schema["columns"]) == {"DisplayName", "Weight", "Stats"}
    hits = call("search_datatable_rows", datatable_path="/Game/Systems/ItemTable", query="stone")
    assert [r["Name"] for r in hits["rows"]] == ["Axe"]


def test_datatable_writes(tables):
    path = "/Game/Mods/MyMod/DataTables/DT_Items"
    call("add_datatable_row", datatable_path=path, row_name="Mace", template_row="Sword",
         values={"DisplayName": "Mace", "Stats": {"Damage": 40}})
    row = call("get_datatable_row", datatable_path=path, row_name="Mace")["row_data"]
    assert row["Weight"] == 2.5 and row["Stats"]["Damage"] == 40
    call("update_datatable_row", datatable_path=path, row_name="Mace", values={"Weight": 4.0})
    call("duplicate_datatable_row", datatable_path="/Game/Systems/ItemTable", row_name="Axe",
         new_row_name="MyMod_Axe", destination_path=path, values={"Weight": 1.0})
    call("remove_datatable_row", datatable_path=path, row_name="Sword")
    names = [r["Name"] for r in tables.assets[path].rows]
    assert names == ["Axe", "Mace", "MyMod_Axe"]
    assert "Unreal rejected" in call_err("add_datatable_row", datatable_path=path, row_name="Bad", values={"Nope": 1})


def test_base_game_tables_are_protected(tables):
    err = call_err("update_datatable_row", datatable_path="/Game/Systems/ItemTable", row_name="Axe", values={"Weight": 9})
    assert "/Game/Mods" in err
    call("update_datatable_row", datatable_path="/Game/Systems/ItemTable", row_name="Axe", values={"Weight": 9},
         allow_base_game_table=True)


def test_datatable_export_import(tables):
    path = "/Game/Mods/MyMod/DataTables/DT_Items"
    out = call("export_datatable", datatable_path=path, format="json")
    with open(out["written"]) as f:
        rows = json.load(f)
    rows.append({"Name": "Bow", "DisplayName": "Bow", "Weight": 1.0, "Stats": {"Damage": 15}})
    with open(os.path.join(ue.saved_dir("datatables"), "new_rows.json"), "w") as f:
        json.dump(rows, f)
    res = call("import_datatable", datatable_path=path, file_name="new_rows.json")
    assert res["row_count"] == 3
    csv_out = call("export_datatable", datatable_path=path, format="csv")
    assert csv_out["rows"] == 3
    assert "plain name" in call_err("import_datatable", datatable_path=path, file_name="../../etc/passwd")


# --- blueprints & mod ------------------------------------------------------------

def test_blueprint_info_python_backend(engine):
    engine.add_asset("/Game/Mods/MyMod/Blueprints/BP_Chest", fu.Blueprint("BP_Chest", "/Game/Mods/MyMod/Blueprints/BP_Chest"))
    info = call("get_blueprint_info", blueprint_path="/Game/Mods/MyMod/Blueprints/BP_Chest")
    assert info["parent_class"] == "Actor" and info["backend"] == "python"


def test_mod_workflow(engine):
    out = call("create_mod_structure", mod_name="MyMod")
    assert "/Game/Mods/MyMod/DataTables" in out["created"]
    assert "letter" in call_err("create_mod_structure", mod_name="../evil")
    engine.add_asset("/Game/Mods/MyMod/Blueprints/Chest", fu.Blueprint("Chest", "/Game/Mods/MyMod/Blueprints/Chest"))
    engine.deps["/Game/Mods/MyMod/Blueprints/Chest"] = ["/Game/Mods/MyMod/Meshes/SM_Missing", "/Game/Mods/Other/Thing"]
    v = call("validate_assets", package_path="/Game/Mods/MyMod")
    assert v["broken_count"] == 1
    audit = call("audit_mod", mod_name="MyMod")
    assert not audit["checks"]["no_broken_references"] and not audit["checks"]["no_cross_mod_dependencies"]
    assert any(n["asset"].endswith("Chest.Chest") for n in audit["naming_issues"])
    assert audit["score"] < 100


def test_delete_asset_is_destructive(engine, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_DESTRUCTIVE_TOOLS", False)
    assert "DESTRUCTIVE" in call_err("delete_asset", asset_path="/Game/Mods/MyMod/Meshes/SM_Rock")
    monkeypatch.setattr(config, "ENABLE_DESTRUCTIVE_TOOLS", True)
    call("delete_asset", asset_path="/Game/Mods/MyMod/Meshes/SM_Rock")
    assert "/Game/Mods/MyMod/Meshes/SM_Rock" not in engine.assets


# --- system --------------------------------------------------------------------

def test_capabilities(engine):
    caps = call("get_server_capabilities")
    assert caps["engine_available"] and caps["capabilities"]["editor_actor_subsystem"]
    assert caps["terrain_editing"].startswith("heightmap file")


def test_nested_path_arguments_are_validated(engine):
    err = call_err("spawn_actors_batch", actors=[{"asset_path": "/Game/../../Windows/x"}])
    assert "traversal" in err


def test_readonly_mode_blocks_new_write_tools(engine, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_WRITE_TOOLS", False)
    assert "SAFE_WRITE" in call_err("delete_actors", actors=["SM_Wall_01"])


# --- skills, rich results, deferred work --------------------------------------

def test_skills_are_served_as_prompts():
    from conan_mcp.core.registry import prompt_registry
    from conan_mcp.prompts import load_skills
    names = {s["name"] for s in load_skills()}
    assert {"conan-map-design", "conan-landscape-sculpting", "conan-structures", "conan-items-recipes",
            "conan-blueprint-authoring", "conan-mod-release", "conan-mcp-safety",
            "conan-animation-from-reference", "conan-custom-attacks-vfx"} <= names
    for s in load_skills():
        assert s.get("description"), s["name"]
    msg = prompt_registry.get_prompt("conan-map-design", {"goal": "Add a desert village"})
    text = msg["messages"][0]["content"]["text"]
    assert "Design rules" in text and text.endswith("Add a desert village")


def test_image_results_become_mcp_image_content(monkeypatch):
    from conan_mcp.core.registry import registry
    from conan_mcp.core.results import ToolResult
    registry.register("_test_image", "Test", "test", {"properties": {}}, "READ_ONLY",
                      lambda a: ToolResult({"ok": True}, images=[(b"\x89PNGfake", "image/png")]))
    try:
        res = call_tool("_test_image", {})
        assert res["content"][1]["type"] == "image" and res["content"][1]["mimeType"] == "image/png"
    finally:
        registry.tools.pop("_test_image")


def test_deferred_results_through_the_game_thread_queue(monkeypatch):
    from conan_mcp.core import dispatcher
    from conan_mcp.core.results import Deferred
    from conan_mcp.core.state import STATE
    import threading
    polls = {"n": 0}

    def poll():
        polls["n"] += 1
        return polls["n"] >= 3, "done"

    monkeypatch.setattr(STATE, "ticker_handle", "fake")
    monkeypatch.setattr(STATE, "game_thread_ident", None)
    stop = threading.Event()

    def engine_loop():
        while not stop.is_set():
            dispatcher._game_thread_ticker(0.0)
            stop.wait(0.01)

    t = threading.Thread(target=engine_loop, daemon=True)
    t.start()
    try:
        assert dispatcher.execute_on_game_thread(lambda: Deferred(poll, timeout=5)) == "done"
    finally:
        stop.set()
        t.join()
    assert polls["n"] >= 3


def test_capture_viewport_waits_for_file(engine, monkeypatch):
    class Automation:
        @staticmethod
        def take_high_res_screenshot(w, h, path, *a):
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(fu, "AutomationLibrary", Automation, raising=False)
    res = call_tool("capture_viewport", {"width": 320, "height": 200})
    assert not res["isError"], res
    assert res["content"][1]["type"] == "image"
