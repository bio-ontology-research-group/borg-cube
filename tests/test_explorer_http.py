from __future__ import annotations

import http.client
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cube.explorer_http import ExplorerServer


@pytest.fixture
def server():
    explorer = SimpleNamespace(
        settings=SimpleNamespace(host="ws"),
        snapshot=Mock(return_value={"agents": []}),
        trigger=Mock(return_value={"status": "queued"}),
    )
    service = ExplorerServer(explorer, port=0)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = (response.status, dict(response.getheaders()), response.read())
    connection.close()
    return result


def post_headers(server):
    return {
        "Content-Type": "application/json",
        "X-Cube-CSRF": server.csrf,
        "Origin": f"http://127.0.0.1:{server.server_port}",
    }


def test_loopback_session_and_snapshot(server):
    assert server.server_address[0] == "127.0.0.1"
    status, headers, body = request(server, "GET", "/api/session")
    assert status == 200
    assert json.loads(body)["csrf"] == server.csrf
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Frame-Options"] == "DENY"
    assert request(server, "GET", "/api/snapshot?days=7")[0] == 200
    server.explorer.snapshot.assert_called_once_with(7, None)


@pytest.mark.parametrize(
    "headers",
    [{"Host": "evil.example"}, {"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}],
)
def test_cross_site_reads_denied(server, headers):
    assert request(server, "GET", "/api/session", headers=headers)[0] == 403


@pytest.mark.parametrize(
    "path",
    ["/../cube.yaml", "/%2e%2e/cube.yaml", "/api/agents/../alpha", "/api/agents/alpha/trigger"],
)
def test_no_asset_or_api_traversal(server, path):
    assert request(server, "GET", path)[0] == 404


def test_post_requires_origin_and_csrf(server):
    body = json.dumps({"confirm": True})
    assert request(server, "POST", "/api/agents/alpha/trigger", body)[0] == 403
    headers = post_headers(server)
    headers["X-Cube-CSRF"] = "wrong"
    assert request(server, "POST", "/api/agents/alpha/trigger", body, headers)[0] == 403
    server.explorer.trigger.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [{}, {"confirm": False}, {"confirm": True, "command": "sh"}, {"confirm": True, "message": 1}],
)
def test_explicit_bounded_confirmation(server, body):
    assert (
        request(
            server, "POST", "/api/agents/alpha/trigger", json.dumps(body), post_headers(server)
        )[0]
        == 400
    )
    server.explorer.trigger.assert_not_called()


def test_confirmed_post_and_cache_invalidation(server):
    server.cache[(7, None)] = (0, {})
    status, _, body = request(
        server,
        "POST",
        "/api/agents/alpha/trigger",
        json.dumps({"confirm": True, "message": "Check results"}),
        post_headers(server),
    )
    assert status == 202
    assert json.loads(body)["status"] == "queued"
    assert server.cache == {}
    server.explorer.trigger.assert_called_once_with("alpha", "Check results")
