"""Serves the plugin's skills (skills/<name>/SKILL.md) as MCP prompts.

The same files can be installed as Claude Code / Antigravity skills, so every
MCP client gets identical guidance.
"""

import os
import re
from typing import Dict, List

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def skills_dir() -> str:
    # Content/Python/conan_mcp/prompts.py -> plugin root / skills
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "..", "skills"))


def parse_skill(text: str) -> Dict[str, str]:
    meta, body = {}, text
    m = _FRONTMATTER.match(text)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip('"').strip("'")
    meta["body"] = body.strip()
    return meta


def load_skills() -> List[Dict[str, str]]:
    root = skills_dir()
    skills = []
    if not os.path.isdir(root):
        return skills
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name, "SKILL.md")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                skill = parse_skill(f.read())
            skill.setdefault("name", name)
            skills.append(skill)
    return skills


def _make_handler(skill):
    def handler(args):
        goal = (args or {}).get("goal", "").strip()
        text = skill["body"]
        if goal:
            text += f"\n\n---\n## Current task\n{goal}"
        return {
            "description": skill.get("description", ""),
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }
    return handler


def register(prompt_registry):
    for skill in load_skills():
        prompt_registry.register(
            skill["name"],
            skill.get("description", ""),
            [{"name": "goal", "description": "What you want to achieve (optional)", "required": False}],
            _make_handler(skill),
        )
