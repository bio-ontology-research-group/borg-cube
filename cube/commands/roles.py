"""`cube roles --json`: the functional roles an agent can play, from roles/*.yaml."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.roles.loader import load_all


def roles_payload(settings: Settings) -> dict[str, Any]:
    roles, errors = load_all(settings.root)
    rows = [
        {
            "name": r.name,
            "summary": r.summary,
            "runtime": r.runtime,
            "tier": r.tier,
            "model": r.model,
            "skills": list(r.skills),
            "can_close": r.can_close,
            "review_required_by": r.review_required_by,
            "privacy_max": r.privacy_max,
            "triggers": list(r.triggers),
        }
        for r in roles.values()
    ]
    return {"roles": rows, "errors": errors}


def cmd_roles(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    payload = roles_payload(settings)
    lines = [
        f"{r['name']:14} {r['runtime']:8} {r['tier']:10} {r['summary']}" for r in payload["roles"]
    ]
    lines += [f"ERROR {name}: {err}" for name, err in payload["errors"].items()]
    helpers.emit(args, payload, "\n".join(lines) or "no roles")
    return 1 if payload["errors"] else 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("roles", help="functional roles an agent can play (roles/*.yaml)")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_roles(a, s, helpers))
