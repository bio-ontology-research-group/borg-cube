#!/usr/bin/env python3
"""Serve a deterministic local mock administrative form on loopback.

The server accepts GET requests for ``/`` and ``/healthz``. POST is always
rejected with status 405, so the mock cannot submit anything.

Example:
  mock_form.py --port 8765
  mock_form.py --port 0 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORM_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Local mock administrative request</title>
</head>
<body>
  <main>
    <h1>Local mock administrative request</h1>
    <form id="admin-request" method="post" action="/submit">
      <label for="requester_name">Requester name</label>
      <input id="requester_name" name="requester_name" type="text" autocomplete="off">

      <label for="purpose">Purpose</label>
      <textarea id="purpose" name="purpose"></textarea>

      <label for="travel_date">Travel date</label>
      <input id="travel_date" name="travel_date" type="date">

      <label for="cost_center">Cost center</label>
      <select id="cost_center" name="cost_center">
        <option value="">Choose one</option>
        <option value="mock-001">Mock 001</option>
        <option value="mock-002">Mock 002</option>
      </select>

      <label for="policy_confirmed">Policy reviewed</label>
      <input id="policy_confirmed" name="policy_confirmed" type="checkbox">

      <fieldset>
        <legend>Needs follow-up</legend>
        <label for="follow_up_yes">Yes</label>
        <input id="follow_up_yes" name="follow_up" type="radio" value="yes">
        <label for="follow_up_no">No</label>
        <input id="follow_up_no" name="follow_up" type="radio" value="no">
      </fieldset>

      <button id="submit" type="submit">Submit mock request</button>
    </form>
    <p id="status">No submission attempted.</p>
  </main>
  <script>
    document.getElementById('admin-request').addEventListener('submit', function (event) {
      event.preventDefault();
      document.getElementById('status').textContent = 'Submission blocked by local mock.';
    });
  </script>
</body>
</html>
"""


class MockFormHandler(BaseHTTPRequestHandler):
    """Serve only the fixed local form and reject submission."""

    server_version = "BorgMockForm/1.0"

    def do_GET(self) -> None:  # noqa: N802, required by BaseHTTPRequestHandler
        if self.path == "/healthz":
            payload = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        elif self.path == "/":
            payload = FORM_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            payload = b"not found\n"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802, required by BaseHTTPRequestHandler
        payload = b"submission disabled\n"
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("mock form may bind only to the loopback hosts 127.0.0.1 or localhost")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return ThreadingHTTPServer((host, port), MockFormHandler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1", help="loopback host")
    parser.add_argument("--port", default=8765, type=int, help="loopback port; 0 chooses one")
    parser.add_argument("--once", action="store_true", help="serve one request, then exit")
    parser.add_argument("--json", action="store_true", help="print listening details as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        server = make_server(args.host, args.port)
    except (OSError, ValueError) as exc:
        print(f"mock-form: {exc}", file=sys.stderr)
        return 1
    host, port = server.server_address[:2]
    details = {"host": host, "port": port, "url": f"http://{host}:{port}/", "post": "disabled"}
    message = json.dumps(details) if args.json else f"mock-form: {details['url']} (POST disabled)"
    print(message, flush=True)
    try:
        if args.once:
            server.handle_request()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
