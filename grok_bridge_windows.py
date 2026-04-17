#!/usr/bin/env python3
"""WSL2/Windows Chromium bridge for Grok.

Runs from WSL/Linux, controls a Windows Chrome/Edge instance through the Chrome
DevTools Protocol using PowerShell as the Windows-side transport, and exposes a
small REST API compatible with the original grok-bridge shape.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Callable, Iterable, Sequence

GROK_URL = "https://grok.com/"
VERSION = "windows-v2"
DEFAULT_DEBUG_PORT = 9222
DEFAULT_PORT = 19998
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_STABLE_POLLS = 3
DEFAULT_BROWSER_TIMEOUT = 120
DEFAULT_CONNECT_TIMEOUT = 20
INPUT_SELECTORS = [
    "textarea",
    'div[contenteditable="true"]',
    '[data-testid="text-input"]',
    '[role="textbox"]',
]
SEND_SELECTORS = [
    'button[aria-label="Send"]',
    'button[data-testid="send-button"]',
]
BROWSER_CANDIDATES = (
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
)
UI_MARKERS = (
    "\nAsk anything",
    "\nDeepSearch",
    "\nThink Harder",
    "\nThink\n",
    "\nAttach",
    "\nGrok",
    "\nFast\n",
    "\nAuto\n",
    "\nUpgrade to",
)


class BridgeError(RuntimeError):
    """Raised when the Grok bridge cannot complete a browser action."""


@dataclass(slots=True)
class BridgeConfig:
    debug_port: int = DEFAULT_DEBUG_PORT
    server_port: int = DEFAULT_PORT
    startup_url: str = GROK_URL
    browser_timeout: int = DEFAULT_BROWSER_TIMEOUT
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    poll_interval: float = DEFAULT_POLL_INTERVAL
    stable_polls: int = DEFAULT_STABLE_POLLS
    browser_path: str | None = None
    profile_dir: Path | None = None
    launch_browser: bool = True


@dataclass(slots=True)
class CDPTarget:
    id: str
    url: str
    websocket_url: str
    title: str = ""


def detect_windows_browser_path(
    candidates: Sequence[str] = BROWSER_CANDIDATES,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> str | None:
    for candidate in candidates:
        if path_exists(candidate):
            return candidate
    return None


def build_browser_command(
    browser_path: str,
    debug_port: int,
    profile_dir: Path | None,
    startup_url: str = GROK_URL,
) -> list[str]:
    command = [
        browser_path,
        f"--remote-debugging-port={debug_port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-features=Translate,OptimizationHints",
    ]
    if profile_dir is not None:
        command.append(f"--user-data-dir={profile_dir}")
    command.append(startup_url)
    return command


def choose_grok_target(targets: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    page_targets = [target for target in targets if target.get("type") == "page"]
    if not page_targets:
        return None

    def score(target: dict[str, Any]) -> tuple[int, int, int]:
        url = str(target.get("url") or "")
        exact = 0 if url.startswith("https://grok.com") or url.startswith("http://grok.com") else 1
        chat = 0 if "grok.com" in url and ("/chat" in url or url.rstrip("/") == "https://grok.com") else 1
        empty = 0 if url else 1
        return (exact, chat, empty)

    return sorted(page_targets, key=score)[0]


def clean_response_text(text: str) -> str:
    cleaned = text
    for marker in UI_MARKERS:
        idx = cleaned.rfind(marker)
        if idx > 0:
            cleaned = cleaned[:idx]
    cleaned = re.sub(r"\n[0-9]+(?:\.[0-9]+)?s\n", "\n", cleaned)
    cleaned = re.sub(r"\n(Share|Compare|Make it.*|Explain.*|Toggle.*|Like|Dislike).*", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_response_from_body(body: str, prompt: str) -> str:
    marker = prompt[:60]
    parts = body.split(marker)
    tail = parts[-1] if len(parts) >= 2 else body
    return clean_response_text(tail)


def _js_string_literal(value: str) -> str:
    return json.dumps(value)


def build_send_prompt_expression(prompt: str) -> str:
    prompt_js = _js_string_literal(prompt.replace("\r", ""))
    selectors_js = json.dumps(INPUT_SELECTORS)
    send_selectors_js = json.dumps(SEND_SELECTORS)
    return f"""
