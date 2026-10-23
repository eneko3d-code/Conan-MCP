"""Security levels, package-path validation and lightweight JSON-Schema checks."""

from typing import Any, Optional

from . import config

READ_ONLY = "READ_ONLY"
SAFE_WRITE = "SAFE_WRITE"
DESTRUCTIVE = "DESTRUCTIVE"

# Argument names whose (string) values are package/asset paths, at any nesting depth
PATH_ARG_NAMES = {
    "package_path", "asset_path", "path", "datatable_path", "blueprint_path", "particle_path",
    "mesh_path", "mod_path", "source_path", "destination_path", "template_path", "target_path", "copy_struct_from",
}
PATH_LIST_ARG_NAMES = {"asset_paths", "package_paths"}


def validate_package_path(value: str, arg_name: str = "path") -> None:
    """Rejects package/asset paths outside the allowed roots or containing traversal sequences."""
    if not isinstance(value, str) or not value:
        return
    if ".." in value or "\\" in value or "//" in value or "\0" in value:
        raise ValueError(f"Invalid '{arg_name}': traversal sequences are not allowed")
    roots = config.ALLOWED_PACKAGE_ROOTS
    if not any(value == root or value.startswith(root + "/") for root in roots):
        raise ValueError(f"Invalid '{arg_name}': must start with one of {', '.join(roots)}")


def _validate_paths(obj: Any, depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in PATH_ARG_NAMES and isinstance(value, str):
                validate_package_path(value.strip(), key)
            elif key in PATH_LIST_ARG_NAMES and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        validate_package_path(item.strip(), key)
            else:
                _validate_paths(value, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _validate_paths(item, depth + 1)


_JSON_TYPES = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate_against_schema(args: dict, schema: Optional[dict]) -> None:
    """Minimal JSON-Schema check: required fields, primitive types, enum, min/max, array length."""
    if not schema:
        return
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args or args[name] is None:
            raise ValueError(f"Missing required argument '{name}'")
    for name, value in args.items():
        spec = props.get(name)
        if not spec or value is None:
            continue
        expected = spec.get("type")
        types = expected if isinstance(expected, list) else [expected]
        known = [t for t in types if t in _JSON_TYPES]
        if known:
            ok = False
            for t in known:
                if isinstance(value, _JSON_TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool)):
                    ok = True
            if not ok:
                raise ValueError(f"Argument '{name}' must be of type {'/'.join(known)}")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"Argument '{name}' must be one of {spec['enum']}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                raise ValueError(f"Argument '{name}' must be >= {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise ValueError(f"Argument '{name}' must be <= {spec['maximum']}")
        if isinstance(value, list) and "maxItems" in spec and len(value) > spec["maxItems"]:
            raise ValueError(f"Argument '{name}' accepts at most {spec['maxItems']} items")


def validate_tool_arguments(args: Any, schema: Optional[dict] = None) -> None:
    """Validates a tool call's arguments (schema + every path-like value) before it reaches the engine."""
    if not isinstance(args, dict):
        raise ValueError("'arguments' must be a JSON object")
    validate_against_schema(args, schema)
    _validate_paths(args)


def check_level_allowed(level: str) -> Optional[str]:
    """Returns an error message if the security level is disabled, else None."""
    if level == SAFE_WRITE and not config.ENABLE_WRITE_TOOLS:
        return "Security error: SAFE_WRITE tools are disabled (CONAN_MCP_READONLY=1)"
    if level == DESTRUCTIVE and not config.ENABLE_DESTRUCTIVE_TOOLS:
        return "Security error: DESTRUCTIVE tools are disabled (set CONAN_MCP_ENABLE_DESTRUCTIVE=1 to allow)"
    return None
