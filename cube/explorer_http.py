"""Loopback-only explorer. SSH authenticates remote access; no public listener."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cube.explorer import Explorer

ASSETS = {
    "/": ("explorer.html", "text/html; charset=utf-8"),
    "/explorer.js": ("explorer.js", "text/javascript; charset=utf-8"),
}
AGENT_PATH = re.compile(r"/api/agents/([a-z][a-z0-9-]*)(/trigger)?\Z")
HOST = re.compile(r"(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?\Z")


class ExplorerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, explorer: Explorer, port: int = 8765) -> None:
        self.explorer = explorer
        self.csrf = secrets.token_urlsafe(32)
        self.cache: dict[tuple[int, str | None], tuple[float, dict[str, Any]]] = {}
        self.cache_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)

    def snapshot(self, days: int, name: str | None) -> dict[str, Any]:
        with self.cache_lock:
            key = (days, name)
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 10:
                return cached[1]
            result = self.explorer.snapshot(days, name)
            self.cache[key] = (time.monotonic(), result)
            return result


class Handler(BaseHTTPRequestHandler):
    server: ExplorerServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args: Any) -> None:
        # No query strings, instruction bodies or research content in access logs.
        pass

    def _respond(self, status: int, value: Any, mime: str = "application/json") -> None:
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _trusted(self, *, write: bool = False) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if not HOST.fullmatch(host) or (origin and origin != f"http://{host}"):
            self._respond(403, {"error": "Access through the localhost SSH tunnel."})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._respond(403, {"error": "Cross-site requests are refused."})
            return False
        if write and (
            origin != f"http://{host}"
            or not secrets.compare_digest(self.headers.get("X-Cube-CSRF", ""), self.server.csrf)
        ):
            self._respond(403, {"error": "Reload the explorer before requesting an action."})
            return False
        return True

    def do_GET(self) -> None:
        if not self._trusted():
            return
        parsed = urlsplit(self.path)
        if parsed.path in ASSETS:
            name, mime = ASSETS[parsed.path]
            self._respond(200, (Path(__file__).parent / "web" / name).read_bytes(), mime)
            return
        if parsed.path == "/healthz":
            self._respond(200, {"status": "ok", "host": self.server.explorer.settings.host})
            return
        if parsed.path == "/api/session":
            self._respond(200, {"csrf": self.server.csrf})
            return
        match = AGENT_PATH.fullmatch(parsed.path)
        if parsed.path != "/api/snapshot" and (not match or match.group(2)):
            self._respond(404, {"error": "Not found."})
            return
        try:
            days = int(parse_qs(parsed.query).get("days", ["7"])[0])
            self._respond(200, self.server.snapshot(days, match.group(1) if match else None))
        except ValueError as exc:
            self._respond(400, {"error": str(exc)})
        except (OSError, RuntimeError):
            self._respond(
                503,
                {"error": "Fleet data unavailable. Check the explorer service log and data paths."},
            )

    def do_POST(self) -> None:
        if not self._trusted(write=True):
            return
        match = AGENT_PATH.fullmatch(urlsplit(self.path).path)
        if not match or not match.group(2):
            self._respond(404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                length < 1
                or length > 16000
                or self.headers.get("Content-Type") != "application/json"
            ):
                raise ValueError("Send a bounded JSON instruction.")
            body = json.loads(self.rfile.read(length))
            if (
                not isinstance(body, dict)
                or body.get("confirm") is not True
                or set(body) - {"confirm", "message"}
            ):
                raise ValueError("Explicit confirmation is required.")
            message = body.get("message", "")
            if not isinstance(message, str):
                raise ValueError("Instruction must be text.")
            result = self.server.explorer.trigger(match.group(1), message)
            with self.server.cache_lock:
                self.server.cache.clear()
            self._respond(202, result)
        except (ValueError, OSError) as exc:
            self._respond(400, {"error": str(exc)})
