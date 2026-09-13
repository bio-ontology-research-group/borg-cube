"""Mattermost event intake: normalise a gateway or webhook payload into one event.

No polling lives here (pa rule: never poll Mattermost on a schedule). Events arrive from the
Hermes gateway or an outgoing webhook and are handed to ``parse_event``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_BASE_URL = "https://borg.bio2vec.net"
DEFAULT_TEAM = "borg"


@dataclass(frozen=True)
class MattermostEvent:
    post_id: str
    user: str | None
    user_id: str | None
    channel: str | None
    channel_id: str | None
    text: str
    permalink: str
    team: str
    created: datetime | None = None
    root_id: str | None = None
    raw_kind: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created"] = self.created.isoformat() if self.created else None
        return d


def permalink_for(post_id: str, base_url: str = DEFAULT_BASE_URL, team: str = DEFAULT_TEAM) -> str:
    return f"{base_url.rstrip('/')}/{team}/pl/{post_id}"


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if num > 1e12:  # Mattermost create_at is milliseconds
        num /= 1000.0
    return datetime.fromtimestamp(num, tz=UTC)


def parse_event(
    payload: dict[str, Any],
    *,
    base_url: str = DEFAULT_BASE_URL,
    team: str = DEFAULT_TEAM,
) -> MattermostEvent | None:
    """Accept an outgoing-webhook body, a websocket ``posted`` event or a Hermes gateway
    message and return a normalised event; None when no post id can be found."""
    kind = "webhook"
    post: dict[str, Any] = {}
    data = payload
    if isinstance(payload.get("data"), dict):  # websocket event {event: posted, data: {post: json}}
        data = payload["data"]
        kind = "websocket"
        raw_post = data.get("post")
        if isinstance(raw_post, str):
            import json

            try:
                post = json.loads(raw_post)
            except json.JSONDecodeError:
                post = {}
        elif isinstance(raw_post, dict):
            post = raw_post
    elif isinstance(payload.get("post"), dict):
        post = payload["post"]
        kind = "gateway"
    post_id = _first(post, "id") or _first(payload, "post_id", "postId", "id", "message_id")
    if not post_id:
        return None
    text = str(_first(post, "message") or _first(payload, "text", "message", "content") or "")
    team_name = str(_first(payload, "team_domain", "team_name", "team") or team)
    return MattermostEvent(
        post_id=str(post_id),
        user=_first(payload, "user_name", "username", "sender_name", "user")
        or _first(data, "sender_name"),
        user_id=_first(post, "user_id") or _first(payload, "user_id"),
        channel=_first(payload, "channel_name", "channel") or _first(data, "channel_name"),
        channel_id=_first(post, "channel_id") or _first(payload, "channel_id"),
        text=text,
        permalink=permalink_for(str(post_id), base_url, team_name),
        team=team_name,
        created=_ts(_first(post, "create_at") or _first(payload, "timestamp", "create_at")),
        root_id=_first(post, "root_id") or _first(payload, "root_id"),
        raw_kind=kind,
    )
