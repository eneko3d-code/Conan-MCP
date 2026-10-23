"""DataTable tools: real row reads, schema, search, add/update/duplicate/remove rows, JSON/CSV export & import.

Writes round-trip the whole table through JSON (DataTableFunctionLibrary) inside
an undoable transaction. Base-game tables are read-only unless explicitly
allowed: mods should put their rows in their own tables under /Game/Mods.
"""

import csv
import io
import json

from ..core import ue
from ..core.security import READ_ONLY, SAFE_WRITE

EXPORT_DIR = "datatables"


def _load_table(path):
    u = ue.require()
    dt = ue.load_asset(path)
    if not isinstance(dt, u.DataTable):
        raise ValueError(f"'{path}' is not a DataTable (it is a {ue.class_name(dt)})")
    return dt


def _lib():
    u = ue.require()
    lib = getattr(u, "DataTableFunctionLibrary", None)
    if lib is None or not hasattr(lib, "export_data_table_to_json_string"):
        raise ue.UnsupportedError("DataTableFunctionLibrary.export_data_table_to_json_string is not available")
    return lib


def read_rows(dt):
    """Rows as a list of dicts, each with its row name under 'Name'."""
    raw = _lib().export_data_table_to_json_string(dt)
    rows = json.loads(raw) if raw else []
    if isinstance(rows, dict):  # some versions export {RowName: {...}}
        rows = [{"Name": k, **v} for k, v in rows.items()]
    return rows


def write_rows(dt, rows, description):
    lib = _lib()
    if not hasattr(lib, "fill_data_table_from_json_string"):
        raise ue.UnsupportedError("DataTableFunctionLibrary.fill_data_table_from_json_string is not available")
    payload = json.dumps(rows)
    with ue.transaction(description):
        dt.modify()
        ok = lib.fill_data_table_from_json_string(dt, payload)
    if ok is False:
        raise RuntimeError("Unreal rejected the JSON (field names or value formats do not match the row struct)")
    return read_rows(dt)


def _guard_writable(path, args):
    if not path.startswith("/Game/Mods/") and not args.get("allow_base_game_table"):
        raise PermissionError(
            f"'{path}' is not inside /Game/Mods/. Editing base-game tables breaks other mods and game updates; "
            "copy rows into your mod's own table instead, or pass allow_base_game_table=true if you really mean it.")


def _row_name(row):
    return str(row.get("Name", row.get("RowName", "")))


def _find(rows, name):
    for i, r in enumerate(rows):
        if _row_name(r) == name:
            return i
    return -1


def _maybe_save(dt, args):
    if args.get("save"):
        ue.require().EditorAssetLibrary.save_loaded_asset(dt, False)
        return True
    return False


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def tool_get_datatable_row(args):
    dt = _load_table(args["datatable_path"])
    rows = read_rows(dt)
    idx = _find(rows, args["row_name"])
    if idx < 0:
        close = [_row_name(r) for r in rows if args["row_name"].lower() in _row_name(r).lower()][:20]
        raise ValueError(f"Row '{args['row_name']}' not found. Similar rows: {close}")
    return {"datatable": dt.get_name(), "row_name": args["row_name"], "row_data": rows[idx]}


def tool_get_datatable_schema(args):
    dt = _load_table(args["datatable_path"])
    struct = None
    try:
        rs = dt.get_editor_property("row_struct")
        struct = rs.get_path_name() if rs else None
    except Exception:
        pass
    rows = read_rows(dt)
    columns = {}
    for r in rows[:200]:
        for k, v in r.items():
            if k == "Name":
                continue
            t = type(v).__name__
            col = columns.setdefault(k, {"types": set(), "example": v})
            col["types"].add(t)
    return {
        "datatable": dt.get_name(), "row_struct": struct, "row_count": len(rows),
        "columns": {k: {"json_types": sorted(c["types"]), "example": c["example"]} for k, c in columns.items()},
        "template_row": rows[0] if rows else None,
    }


def _matches(row, query, field, equals, contains):
    if field:
        v = row.get(field)
        if equals is not None and str(v) != str(equals):
            return False
        if contains and contains.lower() not in json.dumps(v).lower():
            return False
        return True
    if query:
        return query.lower() in json.dumps(row).lower()
    return True


