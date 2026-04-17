"""Tests for the WSL2/Windows Chromium Grok bridge."""

from pathlib import Path

import grok_bridge_windows as gbw


def test_detect_windows_browser_path_prefers_chrome():
    def fake_exists(path: str) -> bool:
        return path in {
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
            "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        }

    assert gbw.detect_windows_browser_path(path_exists=fake_exists) == (
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
    )


def test_detect_windows_browser_path_falls_back_to_edge():
    def fake_exists(path: str) -> bool:
        return path == "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

    assert gbw.detect_windows_browser_path(path_exists=fake_exists) == (
        "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    )


def test_detect_windows_browser_path_returns_none_when_missing():
    assert gbw.detect_windows_browser_path(path_exists=lambda _path: False) is None


def test_build_browser_command_sets_remote_debugging_and_profile():
    command = gbw.build_browser_command(
        browser_path="/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        debug_port=9222,
        profile_dir=Path("/mnt/c/Users/ianka/AppData/Local/HermesGrokBridge"),
        startup_url="https://grok.com",
    )

    assert command[0] == "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
    assert "--remote-debugging-port=9222" in command
    assert "--no-first-run" in command
    assert any(arg.startswith("--user-data-dir=") for arg in command)
    assert command[-1] == "https://grok.com"


def test_choose_grok_target_prefers_exact_grok_tab():
    targets = [
        {"id": "other", "type": "page", "url": "https://example.com"},
        {"id": "chat", "type": "page", "url": "https://grok.com/chat/123"},
        {"id": "home", "type": "page", "url": "https://grok.com/"},
    ]

    chosen = gbw.choose_grok_target(targets)

    assert chosen["id"] == "chat"


def test_choose_grok_target_returns_none_without_page_targets():
    assert gbw.choose_grok_target([{"id": "worker", "type": "service_worker"}]) is None


def test_clean_response_text_removes_grok_ui_artifacts():
    body = "Answer line\n\nShare\nCompare\nMake it better\n\nAsk anything"

    assert gbw.clean_response_text(body) == "Answer line"


def test_extract_response_from_body_uses_prompt_marker_and_cleanup():
    body = "Prompt text\nThe answer\n\nThink Harder\nShare\nCompare"

    assert gbw.extract_response_from_body(body, "Prompt text") == "The answer"


def test_build_send_prompt_expression_escapes_prompt_content():
    expression = gbw.build_send_prompt_expression("Say 'hi'\nnext line")

    assert "insertText" in expression
    assert 'const prompt = ' in expression
    assert '"Say \'hi\'\\nnext line"'.replace("\\'", "'") in expression
    assert "button.click()" in expression
