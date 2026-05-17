from __future__ import annotations
import json
import os

from app.tools import registry, ToolContext, validate_path, YELLOW


@registry.register(
    name="read_file",
    description="Read a file from the container filesystem. Limited to /data, /tmp, and /obsidian (Obsidian vault qDome).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path (must start with /data/, /tmp/, or /obsidian/)"},
        },
        "required": ["path"],
    },
)
async def read_file(context: ToolContext, path: str) -> str:
    err = validate_path(path)
    if err:
        return json.dumps({"success": False, "error": "path_blocked", "reason": err})
    if not os.path.exists(path):
        return json.dumps({"success": False, "error": "not_found", "reason": f"File not found: {path}"})
    try:
        with open(path, "r") as f:
            content = f.read(10240)  # 10KB max
        return json.dumps({"success": True, "result": content})
    except Exception as e:
        return json.dumps({"success": False, "error": "read_error", "reason": str(e)})


@registry.register(
    name="write_file",
    description="Write content to a file. Limited to /data, /tmp, and /obsidian (Obsidian vault qDome).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path (must start with /data/, /tmp/, or /obsidian/)"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    safety=YELLOW,
)
async def write_file(context: ToolContext, path: str, content: str) -> str:
    err = validate_path(path)
    if err:
        return json.dumps({"success": False, "error": "path_blocked", "reason": err})
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return json.dumps({"success": True, "result": f"Written {len(content)} bytes to {path}"})
    except Exception as e:
        return json.dumps({"success": False, "error": "write_error", "reason": str(e)})


@registry.register(
    name="list_files",
    description="List files in a directory. Limited to /data, /tmp, and /obsidian (Obsidian vault qDome).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path (must start with /data/, /tmp/, or /obsidian/)"},
        },
        "required": ["path"],
    },
)
async def list_files(context: ToolContext, path: str) -> str:
    err = validate_path(path)
    if err:
        return json.dumps({"success": False, "error": "path_blocked", "reason": err})
    if not os.path.isdir(path):
        return json.dumps({"success": False, "error": "not_found", "reason": f"Directory not found: {path}"})
    try:
        entries = os.listdir(path)
        return json.dumps({"success": True, "result": entries})
    except Exception as e:
        return json.dumps({"success": False, "error": "list_error", "reason": str(e)})
