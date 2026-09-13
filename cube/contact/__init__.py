"""Outbound-contact policy: default deny, explicit per-person grants in contacts.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

VALID_CHANNELS = {
    "mattermost_dm",
    "mattermost_channel",
    "email",
    "github",
    "portal",
    "dossier_read",
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    grant: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "grant": self.grant}


class ContactPolicy:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = {"grants": {}}
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict) or not isinstance(loaded.get("grants", {}), dict):
                raise ValueError(f"{path}: expected a mapping with a 'grants' mapping")
            self._data = {"grants": loaded.get("grants") or {}}

    @property
    def grants(self) -> dict[str, dict[str, Any]]:
        return dict(self._data["grants"])

    def check(self, person: str, channel: str, action: str, today: date | None = None) -> Decision:
        today = today or date.today()
        if channel not in VALID_CHANNELS:
            return Decision(False, f"unknown channel {channel!r}")
        person_grants = self._data["grants"].get(person)
        if not person_grants:
            return Decision(False, f"no grants for {person}; default is deny, route to Robert")
        grant = person_grants.get(channel)
        if not grant:
            return Decision(False, f"{person} has no grant for channel {channel}")
        expires = grant.get("expires")
        if expires and _to_date(expires) < today:
            return Decision(False, f"grant for {person}/{channel} expired on {expires}", grant)
        scope = grant.get("scope") or []
        if scope and action not in scope and "*" not in scope:
            return Decision(
                False, f"action {action!r} not in scope {scope} for {person}/{channel}", grant
            )
        return Decision(
            True, f"granted on {grant.get('granted')} by {grant.get('by', 'robert')}", grant
        )

    def grant(
        self,
        person: str,
        channel: str,
        scope: list[str],
        *,
        by: str = "robert",
        expires: date | None = None,
        evidence: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        if channel not in VALID_CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; valid: {sorted(VALID_CHANNELS)}")
        today = today or date.today()
        entry: dict[str, Any] = {"granted": today.isoformat(), "by": by, "scope": list(scope)}
        if expires:
            entry["expires"] = expires.isoformat()
        if evidence:
            entry["evidence"] = evidence
        self._data["grants"].setdefault(person, {})[channel] = entry
        return entry

    def revoke(self, person: str, channel: str | None = None) -> bool:
        grants = self._data["grants"]
        if person not in grants:
            return False
        if channel is None:
            del grants[person]
            return True
        removed = grants[person].pop(channel, None) is not None
        if not grants[person]:
            del grants[person]
        return removed

    def allowed_users(self, channel: str = "mattermost_dm", today: date | None = None) -> list[str]:
        """People with a live grant on a channel (feeds MATTERMOST_ALLOWED_USERS)."""
        today = today or date.today()
        out: list[str] = []
        for person, channels in self._data["grants"].items():
            grant = channels.get(channel)
            if not grant:
                continue
            expires = grant.get("expires")
            if expires and _to_date(expires) < today:
                continue
            out.append(person)
        return sorted(out)

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        header = (
            "# Outbound-contact grants. EMPTY BY DEFAULT: borg-cube contacts nobody but Robert.\n"
            "# Edit only via `cube contact grant/revoke`; every entry needs granted, by, scope.\n"
        )
        target.write_text(header + yaml.safe_dump(self._data, sort_keys=True), encoding="utf-8")


def _to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
