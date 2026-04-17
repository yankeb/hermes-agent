#!/usr/bin/env python3
"""MCP server exposing the local Grok bridge as MCP tools."""

from __future__ import annotations

import asyncio
import json

from grok_bridge_client import bridge_chat, bridge_history, bridge_new_conversation, grok_bridge_health

_MCP_SERVER_AVAILABLE = False
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_SERVER_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment]


def create_mcp_server() -> "FastMCP":
    if not _MCP_SERVER_AVAILABLE:
        raise ImportError("Grok MCP server requires the 'mcp' package. Install with: pip install 'hermes-agent[mcp]'")

    mcp = FastMCP(
        "grok-bridge",
        instructions=(
            "Access the user's local Grok browser bridge. Use these tools to query a logged-in Grok session, "
            "check bridge health, inspect visible history, or start a fresh conversation."
        ),
    )

    @mcp.tool()
    def chat(prompt: str, timeout: int = 90, bridge_url: str | None = None) -> str:
        """Send a prompt to the local Grok bridge and return the JSON result."""
        return json.dumps(bridge_chat(prompt, timeout=timeout, bridge_url=bridge_url), ensure_ascii=False)

    @mcp.tool()
    def health(bridge_url: str | None = None) -> str:
        """Check the local Grok bridge health/status."""
        return json.dumps(grok_bridge_health(bridge_url=bridge_url), ensure_ascii=False)

    @mcp.tool()
    def history(bridge_url: str | None = None) -> str:
        """Read visible conversation text from the current Grok session."""
        return json.dumps(bridge_history(bridge_url=bridge_url), ensure_ascii=False)

    @mcp.tool()
    def new_conversation(bridge_url: str | None = None) -> str:
        """Start a fresh Grok conversation via the local bridge."""
        return json.dumps(bridge_new_conversation(bridge_url=bridge_url), ensure_ascii=False)

    return mcp


def run_mcp_server() -> None:
    server = create_mcp_server()

    async def _run() -> None:
        await server.run_stdio_async()

    asyncio.run(_run())


if __name__ == "__main__":
    run_mcp_server()
