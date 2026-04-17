#!/usr/bin/env python3
"""Native Hermes tools for the local Grok bridge."""

from __future__ import annotations

import json

from grok_bridge_client import (
    GrokBridgeError,
    bridge_chat,
    bridge_history,
    bridge_new_conversation,
    grok_bridge_health,
    grok_bridge_is_available,
)
from tools.registry import registry


def _ok(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


def grok_chat(prompt: str, timeout: int = 90, bridge_url: str | None = None, task_id: str | None = None) -> str:
    del task_id
    if not prompt.strip():
        return _err("prompt is required")
    try:
        result = bridge_chat(prompt.strip(), timeout=timeout, bridge_url=bridge_url)
    except GrokBridgeError as exc:
        return _err(str(exc))
    result.setdefault("success", result.get("status") == "ok")
    return _ok(result)


def grok_health(bridge_url: str | None = None, task_id: str | None = None) -> str:
    del task_id
    try:
        result = grok_bridge_health(bridge_url=bridge_url)
    except GrokBridgeError as exc:
        return _err(str(exc))
    result.setdefault("success", result.get("status") == "ok")
    return _ok(result)


def grok_new_conversation(bridge_url: str | None = None, task_id: str | None = None) -> str:
    del task_id
    try:
        result = bridge_new_conversation(bridge_url=bridge_url)
    except GrokBridgeError as exc:
        return _err(str(exc))
    result.setdefault("success", result.get("status") == "ok")
    return _ok(result)


def grok_history(bridge_url: str | None = None, task_id: str | None = None) -> str:
    del task_id
    try:
        result = bridge_history(bridge_url=bridge_url)
    except GrokBridgeError as exc:
        return _err(str(exc))
    result.setdefault("success", result.get("status") == "ok")
    return _ok(result)


def check_grok_bridge_requirements() -> bool:
    return grok_bridge_is_available()


GROK_CHAT_SCHEMA = {
    "name": "grok_chat",
    "description": (
        "Query the user's local Grok browser bridge. Use this when you need a second opinion, a Grok-native answer, "
        "or want to compare the current model against Grok. Returns the bridge JSON response including status, text, "
        "elapsed time, and bridge metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Prompt to send to Grok."},
            "timeout": {"type": "integer", "description": "Maximum wait time in seconds.", "default": 90},
            "bridge_url": {"type": "string", "description": "Optional override for the Grok bridge base URL."},
        },
        "required": ["prompt"],
    },
}

GROK_HEALTH_SCHEMA = {
    "name": "grok_health",
    "description": "Check whether the local Grok bridge is reachable and which page/profile it is attached to.",
    "parameters": {
        "type": "object",
        "properties": {
            "bridge_url": {"type": "string", "description": "Optional override for the Grok bridge base URL."},
        },
    },
}

GROK_NEW_SCHEMA = {
    "name": "grok_new_conversation",
    "description": "Tell the Grok bridge to start a fresh conversation in the attached browser session.",
    "parameters": {
        "type": "object",
        "properties": {
            "bridge_url": {"type": "string", "description": "Optional override for the Grok bridge base URL."},
        },
    },
}

GROK_HISTORY_SCHEMA = {
    "name": "grok_history",
    "description": "Read the current visible conversation text from the attached Grok browser session.",
    "parameters": {
        "type": "object",
        "properties": {
            "bridge_url": {"type": "string", "description": "Optional override for the Grok bridge base URL."},
        },
    },
}

registry.register(
    name="grok_chat",
    toolset="grok",
    schema=GROK_CHAT_SCHEMA,
    handler=lambda args, **kw: grok_chat(
        prompt=args.get("prompt", ""),
        timeout=args.get("timeout", 90),
        bridge_url=args.get("bridge_url"),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_grok_bridge_requirements,
    description=GROK_CHAT_SCHEMA["description"],
    emoji="🧠",
)
registry.register(
    name="grok_health",
    toolset="grok",
    schema=GROK_HEALTH_SCHEMA,
    handler=lambda args, **kw: grok_health(
        bridge_url=args.get("bridge_url"),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_grok_bridge_requirements,
    description=GROK_HEALTH_SCHEMA["description"],
    emoji="💓",
)
registry.register(
    name="grok_new_conversation",
    toolset="grok",
    schema=GROK_NEW_SCHEMA,
    handler=lambda args, **kw: grok_new_conversation(
        bridge_url=args.get("bridge_url"),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_grok_bridge_requirements,
    description=GROK_NEW_SCHEMA["description"],
    emoji="🆕",
)
registry.register(
    name="grok_history",
    toolset="grok",
    schema=GROK_HISTORY_SCHEMA,
    handler=lambda args, **kw: grok_history(
        bridge_url=args.get("bridge_url"),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_grok_bridge_requirements,
    description=GROK_HISTORY_SCHEMA["description"],
    emoji="📜",
)