def tool_search_datatable_rows(args):
    dt = _load_table(args["datatable_path"])
    rows = read_rows(dt)
    q, field = args.get("query", ""), args.get("field", "")
    eq, contains = args.get("equals"), args.get("contains", "")
    hits = [r for r in rows if _matches(r, q, field, eq, contains)]
    offset = max(int(args.get("offset", 0)), 0)
    limit = min(max(int(args.get("limit", 25)), 1), 200)
    fields = args.get("fields")
    page = hits[offset:offset + limit]
    if fields:
        page = [{"Name": _row_name(r), **{f: r.get(f) for f in fields}} for r in page]
    return {"datatable": dt.get_name(), "total_rows": len(rows), "total_matching": len(hits),
            "offset": offset, "returned": len(page), "has_more": offset + len(page) < len(hits), "rows": page}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _merge(base, patch):
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def tool_add_datatable_row(args):
    path = args["datatable_path"]
    _guard_writable(path, args)
    dt = _load_table(path)
    rows = read_rows(dt)
    name = args["row_name"]
    if _find(rows, name) >= 0:
        raise ValueError(f"Row '{name}' already exists; use update_datatable_row")
    base = {}
    if args.get("template_row"):
        idx = _find(rows, args["template_row"])
        if idx < 0:
            raise ValueError(f"Template row '{args['template_row']}' not found")
        base = rows[idx]
    elif rows:
        base = rows[0]  # keep every column so the struct import succeeds
    new = _merge(base, args.get("values") or {})
    new["Name"] = name
    if args.get("dry_run"):
        return {"dry_run": True, "new_row": new}
    after = write_rows(dt, rows + [new], f"ConanMCP: Add row {name}")
    if _find(after, name) < 0:
        raise RuntimeError("Row was not added (check the values against get_datatable_schema)")
    return {"added": name, "row_count": len(after), "saved": _maybe_save(dt, args), "row": after[_find(after, name)]}


def tool_update_datatable_row(args):
    path = args["datatable_path"]
    _guard_writable(path, args)
    dt = _load_table(path)
    rows = read_rows(dt)
    name = args["row_name"]
    idx = _find(rows, name)
    if idx < 0:
        raise ValueError(f"Row '{name}' not found")
    updated = _merge(rows[idx], args.get("values") or {})
    updated["Name"] = name
    if args.get("dry_run"):
        return {"dry_run": True, "before": rows[idx], "after": updated}
    rows[idx] = updated
    after = write_rows(dt, rows, f"ConanMCP: Update row {name}")
    return {"updated": name, "saved": _maybe_save(dt, args), "row": after[_find(after, name)]}


def tool_duplicate_datatable_row(args):
    path = args.get("destination_path") or args["datatable_path"]
    _guard_writable(path, args)
    src_dt = _load_table(args["datatable_path"])
    src_rows = read_rows(src_dt)
    idx = _find(src_rows, args["row_name"])
    if idx < 0:
        raise ValueError(f"Row '{args['row_name']}' not found")
    dst_dt = src_dt if path == args["datatable_path"] else _load_table(path)
    dst_rows = src_rows if dst_dt is src_dt else read_rows(dst_dt)
    new_name = args["new_row_name"]
    if _find(dst_rows, new_name) >= 0:
        raise ValueError(f"Row '{new_name}' already exists in the destination")
    new = _merge(src_rows[idx], args.get("values") or {})
    new["Name"] = new_name
    if args.get("dry_run"):
        return {"dry_run": True, "new_row": new, "destination": path}
    after = write_rows(dst_dt, dst_rows + [new], f"ConanMCP: Duplicate row {args['row_name']} -> {new_name}")
    return {"created": new_name, "destination": path, "saved": _maybe_save(dst_dt, args), "row": after[_find(after, new_name)]}


def tool_remove_datatable_row(args):
    path = args["datatable_path"]
    _guard_writable(path, args)
    dt = _load_table(path)
    rows = read_rows(dt)
    names = args.get("row_names") or [args.get("row_name")]
    missing = [n for n in names if _find(rows, n) < 0]
    if missing:
        raise ValueError(f"Rows not found: {missing}")
    if args.get("dry_run"):
        return {"dry_run": True, "would_remove": names}
    keep = [r for r in rows if _row_name(r) not in set(names)]
    after = write_rows(dt, keep, f"ConanMCP: Remove {len(names)} rows")
    return {"removed": names, "row_count": len(after), "saved": _maybe_save(dt, args)}


def _flatten(value):
    return value if isinstance(value, (str, int, float, bool)) or value is None else json.dumps(value)


def tool_export_datatable(args):
    dt = _load_table(args["datatable_path"])
    rows = read_rows(dt)
    fmt = args.get("format", "json")
    name = args.get("file_name") or f"{dt.get_name()}.{fmt}"
    out = ue.safe_file(name, EXPORT_DIR)
    if fmt == "json":
        text = json.dumps(rows, indent=2)
    else:
        cols = ["Name"] + sorted({k for r in rows for k in r if k != "Name"})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: _flatten(r.get(k)) for k in cols})
        text = buf.getvalue()
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return {"written": out, "rows": len(rows), "format": fmt}


