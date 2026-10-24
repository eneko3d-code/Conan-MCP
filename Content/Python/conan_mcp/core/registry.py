"""Tool, resource and prompt registries."""

import json
from typing import Any, Callable, Dict, List, Optional

from .security import DESTRUCTIVE, READ_ONLY


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def clear(self):
        self.tools.clear()

    def register(self, name: str, category: str, description: str, input_schema: dict,
                 security_level: str, handler: Callable, idempotent: Optional[bool] = None,
                 off_game_thread: bool = False, open_world: bool = False):
        """off_game_thread: the handler does network/IO work and must not block the Game Thread;
        it runs on the request thread and uses execute_on_game_thread() itself for engine calls."""
        if "type" not in input_schema:
            input_schema = {"type": "object", **input_schema}
        self.tools[name] = {
            "name": name,
            "category": category,
            "summary": description,
            "description": f"[{category}][{security_level}] {description}",
            "inputSchema": input_schema,
            "security": security_level,
            "handler": handler,
            "idempotent": security_level == READ_ONLY if idempotent is None else idempotent,
            "off_game_thread": off_game_thread,
            "open_world": open_world,
        }

    def tool(self, name: str, category: str, description: str, security_level: str,
             properties: Optional[dict] = None, required: Optional[List[str]] = None, **kwargs):
        """Decorator form: @registry.tool("name", "Category", "desc", READ_ONLY, {...props}, ["req"])."""
        def wrap(fn):
            schema = {"type": "object", "properties": properties or {}}
            if required:
                schema["required"] = list(required)
            self.register(name, category, description, schema, security_level, fn, **kwargs)
            return fn
        return wrap

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        return self.tools.get(name)

    def list_tools_schema(self) -> List[Dict[str, Any]]:
        return [{
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
            "annotations": {
                "readOnlyHint": t["security"] == READ_ONLY,
                "destructiveHint": t["security"] == DESTRUCTIVE,
                "idempotentHint": bool(t["idempotent"]),
                "openWorldHint": bool(t.get("open_world")),
            },
        } for t in self.tools.values()]


class ResourceRegistry:
    def __init__(self):
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.templates: List[Dict[str, Any]] = []

    def clear(self):
        self.resources.clear()
        self.templates.clear()

    def register(self, uri: str, name: str, mime_type: str, description: str, handler):
        self.resources[uri] = {"uri": uri, "name": name, "mimeType": mime_type,
                               "description": description, "handler": handler}

    def register_template(self, uri_template: str, name: str, mime_type: str, description: str, handler):
        self.templates.append({"uriTemplate": uri_template, "name": name, "mimeType": mime_type,
                               "description": description, "handler": handler})

    def list_resources_schema(self) -> List[Dict[str, Any]]:
        return [{k: r[k] for k in ("uri", "name", "mimeType", "description")} for r in self.resources.values()]

    def list_templates_schema(self) -> List[Dict[str, Any]]:
        return [{k: t[k] for k in ("uriTemplate", "name", "mimeType", "description")} for t in self.templates]

    def read_resource(self, uri: str, runner) -> Dict[str, Any]:
        """``runner(fn, *args)`` executes the handler (normally on the Game Thread)."""
        if uri in self.resources:
            r = self.resources[uri]
            data = runner(r["handler"], uri)
            return {"uri": uri, "mimeType": r["mimeType"],
                    "text": data if isinstance(data, str) else json.dumps(data, indent=2)}
        for t in self.templates:
            prefix = t["uriTemplate"].split("{")[0]
            if uri.startswith(prefix):
                data = runner(t["handler"], uri, uri[len(prefix):])
                return {"uri": uri, "mimeType": t["mimeType"],
                        "text": data if isinstance(data, str) else json.dumps(data, indent=2)}
        raise ValueError(f"Resource not found: '{uri}'")


class PromptRegistry:
    def __init__(self):
        self.prompts: Dict[str, Dict[str, Any]] = {}

    def clear(self):
        self.prompts.clear()

    def register(self, name: str, description: str, arguments: List[Dict[str, Any]], handler):
        self.prompts[name] = {"name": name, "description": description, "arguments": arguments, "handler": handler}

    def list_prompts_schema(self) -> List[Dict[str, Any]]:
        return [{k: p[k] for k in ("name", "description", "arguments")} for p in self.prompts.values()]

    def get_prompt(self, name: str, arguments: dict) -> Dict[str, Any]:
        if name not in self.prompts:
            raise ValueError(f"Prompt '{name}' not found")
        return self.prompts[name]["handler"](arguments or {})


registry = ToolRegistry()
resource_registry = ResourceRegistry()
prompt_registry = PromptRegistry()
