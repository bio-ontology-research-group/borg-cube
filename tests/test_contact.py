from datetime import date
from pathlib import Path

import pytest

from cube.contact import ContactPolicy


def test_default_deny(tmp_path: Path) -> None:
    p = ContactPolicy(tmp_path / "contacts.yaml")
    d = p.check("alex-example", "mattermost_dm", "weekly-checkin")
    assert not d.allowed and "default is deny" in d.reason


def test_grant_scope_expiry_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "contacts.yaml"
    p = ContactPolicy(path)
    p.grant(
        "alex-example",
        "mattermost_dm",
        ["weekly-checkin"],
        expires=date(2026, 12, 31),
        today=date(2026, 9, 2),
    )
    p.save()
    q = ContactPolicy(path)
    today = date(2026, 10, 1)
    assert q.check("alex-example", "mattermost_dm", "weekly-checkin", today=today).allowed
    assert not q.check(
        "alex-example", "mattermost_dm", "milestone-reminder", today=date(2026, 10, 1)
    ).allowed
    assert not q.check(
        "alex-example", "mattermost_dm", "weekly-checkin", today=date(2027, 1, 1)
    ).allowed
    assert not q.check("alex-example", "email", "weekly-checkin", today=date(2026, 10, 1)).allowed
    assert q.allowed_users("mattermost_dm", today=date(2026, 10, 1)) == ["alex-example"]
    assert q.allowed_users("mattermost_dm", today=date(2027, 2, 1)) == []


def test_unknown_channel(tmp_path: Path) -> None:
    p = ContactPolicy(tmp_path / "contacts.yaml")
    assert not p.check("x", "carrier-pigeon", "y").allowed
    with pytest.raises(ValueError):
        p.grant("x", "carrier-pigeon", ["*"])


def test_revoke(tmp_path: Path) -> None:
    p = ContactPolicy(tmp_path / "contacts.yaml")
    p.grant("a", "email", ["*"])
    p.grant("a", "mattermost_dm", ["*"])
    assert p.revoke("a", "email")
    assert "email" not in p.grants["a"]
    assert p.revoke("a")
    assert p.grants == {}
    assert not p.revoke("a")


def test_malformed_file(tmp_path: Path) -> None:
    f = tmp_path / "contacts.yaml"
    f.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ContactPolicy(f)