(() => {{
  const inputSelectors = {selectors_js};
  const sendSelectors = {send_selectors_js};
  const prompt = {prompt_js};
  const input = inputSelectors
    .map((selector) => document.querySelector(selector))
    .find(Boolean);
  if (!input) return {{ ok: false, error: 'input not found' }};

  input.focus();
  if (input.tagName === 'TEXTAREA') {{
    input.value = '';
  }} else {{
    input.textContent = '';
  }}

  const inserted = document.execCommand('insertText', false, prompt);
  if (!inserted && input.tagName === 'TEXTAREA') {{
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  }}

  for (const selector of sendSelectors) {{
    const button = document.querySelector(selector);
    if (button && !button.disabled) {{
      button.click();
      return {{ ok: true, action: 'clicked', selector }};
    }}
  }}

  const fallback = [...document.querySelectorAll('button')].find((button) =>
    /send|submit|ask|go/i.test(button.textContent || button.ariaLabel || '') && !button.disabled
  );
  if (fallback) {{
    fallback.click();
    return {{ ok: true, action: 'fallback_click' }};
  }}

  input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }}));
  return {{ ok: true, action: 'enter' }};
}})()
""".strip()


def _build_find_input_expression() -> str:
    selectors_js = json.dumps(INPUT_SELECTORS)
    return f"""
