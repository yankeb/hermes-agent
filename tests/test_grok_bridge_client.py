import json
from pathlib import Path

import pytest

import grok_bridge_client as gbc


def test_resolve_bridge_url_prefers_explicit_over_env_and_config(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text("grok_bridge:\n  url: http://config:19998\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("GROK_BRIDGE_URL", "http://env:20001")

    assert gbc.resolve_grok_bridge_url("http://explicit:1234") == "http://explicit:1234"


def test_resolve_bridge_url_uses_env_before_config(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text("grok_bridge:\n  url: http://config:19998\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("GROK_BRIDGE_URL", "http://env:20001/")

    assert gbc.resolve_grok_bridge_url() == "http://env:20001"


def test_resolve_bridge_url_uses_config_when_env_missing(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text("grok_bridge:\n  url: http://config:19998/\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("GROK_BRIDGE_URL", raising=False)

    assert gbc.resolve_grok_bridge_url() == "http://config:19998"


def test_resolve_bridge_url_falls_back_to_default(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("GROK_BRIDGE_URL", raising=False)

    assert gbc.resolve_grok_bridge_url() == gbc.DEFAULT_GROK_BRIDGE_URL


def test_grok_command_message_for_grok_includes_tool_instruction():
    message = gbc.build_grok_command_message("grok", "Explain flash attention")

    assert "grok_chat" in message
    assert "Explain flash attention" in message
    assert "Return the Grok answer" in message


def test_grok_command_message_for_compare_requests_side_by_side():
    message = gbc.build_grok_command_message("compare", "Review this design")

    assert "First answer the user's prompt yourself" in message
    assert "Then call the grok_chat tool" in message
    assert "Review this design" in message


def test_bridge_request_raises_for_http_error(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            raise RuntimeError("boom")

        def json(self):
            return {}

    monkeypatch.setattr(gbc.requests, "request", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(gbc.GrokBridgeError):
        gbc.bridge_request("GET", "/health", bridge_url="http://127.0.0.1:9")


def test_bridge_chat_posts_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok", "response": "hi"}

    def fake_request(method, url, json=None, timeout=None):
        captured.update({"method": method, "url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(gbc.requests, "request", fake_request)
    result = gbc.bridge_chat("hello", timeout=42, bridge_url="http://bridge:20001")

    assert result["response"] == "hi"
    assert captured == {
        "method": "POST",
        "url": "http://bridge:20001/chat",
        "json": {"prompt": "hello", "timeout": 42},
        "timeout": 47,
    }
