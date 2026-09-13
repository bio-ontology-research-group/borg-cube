"""state/approvals/<id>.json, one file per outbound or irreversible intent."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field

from cube.audit import audit
from cube.contact import ContactPolicy
from cube.notify import append_event, make_event

ApprovalKind = Literal[
    "email",
    "mattermost_dm",
    "mattermost_channel",
    "github",
    "portal",
    "org_edit",
    "file_change",
]
APPROVAL_KINDS: tuple[str, ...] = (
    "email",
    "mattermost_dm",
    "mattermost_channel",
    "github",
    "portal",
    "org_edit",
    "file_change",
)
Status = Literal["pending", "approved", "rejected", "delivered"]

# kind -> ContactPolicy channel (file edits are not contact; they still need approval)
CONTACT_CHANNEL: dict[str, str | None] = {
    "email": "email",
    "mattermost_dm": "mattermost_dm",
    "mattermost_channel": "mattermost_channel",
    "github": "github",
    "portal": "portal",
    "org_edit": None,
    "file_change": None,
}


class ApprovalError(RuntimeError):
    pass


class Intent(BaseModel):
    """What a role wants to do; parsed from an artifact file's YAML front matter."""

    kind: ApprovalKind
    to: str | None = None
    person: str | None = None
    channel: str | None = None
    action: str = "message"
    subject: str | None = None
    body_file: str | None = None
    diff_file: str | None = None
    target_dir: str | None = None


class Approval(BaseModel):
    id: str
    kind: ApprovalKind
    to: str | None = None
    person: str | None = None
    channel: str | None = None
    action: str = "message"
    subject: str | None = None
    body_file: str | None = None
    diff_file: str | None = None
    target_dir: str | None = None
    created_by: str
    run_id: str | None = None
    bead: str | None = None
    status: Status = "pending"
    created: str
    decided: str | None = None
    decided_by: str | None = None
    reason: str | None = None
    policy: dict[str, Any] = Field(default_factory=dict)
    delivery: dict[str, Any] | None = None

    def age_seconds(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        return max(0, int((now - datetime.fromisoformat(self.created)).total_seconds()))

    def summary(self) -> str:
        target = self.person or self.to or self.target_dir or "?"
        return f"{self.kind} to {target}" + (f": {self.subject}" if self.subject else "")

    def cockpit(self) -> dict[str, Any]:
        """Shape from emacs/INTERFACE.md approvals fixture."""
        kind = "write" if self.kind in ("org_edit", "file_change") else "outbound"
        return {
            "id": self.id,
            "kind": kind,
            "channel": self.channel or self.kind,
            "recipient": self.person or self.to,
            "summary": self.summary(),
            "draft_file": self.body_file or self.diff_file,
            "created": self.created,
            "run_id": self.run_id,
            "bead": self.bead,
            "status": self.status,
            "actions": ["approve", "reject", "edit"] if self.status == "pending" else [],
            "policy": self.policy,
        }


def _iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).isoformat(timespec="seconds")


def front_matter(block: str) -> dict[str, Any]:
    """The header as a dict; a header that is not YAML is read line by line.

    A run wrote ``subject: FLOPO status: audit filed`` (a second colon), YAML
    refused it and the whole agent_workday patrol failed twice on 2026-09-07.
    One run's header never stops a patrol: the fallback reads ``key: rest of
    line`` and the kind check below still decides whether it is an intent.
    """
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError:
        loaded = None
    if isinstance(loaded, dict):
        return loaded
    meta: dict[str, Any] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and key[:1] not in (" ", "\t", "-", "#"):
            meta[key.strip()] = value.strip().strip("'\"")
    return meta


