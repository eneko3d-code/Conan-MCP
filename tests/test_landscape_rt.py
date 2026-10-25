"""Render-target landscape backend (no C++): round-trip exactness, sculpting, backups, verify/restore, painting."""

import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "Content", "Python"))
sys.path.insert(0, HERE)

import fake_unreal as fu  # noqa: E402
import conan_mcp_server  # noqa: E402,F401
from conan_mcp.core import config, ue  # noqa: E402
from conan_mcp.core.protocol import call_tool  # noqa: E402
from conan_mcp.mapping import heightmap as hm  # noqa: E402


@pytest.fixture()
def rt_engine(monkeypatch, tmp_path):
    eng = fu.reset()
    monkeypatch.setattr(ue, "unreal", fu)
    monkeypatch.setattr(fu, "ConanMCPEditorLibrary", None, raising=False)
    for name, obj in fu.RT_APIS.items():
        monkeypatch.setattr(fu, name, obj, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ENABLE_WRITE_TOOLS", True)
    return eng


def call(_tool, **args):
    res = call_tool(_tool, args)
    if res["isError"]:
        raise AssertionError(res["content"][0]["text"])
    return json.loads(res["content"][0]["text"])


def call_err(_tool, **args):
    res = call_tool(_tool, args)
    assert res["isError"], res
    return res["content"][0]["text"]


def test_rg_pack_roundtrip():
    g = hm.HeightGrid(3, 2, [0, 1, 255, 256, 32768, 65535])

    class P:
        def __init__(self, r, gg):
            self.r, self.g = r, gg

    raw = hm.pack_rg(g)
    pixels = [P(raw[i] / 255.0, raw[i + 1] / 255.0) for i in range(0, len(raw), 4)]
    assert list(hm.unpack_rg(pixels, 3, 2).data) == list(g.data)
    pixels255 = [P(raw[i], raw[i + 1]) for i in range(0, len(raw), 4)]  # 0-255 readback also works
    assert list(hm.unpack_rg(pixels255, 3, 2).data) == list(g.data)


def test_rgba_png_codec():
    rgba = bytes(range(256)) * 4
    w, h, ch, depth, raw = hm.decode_png(hm.encode_png_rgba8(16, 16, rgba))
    assert (w, h, ch, depth) == (16, 16, 4, 8) and raw == rgba


def test_capabilities_and_info_report_render_target(rt_engine):
    fu.make_rt_landscape()
    caps = call("get_server_capabilities")
    assert caps["terrain_editing"] == "render_target" and caps["capabilities"]["landscape_rt_export"]
    info = call("get_landscape_info")
    assert info["editing_backend"] == "render_target"
    assert info["render_target_layout"]["width"] == 65 and info["render_target_layout"]["height"] == 65


def test_unchanged_roundtrip_is_exact(rt_engine):
    land = fu.make_rt_landscape()
    before = list(land.heights.data)
    out = call("test_landscape_backend", write_test=True)
    assert out["result"] == "ok" and out["write_test"]["exact"] and out["second_read_identical"]
    assert list(land.heights.data) == before
    assert out["heights"]["unique_values"] > 1


def test_srgb_must_be_disabled(rt_engine, monkeypatch):
    """If the transient texture stayed sRGB, heights would be corrupted: verify catches it and restores."""
    land = fu.make_rt_landscape()
    before = list(land.heights.data)
    monkeypatch.setattr(fu._Texture, "set_editor_property", lambda self, k, v: None)  # srgb can't be turned off
    err = call_err("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=800, amount=100)
    assert "not exact" in err
    # the restore goes through the same broken path: the user is told how to recover by hand
    assert "could not be confirmed" in err and "Landscape mode" in err and ".png" in err
    assert len(before) == len(land.heights.data)


def test_sculpt_raise_only_changes_region_and_backs_up(rt_engine):
    land = fu.make_rt_landscape()
    before = land.heights.copy()
    dry = call("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=500, amount=200, dry_run=True)
    assert dry["backend"] == "render_target" and land.imports == 0
    out = call("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=500, amount=200, falloff=0)
    assert out["verified"] and out["backup"].endswith(".png") and "read_s" in out["timings"]
    assert land.heights.get(32, 32) == before.get(32, 32) + 256  # 200 cm at scale 100
    assert land.heights.get(0, 0) == before.get(0, 0) and land.heights.get(64, 64) == before.get(64, 64)
    backups = call("list_heightmap_backups")["backups"]
    assert backups and backups[0]["file_name"] == out["backup"]

    restored = call("restore_heightmap_backup", file_name=out["backup"])
    assert restored["verified"] and list(land.heights.data) == list(before.data)


def test_flatten_and_export_import(rt_engine):
    land = fu.make_rt_landscape()
    call("sculpt_terrain", operation="flatten", center={"x": 1000, "y": 1000}, radius=400, target_z=0, falloff=0)
    assert land.heights.get(10, 10) == 32768
    exp = call("export_heightmap", file_name="hm.png")
    assert exp["backend"] == "render_target" and (exp["width"], exp["height"]) == (65, 65)
    with open(exp["written"], "rb") as f:
        grid = hm.decode_png16(f.read())
    grid.set(40, 40, 40000)
    with open(exp["written"], "wb") as f:
        f.write(hm.encode_png16(grid))
    imp = call("import_heightmap", file_name="hm.png")
    assert imp["verified"] and land.heights.get(40, 40) == 40000
    with open(exp["written"], "wb") as f:
        f.write(hm.encode_png16(hm.HeightGrid(10, 10)))
    assert "landscape needs 65x65" in call_err("import_heightmap", file_name="hm.png")


def test_streaming_proxy_only(rt_engine):
    proxy = fu.make_rt_landscape(cls=fu.LandscapeStreamingProxy, label="LandscapeStreamingProxy_0")
    before = proxy.heights.get(20, 20)
    call("sculpt_terrain", operation="lower", center={"x": 2000, "y": 2000}, radius=300, amount=100, falloff=0)
    assert proxy.heights.get(20, 20) == before - 128


def test_paint_requires_replace_layer(rt_engine):
    land = fu.make_rt_landscape()
    assert "REPLACES the whole layer" in call_err("paint_landscape_layer", layer="Sand", center={"x": 3200, "y": 3200}, radius=500)
    dry = call("paint_landscape_layer", layer="Sand", center={"x": 3200, "y": 3200}, radius=500, replace_layer=True, dry_run=True)
    assert dry["painted_vertices"] > 0 and not land.weights
    out = call("paint_landscape_layer", layer="Sand", center={"x": 3200, "y": 3200}, radius=500, replace_layer=True, falloff=0)
    assert out["replaced_layer"]
    w = land.weights["Sand"]
    assert w[32 * 65 + 32] == 255 and w[0] == 0


def test_explicit_native_mode_explains(rt_engine):
    fu.make_rt_landscape()
    assert "cannot compile" in call_err("sculpt_terrain", operation="raise", center={"x": 0, "y": 0}, mode="native")


# --- 2.2.2: grouping, first-read blanks, independent trace checks -------------------

def test_two_landscapes_are_never_merged(rt_engine):
    """AlmostEmpty: two 249x249 landscapes side by side must each be their own grid."""
    a = fu.make_rt_landscape(size=249, label="Landscape")
    b = fu.make_rt_landscape(size=249, label="Landscape2", min_corner=(24800.0, 0.0), base=30000)
    info = call("get_landscape_info", landscape="Landscape2")
    lay = info["render_target_layout"]
    assert (lay["width"], lay["height"]) == (249, 249) and lay["members"] == ["Landscape2"]
    exp = call("export_heightmap", landscape="Landscape2", file_name="l2.png")
    assert exp["min_units"] >= 30000 and exp["min_units"] > 0  # no zero columns from the other landscape
    b_before = list(b.heights.data)
    call("sculpt_terrain", landscape="Landscape", operation="raise", center={"x": 12400, "y": 12400}, radius=500, amount=100)
    assert list(b.heights.data) == b_before and a.imports == 1 and b.imports == 0


def test_proxy_groups_with_its_owner(rt_engine):
    main = fu.make_rt_landscape(size=65, label="Landscape")
    proxy = fu.make_rt_landscape(cls=fu.LandscapeStreamingProxy, size=65, label="Proxy_1")
    proxy.owner = main
    lay = call("get_landscape_info", landscape="Proxy_1")["render_target_layout"]
    assert sorted(lay["members"]) == ["Landscape", "Proxy_1"] and lay["label"] == "Landscape"


def test_first_reads_blank_are_retried_before_writing(rt_engine):
    land = fu.make_rt_landscape()
    land.blank_exports = 2  # first export(s) of the session render nothing
    before = land.heights.copy()
    out = call("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=500, amount=100, falloff=0)
    assert out["timings"]["read_attempts"] == 3 and out["verified"] is True
    assert land.heights.get(0, 0) == before.get(0, 0)  # nothing flattened to -128 m
    assert min(land.heights.data) > 0


def test_never_valid_read_writes_nothing(rt_engine, monkeypatch):
    from conan_mcp.tools import landscape_rt
    real = landscape_rt.ready_heights
    monkeypatch.setattr(landscape_rt, "ready_heights",
                        lambda lay, then, **k: real(lay, then, max_wait_s=0.3, min_interval_s=0.05, **{x: y for x, y in k.items() if x == "allow_zero_heights"}))
    land = fu.make_rt_landscape()
    land.blank_exports = 10 ** 6
    err = call_err("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=500, amount=100)
    assert "Nothing was written" in err and land.imports == 0


def test_zero_columns_in_read_are_rejected(rt_engine, monkeypatch):
    from conan_mcp.tools import landscape_rt
    real = landscape_rt.ready_heights
    monkeypatch.setattr(landscape_rt, "ready_heights",
                        lambda lay, then, **k: real(lay, then, max_wait_s=0.3, min_interval_s=0.05))
    land = fu.make_rt_landscape()

    def zero_columns(g):
        for y in range(g.height):
            for x in range(40, g.width):
                g.data[y * g.width + x] = 0
        return g
    land.corrupt_export = zero_columns
    err = call_err("sculpt_terrain", operation="raise", center={"x": 1000, "y": 1000}, radius=300, amount=100)
    assert "exactly 0" in err and land.imports == 0


def test_traces_veto_a_wrong_read(rt_engine):
    """A plausible but wrong read (all heights shifted) must be caught by line traces before writing."""
    land = fu.make_rt_landscape()

    def shifted(g):
        g.data = type(g.data)("H", [min(65535, v + 1000) for v in g.data])  # +7.8 m everywhere
        return g
    land.corrupt_export = shifted
    err = call_err("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=500, amount=100)
    assert "do not match the real terrain" in err and "Nothing was written" in err and land.imports == 0


def test_test_tool_reports_attempts_and_traces(rt_engine):
    land = fu.make_rt_landscape()
    land.blank_exports = 1
    out = call("test_landscape_backend", write_test=True)
    assert out["result"] == "ok" and out["read_attempts"] == 2 and out["trace_check"] == "ok"
    assert out["layout"]["members"] == ["Landscape"]


def test_post_write_trace_mismatch_restores(rt_engine, monkeypatch):
    land = fu.make_rt_landscape()
    before = list(land.heights.data)
    real_z = land.z_at
    # collision says something different from what was written, but only after the stroke is imported
    monkeypatch.setattr(land, "z_at", lambda x, y: (real_z(x, y) + 500.0) if land.imports == 1 and real_z(x, y) is not None else real_z(x, y))
    err = call_err("sculpt_terrain", operation="raise", center={"x": 3200, "y": 3200}, radius=500, amount=100)
    assert "line traces disagree" in err and "restored exactly" in err
    assert list(land.heights.data) == before
