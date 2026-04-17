import json

import tools.grok_bridge_tool as gbt


def test_grok_chat_returns_bridge_payload(monkeypatch):
    monkeypatch.setattr(gbt, "bridge_chat", lambda prompt, timeout=90, bridge_url=None: {"status": "ok", "response": prompt})

    result = json.loads(gbt.grok_chat("hello"))

    assert result["status"] == "ok"
    assert result["response"] == "hello"
    assert result["success"] is True


def test_grok_chat_requires_prompt():
    result = json.loads(gbt.grok_chat("   "))
    assert result["success"] is False


def test_grok_health_wraps_errors(monkeypatch):
    monkeypatch.setattr(gbt, "grok_bridge_health", lambda bridge_url=None: (_ for _ in ()).throw(gbt.GrokBridgeError("down")))

    result = json.loads(gbt.grok_health())

    assert result["success"] is False
    assert "down" in result["error"]
