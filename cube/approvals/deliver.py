"""`cube deliver <id>`: perform an approved action. Dry-run by default; email is never sent."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.approvals.store import Approval, ApprovalError, ApprovalStore
from cube.config import Settings
from cube.runners.base import Exec, HttpPost, default_exec, default_http_post


@dataclass
class DeliveryResult:
    ok: bool
    result: str  # queued_for_send|draft_opened|applied|sent|dry_run|failed
    message: str
    commands: list[list[str]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    dry_run: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path).expanduser()
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _strip_front_matter(text: str) -> str:
    s = text.lstrip()
    if s.startswith("---\n"):
        end = s.find("\n---", 4)
        if end > 0:
            return s[end + 4 :].lstrip("\n")
    return text


PERSON_KINDS = ("mattermost_dm", "mattermost_channel", "email")


def deliver(
    settings: Settings,
    store: ApprovalStore,
    approval_id: str,
    *,
    dry_run: bool = True,
    exec_fn: Exec | None = None,
    http_post: HttpPost | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> DeliveryResult:
    """Perform an approved action.

    Messages to people (``PERSON_KINDS``) go out only inside the configured
    contact hours; outside them the approval stays approved with
    ``delivery.deferred_until`` set, and ``cube patrol deliveries`` sends it in
    the next window. ``force`` (``cube deliver --now``) overrides the window.
    """
    approval = store.get(approval_id)
    if approval.status != "approved":
        raise ApprovalError(
            f"{approval_id} is {approval.status}; only approved items are delivered"
        )
    exec_fn = exec_fn or default_exec
    http_post = http_post or default_http_post
    if approval.kind in PERSON_KINDS and not force:
        from cube.contact_hours import (  # noqa: PLC0415
            contact_hours_text,
            next_contact_window,
            within_contact_hours,
        )

        moment = now or datetime.now(UTC)
        hours = settings.contact.hours
        if not within_contact_hours(hours, moment):
            window = next_contact_window(hours, moment)
            message = (
                f"outside contact hours ({contact_hours_text(hours)}); "
                f"deferred until {window.isoformat(timespec='minutes')}"
            )
            if not dry_run:
                approval.delivery = {
                    "result": "deferred",
                    "message": message,
                    "deferred_until": window.isoformat(timespec="minutes"),
                }
                store.save(approval)
            return DeliveryResult(False, "deferred", message, dry_run=dry_run)
    if approval.kind in ("mattermost_dm", "mattermost_channel"):
        res = _deliver_mattermost(settings, approval, dry_run, exec_fn, http_post)
    elif approval.kind == "email":
        res = _deliver_email(settings, approval, dry_run)
    elif approval.kind in ("org_edit", "file_change"):
        res = _deliver_diff(settings, approval, dry_run, exec_fn)
    else:
        res = DeliveryResult(
            False,
            "failed",
            f"kind {approval.kind} has no delivery path yet; Robert performs it by hand",
            dry_run=dry_run,
        )
    if res.ok and not dry_run:
        store.mark_delivered(approval, {"result": res.result, "message": res.message})
    return res


def _deliver_mattermost(
    settings: Settings, approval: Approval, dry_run: bool, exec_fn: Exec, http_post: HttpPost
) -> DeliveryResult:
    body = _strip_front_matter(_read(approval.body_file)).strip()
    if not body:
        return DeliveryResult(False, "failed", "empty body file", dry_run=dry_run)
    target = approval.to or ""
    if not target:
        return DeliveryResult(
            False, "failed", "no `to` (mattermost user or channel id)", dry_run=dry_run
        )
    token = settings.env.get("MATTERMOST_TOKEN")
    url = settings.env.get("MATTERMOST_URL", "https://borg.bio2vec.net").rstrip("/")
    if token and approval.kind == "mattermost_channel":
        payload = json.dumps({"channel_id": target, "message": body}).encode("utf-8")
        cmd = ["POST", f"{url}/api/v4/posts", f"channel_id={target}"]
        if dry_run:
            return DeliveryResult(True, "dry_run", "would POST to Mattermost", [cmd])
        status, raw = http_post(
            f"{url}/api/v4/posts",
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            payload,
            30.0,
        )
        ok = 200 <= status < 300
        return DeliveryResult(
            ok, "sent" if ok else "failed", f"HTTP {status}: {raw[:200]!r}", [cmd], dry_run=False
        )
    cmd = ["hermes", "send", "--to", f"mattermost:{target}", "--message", body]
    if dry_run:
        return DeliveryResult(True, "dry_run", "would run hermes send", [cmd])
    res = exec_fn(cmd, cwd=settings.root, env={}, timeout=60.0, stdin_devnull=True)
    ok = res.returncode == 0
    return DeliveryResult(
        ok,
        "sent" if ok else "failed",
        (res.stdout or res.stderr).strip()[:300],
        [cmd],
        dry_run=False,
    )


def _deliver_email(settings: Settings, approval: Approval, dry_run: bool) -> DeliveryResult:
    """Never sends. Writes a draft under runs/ and prints the Gnus emacsclient command."""
    body = _strip_front_matter(_read(approval.body_file)).strip()
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    draft_dir = settings.runs_dir() / day / "drafts"
    draft = draft_dir / f"{approval.id}.txt"
    header = (
        f"To: {approval.to or approval.person or ''}\n"
        f"Subject: {approval.subject or ''}\n"
        f"X-Cube-Approval: {approval.id}\n\n"
    )
    elisp = (
        "(progn (require 'gnus-msg) (gnus-msg-mail "
        f"{json.dumps(approval.to or '')} {json.dumps(approval.subject or '')}) "
        f"(goto-char (point-max)) (insert-file-contents {json.dumps(str(draft))}))"
    )
    cmd = ["emacsclient", "-s", "gnus", "--eval", elisp]
    if not dry_run:
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft.write_text(header + body + "\n", encoding="utf-8")
    return DeliveryResult(
        True,
        "dry_run" if dry_run else "draft_opened",
        f"draft {'would be ' if dry_run else ''}written; open in Gnus with: "
        + " ".join(shlex.quote(c) for c in cmd)
        + " (never sent automatically)",
        [cmd],
        [str(draft)],
        dry_run=dry_run,
    )


def _deliver_diff(
    settings: Settings, approval: Approval, dry_run: bool, exec_fn: Exec
) -> DeliveryResult:
    diff = Path(approval.diff_file or "").expanduser()
    if not approval.diff_file or not diff.exists():
        return DeliveryResult(
            False, "failed", f"diff file missing: {approval.diff_file}", dry_run=dry_run
        )
    target = Path(approval.target_dir or approval.to or settings.root).expanduser()
    if not target.is_absolute():
        target = settings.root / target
    if approval.kind == "org_edit" and not approval.target_dir and not approval.to:
        target = settings.dirs["org"]
    base = ["patch", "-p1", "-d", str(target), "-i", str(diff), "--no-backup-if-mismatch"]
    if dry_run:
        cmd = [*base, "--dry-run"]
        res = exec_fn(cmd, cwd=target, env={}, timeout=60.0, stdin_devnull=True)
        ok = res.returncode == 0
        return DeliveryResult(
            ok,
            "dry_run" if ok else "failed",
            f"patch --dry-run {'clean' if ok else 'failed'}: "
            + (res.stdout or res.stderr).strip()[:300],
            [cmd],
            [str(diff)],
        )
    res = exec_fn(base, cwd=target, env={}, timeout=60.0, stdin_devnull=True)
    ok = res.returncode == 0
    return DeliveryResult(
        ok,
        "applied" if ok else "failed",
        (res.stdout or res.stderr).strip()[:300],
        [base],
        [str(diff)],
        dry_run=False,
    )