def tool_import_datatable(args):
    path = args["datatable_path"]
    _guard_writable(path, args)
    dt = _load_table(path)
    src = ue.safe_file(args["file_name"], EXPORT_DIR)
    with open(src, encoding="utf-8") as f:
        incoming = json.load(f)
    if not isinstance(incoming, list):
        raise ValueError("Import file must be a JSON array of rows (as written by export_datatable)")
    rows = read_rows(dt)
    mode = args.get("mode", "merge")
    if mode == "replace":
        final = incoming
    else:
        final = list(rows)
        for r in incoming:
            i = _find(final, _row_name(r))
            if i >= 0:
                final[i] = _merge(final[i], r)
            else:
                final.append(r)
    if args.get("dry_run"):
        return {"dry_run": True, "rows_before": len(rows), "rows_after": len(final), "mode": mode}
    after = write_rows(dt, final, f"ConanMCP: Import {len(incoming)} rows")
    return {"imported": len(incoming), "row_count": len(after), "mode": mode, "saved": _maybe_save(dt, args)}


def register(registry):
    dt_path = {"datatable_path": {"type": "string", "description": "DataTable asset path"}}
    write_flags = {"dry_run": {"type": "boolean"}, "save": {"type": "boolean", "description": "Save the asset after editing"},
                   "allow_base_game_table": {"type": "boolean", "description": "Allow editing tables outside /Game/Mods"}}
    registry.register("get_datatable_row", "DataTables", "Returns the full data of one DataTable row as JSON.",
                      {"properties": {**dt_path, "row_name": {"type": "string"}}, "required": ["datatable_path", "row_name"]},
                      READ_ONLY, tool_get_datatable_row)
    registry.register("get_datatable_schema", "DataTables",
                      "Columns of a DataTable (row struct, JSON types, example values) plus a template row to copy.",
                      {"properties": dt_path, "required": ["datatable_path"]}, READ_ONLY, tool_get_datatable_schema)
    registry.register("search_datatable_rows", "DataTables",
                      "Finds rows by free-text query or by field equals/contains, with pagination and field selection.",
                      {"properties": {**dt_path, "query": {"type": "string"}, "field": {"type": "string"},
                                      "equals": {}, "contains": {"type": "string"},
                                      "fields": {"type": "array", "items": {"type": "string"}},
                                      "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
                       "required": ["datatable_path"]}, READ_ONLY, tool_search_datatable_rows)
    registry.register("add_datatable_row", "DataTables",
                      "Adds a row, copying every column from template_row (or the first row) and overriding 'values'. Undoable.",
                      {"properties": {**dt_path, "row_name": {"type": "string"}, "template_row": {"type": "string"},
                                      "values": {"type": "object"}, **write_flags},
                       "required": ["datatable_path", "row_name"]}, SAFE_WRITE, tool_add_datatable_row, idempotent=False)
    registry.register("update_datatable_row", "DataTables", "Deep-merges 'values' into an existing row. Undoable.",
                      {"properties": {**dt_path, "row_name": {"type": "string"}, "values": {"type": "object"}, **write_flags},
                       "required": ["datatable_path", "row_name", "values"]}, SAFE_WRITE, tool_update_datatable_row)
    registry.register("duplicate_datatable_row", "DataTables",
                      "Copies a row (optionally into another table, e.g. base ItemTable -> your mod table) under a new name with overrides.",
                      {"properties": {**dt_path, "row_name": {"type": "string"}, "new_row_name": {"type": "string"},
                                      "destination_path": {"type": "string"}, "values": {"type": "object"}, **write_flags},
                       "required": ["datatable_path", "row_name", "new_row_name"]}, SAFE_WRITE, tool_duplicate_datatable_row, idempotent=False)
    registry.register("remove_datatable_row", "DataTables", "Removes one or more rows. Undoable.",
                      {"properties": {**dt_path, "row_name": {"type": "string"},
                                      "row_names": {"type": "array", "items": {"type": "string"}}, **write_flags},
                       "required": ["datatable_path"]}, SAFE_WRITE, tool_remove_datatable_row)
    registry.register("export_datatable", "DataTables", "Exports a DataTable to JSON or CSV in Saved/ConanMCP/datatables.",
                      {"properties": {**dt_path, "format": {"type": "string", "enum": ["json", "csv"]}, "file_name": {"type": "string"}},
                       "required": ["datatable_path"]}, READ_ONLY, tool_export_datatable)
    registry.register("import_datatable", "DataTables",
                      "Imports rows from a JSON file in Saved/ConanMCP/datatables (merge by row name, or replace). Undoable.",
                      {"properties": {**dt_path, "file_name": {"type": "string"}, "mode": {"type": "string", "enum": ["merge", "replace"]},
                                      **write_flags},
                       "required": ["datatable_path", "file_name"]}, SAFE_WRITE, tool_import_datatable)