def intent_from_file(path: Path, *, default_kind: str | None = None) -> Intent | None:
    """Read `---` YAML front matter (to, person, channel, action, subject) from an artifact."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    stripped = text.lstrip()
    if stripped.startswith("---\n"):
        end = stripped.find("\n---", 4)
        if end > 0:
            meta = front_matter(stripped[4:end])
    kind_raw = str(meta.get("kind") or meta.get("channel") or default_kind or "")
    if kind_raw not in APPROVAL_KINDS:
        return None
    kind = cast(ApprovalKind, kind_raw)
    is_diff = kind in ("org_edit", "file_change")
    return Intent(
        kind=kind,
        to=str(meta["to"]) if meta.get("to") else None,
        person=str(meta["person"]) if meta.get("person") else None,
        channel=str(meta.get("channel") or CONTACT_CHANNEL.get(kind) or "") or None,
        action=str(meta.get("action") or ("edit" if is_diff else "message")),
        subject=str(meta["subject"]) if meta.get("subject") else None,
        body_file=None if is_diff else str(path),
        diff_file=str(path) if is_diff else None,
        target_dir=str(meta["target_dir"]) if meta.get("target_dir") else None,
    )


class ApprovalStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.dir = state_dir / "approvals"

    def _path(self, approval_id: str) -> Path:
        return self.dir / f"{approval_id}.json"

    def new_id(self, now: datetime | None = None) -> str:
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        return f"apr-{stamp}-{secrets.token_hex(2)}"

    def save(self, approval: Approval) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(approval.id)
        path.write_text(approval.model_dump_json(indent=1), encoding="utf-8")
        return path

    def get(self, approval_id: str) -> Approval:
        path = self._path(approval_id)
        if not path.exists():
            raise ApprovalError(f"no such approval: {approval_id}")
        return Approval.model_validate_json(path.read_text(encoding="utf-8"))

    def items(self, status: str | None = None) -> list[Approval]:
        if not self.dir.exists():
            return []
        out: list[Approval] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                item = Approval.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if status is None or item.status == status:
                out.append(item)
        return out

    def create(
        self,
        intent: Intent,
        *,
        policy: ContactPolicy,
        created_by: str,
        autonomous_actions: list[str] | None = None,
        run_id: str | None = None,
        bead: str | None = None,
        now: datetime | None = None,
    ) -> Approval:
        """Check ContactPolicy first; auto-approve only with a grant AND a listed autonomous
        action (never true today). Everything else is pending for Robert."""
        channel = intent.channel or CONTACT_CHANNEL.get(intent.kind)
        decision: dict[str, Any]
        if channel and intent.person:
            d = policy.check(
                intent.person, channel, intent.action, today=(now or datetime.now(UTC)).date()
            )
            decision = d.as_dict()
        elif channel:
            decision = {"allowed": False, "reason": "no person named; default deny"}
        else:
            decision = {
                "allowed": False,
                "reason": f"{intent.kind} is a local write; needs approval",
            }
        auto = bool(decision.get("allowed")) and intent.action in (autonomous_actions or [])
        approval = Approval(
            id=self.new_id(now),
            kind=intent.kind,
            to=intent.to,
            person=intent.person,
            channel=channel,
            action=intent.action,
            subject=intent.subject,
            body_file=intent.body_file,
            diff_file=intent.diff_file,
            target_dir=intent.target_dir,
            created_by=created_by,
            run_id=run_id,
            bead=bead,
            status="approved" if auto else "pending",
            created=_iso(now),
            decided=_iso(now) if auto else None,
            decided_by="policy+autonomous_actions" if auto else None,
            policy={**decision, "auto_approved": auto},
        )
        self.save(approval)
        append_event(
            self.state_dir,
            make_event(
                "approval",
                source="cube",
                title=f"approval {'auto-approved' if auto else 'pending'}: {approval.summary()}",
                body=json.dumps(approval.cockpit(), ensure_ascii=False),
                run_id=run_id,
                bead=bead,
                data={"approval": approval.id, "status": approval.status},
            ),
        )
        audit(
            self.state_dir,
            "approval.create",
            approval=approval.id,
            kind=approval.kind,
            person=approval.person,
            status=approval.status,
            run_id=run_id,
            bead=bead,
            policy=decision.get("reason"),
        )
        return approval

    def decide(
        self,
        approval_id: str,
        *,
        approve: bool,
        by: str = "robert",
        reason: str | None = None,
        body_file: str | None = None,
        now: datetime | None = None,
    ) -> Approval:
        approval = self.get(approval_id)
        if approval.status != "pending":
            raise ApprovalError(f"{approval_id} is already {approval.status}")
        if not approve and not reason:
            raise ApprovalError("a rejection needs --reason")
        approval.status = "approved" if approve else "rejected"
        approval.decided = _iso(now)
        approval.decided_by = by
        approval.reason = reason
        if body_file:
            approval.body_file = body_file
        self.save(approval)
        append_event(
            self.state_dir,
            make_event(
                "approval",
                source="cube",
                title=f"{approval.status}: {approval.summary()}",
                run_id=approval.run_id,
                bead=approval.bead,
                data={"approval": approval.id, "status": approval.status, "by": by},
            ),
        )
        audit(
            self.state_dir,
            f"approval.{approval.status}",
            approval=approval.id,
            by=by,
            reason=reason,
            kind=approval.kind,
            person=approval.person,
        )
        return approval

    def mark_delivered(self, approval: Approval, delivery: dict[str, Any]) -> Approval:
        approval.status = "delivered"
        approval.delivery = delivery
        self.save(approval)
        audit(self.state_dir, "approval.delivered", approval=approval.id, **delivery)
        return approval
