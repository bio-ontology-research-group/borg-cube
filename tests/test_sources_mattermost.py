import json

from cube.sources.mattermost import parse_event, permalink_for


def test_permalink() -> None:
    assert permalink_for("abc") == "https://borg.bio2vec.net/borg/pl/abc"


def test_outgoing_webhook_payload() -> None:
    ev = parse_event(
        {
            "token": "x",
            "team_id": "t",
            "team_domain": "borg",
            "channel_id": "c1",
            "channel_name": "town-square",
            "timestamp": 1756800000000,
            "user_id": "u1",
            "user_name": "finfellow",
            "post_id": "p123",
            "text": "hello @borg-advisor",
        }
    )
    assert ev is not None
    assert ev.post_id == "p123" and ev.user == "finfellow" and ev.channel == "town-square"
    assert ev.channel_id == "c1" and ev.text == "hello @borg-advisor"
    assert ev.permalink == "https://borg.bio2vec.net/borg/pl/p123"
    assert ev.created is not None and ev.created.year == 2025
    assert ev.raw_kind == "webhook"
    assert ev.as_dict()["permalink"].endswith("/pl/p123")


def test_websocket_posted_event() -> None:
    post = {
        "id": "p9",
        "user_id": "u2",
        "channel_id": "c2",
        "message": "ping",
        "create_at": 1756800000000,
        "root_id": "r1",
    }
    ev = parse_event(
        {
            "event": "posted",
            "data": {"post": json.dumps(post), "sender_name": "@bea", "channel_name": "agents"},
        }
    )
    assert ev is not None
    assert ev.post_id == "p9" and ev.user == "@bea" and ev.channel == "agents"
    assert ev.root_id == "r1" and ev.raw_kind == "websocket"


def test_gateway_shape_and_missing_id() -> None:
    ev = parse_event(
        {"post": {"id": "p1", "message": "m", "channel_id": "c"}, "user": "alex"},
        base_url="https://mm.example/",
        team="other",
    )
    assert (
        ev is not None and ev.permalink == "https://mm.example/other/pl/p1" and ev.user == "alex"
    )
    assert ev.raw_kind == "gateway"
    assert parse_event({"text": "no id"}) is None