(() => {{
  const selectors = {selectors_js};
  const selector = selectors.find((candidate) => document.querySelector(candidate));
  return selector ? {{ ok: true, selector }} : {{ ok: false }};
}})()
""".strip()


def _build_get_body_expression() -> str:
    return "document.body ? document.body.innerText : ''"


def _build_navigate_expression(url: str) -> str:
    url_js = _js_string_literal(url)
    return f"window.location.href = {url_js}; true;"


def _build_title_expression() -> str:
    return "({ title: document.title || '', url: window.location.href || '' })"


def _wsl_to_windows_path(path: Path) -> str:
    raw = str(path)
    if not raw.startswith("/mnt/"):
        return raw
    try:
        output = subprocess.run(
            ["wslpath", "-w", raw],
            check=True,
            capture_output=True,
            text=True,
        )
        converted = output.stdout.strip()
        return converted or raw
    except Exception:
        return raw


def _ps_quote(text: str) -> str:
    return text.replace("'", "''")


def build_powershell_command(script: str) -> list[str]:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def run_powershell(script: str) -> str:
    temp_dir = Path("/mnt/c/Windows/Temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ps1", dir=temp_dir, delete=False) as handle:
        handle.write(script)
        temp_path = Path(handle.name)
    windows_temp_path = _wsl_to_windows_path(temp_path)
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_temp_path,
            ],
            capture_output=True,
            text=True,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"PowerShell exited with {result.returncode}"
        raise BridgeError(detail)
    return result.stdout.strip()


def run_powershell_json(script: str) -> Any:
    raw = run_powershell(script)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Expected JSON from PowerShell, got: {raw[:500]}") from exc


def build_windows_http_script(url: str, method: str = "GET", timeout: int = 5) -> str:
    return f"""
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$uri = '{_ps_quote(url)}'
$method = '{_ps_quote(method)}'
try {{
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $uri -Method $method -TimeoutSec {int(timeout)}
    Write-Output $resp.Content
}} catch {{
    Write-Error $_.Exception.Message
    exit 1
}}
""".strip()


def build_windows_cdp_eval_script(websocket_url: str, payload_json: str, timeout: int = 20) -> str:
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    return f"""
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Net.Http
$uri = [Uri]::new('{_ps_quote(websocket_url)}')
$payload = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{payload_b64}'))
$timeoutMs = {int(timeout * 1000)}
$cts = [System.Threading.CancellationTokenSource]::new()
$cts.CancelAfter($timeoutMs)
$ws = [System.Net.WebSockets.ClientWebSocket]::new()
try {{
    [void]$ws.ConnectAsync($uri, $cts.Token).GetAwaiter().GetResult()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $segment = [System.ArraySegment[byte]]::new($bytes)
    [void]$ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).GetAwaiter().GetResult()
    while ($true) {{
        $buffer = New-Object byte[] 65536
        $builder = [System.Text.StringBuilder]::new()
        do {{
            $recv = $ws.ReceiveAsync([System.ArraySegment[byte]]::new($buffer), $cts.Token).GetAwaiter().GetResult()
            if ($recv.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {{ break }}
            [void]$builder.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $recv.Count))
        }} while (-not $recv.EndOfMessage)
        if ($builder.Length -eq 0) {{ continue }}
        $text = $builder.ToString()
        if (-not $text) {{ continue }}
        if ($text -match '"id"\s*:\s*1') {{
            Write-Output $text
            break
        }}
    }}
}} catch {{
    Write-Error $_.Exception.Message
    exit 1
}} finally {{
    try {{
        if ($ws.State -eq [System.Net.WebSockets.WebSocketState]::Open) {{
            [void]$ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
        }}
    }} catch {{}}
    $ws.Dispose()
    $cts.Dispose()
}}
""".strip()


class CDPBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.browser_path = config.browser_path or detect_windows_browser_path()

    def health(self) -> dict[str, Any]:
        try:
            target = self._ensure_grok_target()
            meta = self._eval(target.websocket_url, _build_title_expression())
            return {
                "status": "ok",
                "version": VERSION,
                "browser_path": self.browser_path,
                "url": meta.get("url", target.url),
                "title": meta.get("title", ""),
                "on_grok": "grok.com" in (meta.get("url") or target.url),
                "debug_port": self.config.debug_port,
            }
        except Exception as exc:
            return {
                "status": "error",
                "version": VERSION,
                "browser_path": self.browser_path,
                "error": str(exc),
                "debug_port": self.config.debug_port,
            }

    def history(self) -> dict[str, Any]:
        target = self._ensure_grok_target()
        body = self._get_body(target.websocket_url)
        return {
            "status": "ok",
            "content": clean_response_text(body),
            "raw_length": len(body),
        }

    def new_conversation(self) -> dict[str, Any]:
        target = self._ensure_grok_target()
        self._eval(target.websocket_url, _build_navigate_expression(self.config.startup_url))
        self._wait_for_input(target.websocket_url, timeout=30)
        return {"status": "ok", "url": self.config.startup_url}

    def chat(self, prompt: str, timeout: int = DEFAULT_BROWSER_TIMEOUT) -> dict[str, Any]:
        target = self._ensure_grok_target()
        self._wait_for_input(target.websocket_url, timeout=min(timeout, 30))
        body_before = self._get_body(target.websocket_url)
        send_result = self._eval(target.websocket_url, build_send_prompt_expression(prompt))
        if not send_result.get("ok"):
            return {"status": "error", "error": send_result.get("error", "send failed")}

        started = time.time()
        stable = 0
        last_body = body_before
        while time.time() - started < timeout:
            time.sleep(self.config.poll_interval)
            body = self._get_body(target.websocket_url)
            if body != body_before and body == last_body:
                stable += 1
                if stable >= self.config.stable_polls:
                    return {
                        "status": "ok",
                        "response": extract_response_from_body(body, prompt),
                        "elapsed": round(time.time() - started, 1),
                        "meta": send_result,
                    }
            else:
                stable = 0
            last_body = body

        return {
            "status": "timeout",
            "response": extract_response_from_body(last_body, prompt),
            "elapsed": round(time.time() - started, 1),
            "meta": send_result,
        }

    def _ensure_debug_endpoint(self) -> None:
        try:
            self._json_get("/json/version")
            return
        except Exception:
            pass

        if not self.config.launch_browser:
            raise BridgeError(
                f"Chrome DevTools not reachable on port {self.config.debug_port}; launch a browser with remote debugging enabled"
            )
        if not self.browser_path:
            raise BridgeError("No Windows Chrome/Edge executable found under /mnt/c/Program Files")

        profile_dir = (
            Path(_wsl_to_windows_path(self.config.profile_dir))
            if self.config.profile_dir is not None
            else None
        )
        command = build_browser_command(
            browser_path=self.browser_path,
            debug_port=self.config.debug_port,
            profile_dir=profile_dir,
            startup_url=self.config.startup_url,
        )
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deadline = time.time() + self.config.connect_timeout
        last_error = None
        while time.time() < deadline:
            try:
                self._json_get("/json/version")
                return
            except Exception as exc:  # pragma: no cover - timing dependent
                last_error = exc
                time.sleep(1)
        raise BridgeError(f"Timed out waiting for browser debug endpoint: {last_error}")

    def _ensure_grok_target(self) -> CDPTarget:
        self._ensure_debug_endpoint()
        targets = self._json_get("/json/list")
        target = choose_grok_target(targets)
        if not target:
            self._open_new_tab(self.config.startup_url)
            targets = self._json_get("/json/list")
            target = choose_grok_target(targets)
        if not target:
            raise BridgeError("Could not find or create a Chrome page target for grok.com")

        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise BridgeError("Selected Chrome target is missing webSocketDebuggerUrl")

        cdp_target = CDPTarget(
            id=str(target.get("id")),
            url=str(target.get("url") or ""),
            title=str(target.get("title") or ""),
            websocket_url=str(websocket_url),
        )

        if "grok.com" not in cdp_target.url:
            self._eval(cdp_target.websocket_url, _build_navigate_expression(self.config.startup_url))
            self._wait_for_input(cdp_target.websocket_url, timeout=30)

        return cdp_target

    def _wait_for_input(self, websocket_url: str, timeout: int) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self._eval(websocket_url, _build_find_input_expression())
            if result.get("ok"):
                return str(result.get("selector"))
            time.sleep(0.5)
        raise BridgeError("Timed out waiting for Grok input box")

    def _get_body(self, websocket_url: str) -> str:
        result = self._eval(websocket_url, _build_get_body_expression())
        return str(result or "")

    def _json_get(self, path: str) -> Any:
        url = f"http://127.0.0.1:{self.config.debug_port}{path}"
        script = build_windows_http_script(url=url, method="GET", timeout=5)
        return run_powershell_json(script)

    def _open_new_tab(self, url: str) -> Any:
        encoded_url = urllib_parse_quote(url)
        script = build_windows_http_script(
            url=f"http://127.0.0.1:{self.config.debug_port}/json/new?{encoded_url}",
            method="PUT",
            timeout=5,
        )
        return run_powershell_json(script)

    def _eval(self, websocket_url: str, expression: str) -> Any:
        request = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }
        script = build_windows_cdp_eval_script(
            websocket_url=websocket_url,
            payload_json=json.dumps(request),
            timeout=self.config.connect_timeout,
        )
        message = run_powershell_json(script)
        if "error" in message:
            raise BridgeError(f"CDP error: {message['error']}")
        result = message.get("result", {})
        if "exceptionDetails" in result:
            raise BridgeError(f"JavaScript evaluation failed: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")


class _BridgeHandler(BaseHTTPRequestHandler):
    bridge: CDPBridge | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, self.bridge.health())
            return
        if self.path == "/history":
            try:
                self._json(200, self.bridge.history())
            except Exception as exc:
                self._json(500, {"status": "error", "error": str(exc)})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        data = json.loads(body or b"{}")

        if self.path == "/chat":
            prompt = data.get("prompt", "")
            timeout = int(data.get("timeout", DEFAULT_BROWSER_TIMEOUT))
            try:
                self._json(200, self.bridge.chat(prompt, timeout=timeout))
            except Exception as exc:
                self._json(500, {"status": "error", "error": str(exc)})
            return

        if self.path == "/new":
            try:
                self._json(200, self.bridge.new_conversation())
            except Exception as exc:
                self._json(500, {"status": "error", "error": str(exc)})
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        return

    def _json(self, status: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def urllib_parse_quote(url: str) -> str:
    from urllib.parse import quote

    return quote(url, safe="")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WSL2/Windows Chrome Grok bridge")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP server port")
    parser.add_argument("--debug-port", type=int, default=DEFAULT_DEBUG_PORT, help="Chrome DevTools port")
    parser.add_argument("--browser-path", help="Windows Chrome/Edge executable path")
    parser.add_argument(
        "--profile-dir",
        help="Optional dedicated browser profile directory. Omit to reuse your existing signed-in browser session.",
    )
    parser.add_argument("--startup-url", default=GROK_URL, help="Initial URL to open in the browser")
    parser.add_argument("--browser-timeout", type=int, default=DEFAULT_BROWSER_TIMEOUT)
    parser.add_argument("--connect-timeout", type=int, default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--stable-polls", type=int, default=DEFAULT_STABLE_POLLS)
    parser.add_argument(
        "--connect-only",
        action="store_true",
        help="Do not launch Chrome/Edge automatically; only connect to an existing debug port",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = BridgeConfig(
        debug_port=args.debug_port,
        server_port=args.port,
        startup_url=args.startup_url,
        browser_timeout=args.browser_timeout,
        connect_timeout=args.connect_timeout,
        poll_interval=args.poll_interval,
        stable_polls=args.stable_polls,
        browser_path=args.browser_path,
        profile_dir=Path(args.profile_dir).expanduser() if args.profile_dir else None,
        launch_browser=not args.connect_only,
    )
    bridge = CDPBridge(config)
    _BridgeHandler.bridge = bridge
    server = ThreadedHTTPServer(("0.0.0.0", args.port), _BridgeHandler)
    print(f"Grok Bridge {VERSION} listening on :{args.port}", flush=True)
    print(f"Chrome DevTools port: {args.debug_port}", flush=True)
    if bridge.browser_path:
        print(f"Browser: {bridge.browser_path}", flush=True)
    else:
        print("Browser: auto-detect failed (use --browser-path or --connect-only)", flush=True)
    print("Endpoints: POST /chat, POST /new, GET /health, GET /history", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
