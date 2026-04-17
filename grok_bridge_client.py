#!/usr/bin/env python3
"""Shared Grok bridge client helpers for tools, slash commands, and MCP wrappers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
import yaml

from hermes_constants import get_hermes_home

DEFAULT_GROK_BRIDGE_URL = "http://127.0.0.1:19998"
DEFAULT_GROK_TIMEOUT = 90


class GrokBridgeError(RuntimeError):
    """Raised when the Grok bridge is unavailable or returns invalid data."""


def _load_grok_bridge_config() -> dict[str, Any]:
    config_path = get_hermes_home() / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:
        return {}
    section = data.get("grok_bridge")
    return section if isinstance(section, dict) else {}


def resolve_grok_bridge_url(explicit_url: str | None = None) -> str:
    if explicit_url and explicit_url.strip():
        return explicit_url.strip().rstrip("/")

    env_url = os.getenv("GROK_BRIDGE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")

    cfg_url = str(_load_grok_bridge_config().get("url") or "").strip()
    if cfg_url:
        return cfg_url.rstrip("/")

    return DEFAULT_GROK_BRIDGE_URL


def grok_bridge_health(bridge_url: str | None = None) -> dict[str, Any]:
    return bridge_request("GET", "/health", bridge_url=bridge_url, timeout=5)


def grok_bridge_is_available(bridge_url: str | None = None) -> bool:
    try:
        result = grok_bridge_health(bridge_url=bridge_url)
        return result.get("status") == "ok"
    except Exception:
        return False


def bridge_request(
    method: str,
    path: str,
    *,
    bridge_url: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    url = f"{resolve_grok_bridge_url(bridge_url)}{path}"
    try:
        response = requests.request(method.upper(), url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise GrokBridgeError(f"Grok bridge request failed ({method.upper()} {url}): {exc}") from exc
    if not isinstance(data, dict):
        raise GrokBridgeError(f"Grok bridge returned non-object JSON from {url}")
    return data


def bridge_chat(
    prompt: str,
    *,
    timeout: int = DEFAULT_GROK_TIMEOUT,
    bridge_url: str | None = None,
) -> dict[str, Any]:
    return bridge_request(
        "POST",
        "/chat",
        bridge_url=bridge_url,
        payload={"prompt": prompt, "timeout": timeout},
        timeout=timeout + 5,
    )


def bridge_history(*, bridge_url: str | None = None) -> dict[str, Any]:
    return bridge_request("GET", "/history", bridge_url=bridge_url, timeout=10)


def bridge_new_conversation(*, bridge_url: str | None = None) -> dict[str, Any]:
    return bridge_request("POST", "/new", bridge_url=bridge_url, payload={}, timeout=15)


def build_grok_command_message(command_name: str, user_instruction: str) -> str:
    instruction = user_instruction.strip()
    if command_name == "grok":
        return (
            "Use the grok_chat tool to answer the user's request below. "
            "Return the Grok answer directly with minimal framing unless a brief note is required.\n\n"
            f"User request: {instruction}"
        )
    if command_name == "compare":
        return (
            "First answer the user's prompt yourself in a concise but complete way without calling grok_chat yet. "
            "Then call the grok_chat tool with the same prompt. "
            "Finally present three sections: Current model, Grok, Differences.\n\n"
            f"User request: {instruction}"
        )
    raise ValueError(f"Unsupported Grok slash command: {command_name}")
