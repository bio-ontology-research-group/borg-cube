"""`cube approvals`, `cube approve <id>`, `cube reject <id>`, `cube deliver <id>`."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from cube.approvals import ApprovalError, ApprovalStore, deliver
from cube.commands import Helpers
from cube.config import Settings


def cmd_approvals(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    store = ApprovalStore(settings.state_dir())
    items = store.items(None if args.all else "pending")
    data = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "approvals": [a.cockpit() for a in items],
    }
    text = "\n".join(f"{a.id} [{a.status}] {a.summary()}" for a in items) or "no approvals"
    helpers.emit(args, data, text)
    return 0


def _decide(args: argparse.Namespace, settings: Settings, helpers: Helpers, approve: bool) -> int:
    store = ApprovalStore(settings.state_dir())
    try:
        ap = store.decide(
            args.id,
            approve=approve,
            by=args.by,
            reason=getattr(args, "reason", None),
            body_file=getattr(args, "body_file", None),
        )
    except ApprovalError as exc:
        helpers.emit(args, {"ok": False, "id": args.id, "error": str(exc)}, f"error: {exc}")
        return 3
    if approve:
        result = "queued_for_send" if ap.kind not in ("org_edit", "file_change") else "applied"
        if ap.kind == "email":
            result = "draft_opened"
        message = f"approved; run `cube deliver {ap.id} --apply` to perform it ({ap.summary()})"
    else:
        result, message = "rejected", f"rejected: {ap.reason}"
    data: dict[str, Any] = {
        "ok": True,
        "id": ap.id,
        "action": "approve" if approve else "reject",
        "result": result,
        "message": message,
        "approval": ap.cockpit(),
    }
    helpers.emit(args, data, message)
    return 0


def cmd_deliver(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    store = ApprovalStore(settings.state_dir())
    try:
        res = deliver(settings, store, args.id, dry_run=args.dry_run, force=bool(args.now))
    except ApprovalError as exc:
        helpers.emit(args, {"ok": False, "id": args.id, "error": str(exc)}, f"error: {exc}")
        return 3
    data = {"id": args.id, **res.as_dict()}
    helpers.emit(args, data, f"{'DRY-RUN ' if res.dry_run else ''}{res.result}: {res.message}")
    return 0 if res.ok else 1


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("approvals", help="the approval queue")
    sp.add_argument("--all", action="store_true", help="include decided items")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_approvals(a, s, helpers))

    sp = sub.add_parser("approve", help="approve an outbound or write action (does not send)")
    sp.add_argument("id")
    sp.add_argument("--body-file", dest="body_file", help="replace the body with this file")
    sp.add_argument("--by", default="robert")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: _decide(a, s, helpers, True))

    sp = sub.add_parser("reject", help="reject an approval")
    sp.add_argument("id")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--by", default="robert")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: _decide(a, s, helpers, False))

    sp = sub.add_parser("deliver", help="perform an approved action (dry-run by default)")
    sp.add_argument("id")
    sp.add_argument(
        "--now",
        action="store_true",
        help="send even outside contact hours (people are otherwise reached 07:00-19:00)",
    )
    helpers.add_json(sp)
    helpers.add_dry(sp)
    sp.set_defaults(fn=lambda a, s: cmd_deliver(a, s, helpers))
