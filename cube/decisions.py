"""One list of everything waiting for Robert's answer, and the single answer path.

Agents reach Robert through several channels: the outbound approval store, beads
labelled `needs:robert` (question, request, proposal, finding, conflict), the
`resource:approval` beads a standing agent's workday files, and pipeline
recruitment requests. `pending_decisions` normalises all of them into one shape
so the cockpit can show them in one buffer, and `decide` answers any of them and
routes the answer back to whoever asked.

Nothing here sends anything. An outbound approval still goes through the existing
`ApprovalStore.decide` plus `cube deliver` path.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from cube.agents import (
    RESOURCE_STEP_SEPARATOR,
    AgentError,
    add_grant,
    append_inbox,
    grants_path,
    load_agent,
)
from cube.approvals import Approval, ApprovalError, ApprovalStore
from cube.beads import Beads, BeadsError
from cube.config import DECISION_GUARDS, DecisionRule, Settings
from cube.engine.attention import acknowledge
from cube.engine.context import bead_labels, label_value
from cube.model import BeadHeader, Privacy, Provenance
from cube.notify import append_event, make_event
from cube.systems import names_system

DECISIONS_FILE = "decisions.jsonl"
ANSWERED_LIMIT = 20

FREE = ["free"]
YES_NO = ["yes", "no"]
APPROVE_REJECT = ["approve", "reject"]
ACCEPT_REJECT_FREE = ["accept", "reject", "free"]

CLOSED_STATUSES = {"closed", "done"}
POSITIVE = {"yes", "approve", "accept", "recruit", "y"}
NEGATIVE = {"no", "reject", "deny", "decline", "n"}

FIELD_RE = "^{name}:[ \t]*(.+?)[ \t]*$"


class DecisionError(ValueError):
    """The decision does not exist, or the answer does not fit its options."""


# --- reading ----------------------------------------------------------------


def _field(description: str, name: str) -> str | None:
    match = re.search(FIELD_RE.format(name=re.escape(name)), description or "", re.MULTILINE)
    return match.group(1) if match else None


BODY_MAX_CHARS = 4000


def _strip_header(description: str) -> str:
    """The bead text without its YAML header block."""
    text = description.lstrip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            return text[end + 4 :].lstrip("\n")
    return description


def decision_body(description: str) -> str:
    """What Robert must read to decide: the bead text minus header, capped."""
    body = _strip_header(description or "").strip()
    if len(body) > BODY_MAX_CHARS:
        body = body[:BODY_MAX_CHARS].rstrip() + "\n[truncated; RET opens the full bead]"
    return body


SUMMARY_LINES = 4
SUMMARY_CHARS = 320
_SUMMARY_FIELDS = ("Question", "Finding", "Summary", "Rationale", "Resources requested", "Why")


def decision_summary(body: str) -> str:
    """A few lines Robert can read at a glance; never pages.

    Prefers the labelled lines agents write (Question, Finding, Summary,
    Rationale, Resources requested, Why), then the first lines of the text.
    """
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    picked: list[str] = [line for line in lines if line.split(":", 1)[0] in _SUMMARY_FIELDS][
        :SUMMARY_LINES
    ]
    for line in lines:
        if len(picked) >= SUMMARY_LINES:
            break
        if line not in picked and not line.startswith("#"):
            picked.append(line)
    text = "\n".join(picked)
    if len(text) > SUMMARY_CHARS:
        text = text[:SUMMARY_CHARS].rstrip() + " ..."
    return text


def _approval_body(approval: Approval) -> str:
    parts: list[str] = []
    if approval.subject:
        parts.append(f"Subject: {approval.subject}")
    if approval.to or approval.person:
        parts.append(f"To: {approval.person or ''} {approval.to or ''}".strip())
    for path in (approval.body_file, approval.diff_file):
        if not path:
            continue
        file = Path(path).expanduser()
        if file.exists():
            parts.append(_strip_header(file.read_text(encoding="utf-8", errors="replace")))
    return decision_body("\n\n".join(parts))


def _options_from_body(description: str) -> list[str]:
    raw = _field(description, "Options")
    if not raw:
        return list(FREE)
    options = [part.strip() for part in re.split(r"[|,]", raw) if part.strip()]
    return options or list(FREE)


def _evidence(header: BeadHeader | None) -> list[str]:
    if header is None:
        return []
    out: list[str] = []
    for item in header.provenance:
        out.append(f"{item.source}#{item.locator}" if item.locator else item.source)
    return out


def _run_id(header: BeadHeader | None) -> str | None:
    if header is None:
        return None
    for item in header.provenance:
        if item.source.startswith("runs/"):
            return item.source.split("/", 1)[1]
    return None


def _asker(labels: list[str]) -> str:
    """Who is waiting for the answer, as `agent:x`, `role:x`, `patrol:x` or `cube`."""
    for prefix in ("agent:", "patrol:", "role:"):
        name = label_value(labels, prefix)
        if name:
            return f"{prefix}{name}"
    origin = label_value(labels, "from:")
    if origin:
        return origin if ":" in origin else f"role:{origin}"
    return "cube"


def _asker_host(settings: Settings, asker: str) -> str | None:
    """The host that must deliver the answer, when the asker is a standing agent."""
    if not asker.startswith("agent:"):
        return None
    try:
        return load_agent(settings.root, asker.split(":", 1)[1]).host
    except (AgentError, OSError):
        return None


ANSWER_LABEL = "answer:robert"
"""A bead that carries Robert's answer to a role: work for the role, never a decision."""
NEEDS_ROBERT_LABEL = "needs:robert"
APPROVED_LABEL = "approved:robert"
LAPTOP_READ_LABEL = "laptop-read:approval"
"""A liaison request that reaches beyond the readable directories (ADR-0027)."""


def _bead_kind(labels: list[str]) -> str | None:
    """Map a bead's labels onto a decision kind, or None when it is not a decision."""
    if ANSWER_LABEL in labels:
        return None
    if "pipeline-stage:recruit" in labels:
        return "recruit"
    if "resource:approval" in labels:
        return "permission"
    kind = label_value(labels, "kind:")
    if kind == "request":
        return "permission"
    if kind == "approval":
        # A prepared change (the sysadmin's per-host bundle, doctrine 7a) is
        # answered like a proposal: accept keeps it open as approved, reject closes.
        return "proposal"
    if kind in {"question", "proposal", "finding", "conflict"}:
        return kind
    return None


def _options_for(kind: str, description: str) -> list[str]:
    if kind in {"permission", "recruit"}:
        return list(YES_NO)
    if kind == "question":
        return _options_from_body(description)
    if kind in {"proposal", "finding", "conflict"}:
        return list(ACCEPT_REJECT_FREE)
    return list(APPROVE_REJECT)


def _answer_command(ident: str, options: list[str]) -> list[str]:
    if options == FREE:
        return ["decide", ident, "--text", "<your answer>"]
    return ["decide", ident, "--choice", options[0]]


def _age(since: str | None, now: datetime) -> int:
    if not since:
        return 0
    try:
        stamp = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(0, int((now - stamp).total_seconds()))


def _member_kind(description: str) -> str | None:
    """`agent`, `role` or `person` from a recruitment request's Candidate line."""
    candidate = _field(description, "Candidate")
    if not candidate:
        return None
    prefix, _, _rest = candidate.partition(":")
    return prefix.strip() or None


def _declared_spend(description: str) -> float:
    """The `spend_usd` a resource request declares, or 0."""
    body = description.split("Declared needs:", 1)
    if len(body) != 2:
        return 0.0
    loaded = yaml.safe_load(body[1])
    if not isinstance(loaded, dict):
        return 0.0
    try:
        return float(loaded.get("spend_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


DIFF_TARGET_RE = re.compile(r"^\+\+\+ (?:b/)?(?P<path>\S+)", re.MULTILINE)
DIFF_DELETE_MARKERS = ("deleted file mode", "+++ /dev/null")


def _diff_text(approval: Approval) -> str:
    if not approval.diff_file:
        return ""
    path = Path(approval.diff_file).expanduser()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _approval_targets(approval: Approval) -> list[str]:
    """Paths a file change would touch: the declared target dir plus the diff's own paths."""
    targets: list[str] = []
    if approval.target_dir:
        targets.append(str(approval.target_dir))
    targets += [
        match.group("path")
        for match in DIFF_TARGET_RE.finditer(_diff_text(approval))
        if match.group("path") != "/dev/null"
    ]
    return targets


def _approval_deletes(approval: Approval) -> bool:
    """True when the change removes a file; a deletion is never answered by policy."""
    text = _diff_text(approval)
    return (
        any(marker in text for marker in DIFF_DELETE_MARKERS)
        or "delete" in (approval.action or "").lower()
    )


def _decision_from_bead(
    settings: Settings, bead: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    labels = bead_labels(bead)
    if "needs:robert" not in labels:
        return None
    if "approved:robert" in labels:
        return None  # an accepted proposal stays open for work, not for a decision
    kind = _bead_kind(labels)
    if kind is None:
        return None
    ident = str(bead.get("id") or "")
    description = str(bead.get("description") or "")
    header = BeadHeader.parse(description)
    title = str(bead.get("title") or ident)
    question = _field(description, "Question") or title
    options = _options_for(kind, description)
    since = str(bead.get("created_at") or bead.get("created") or "") or None
    asker = _asker(labels)
    host = _asker_host(settings, asker)
    return {
        "id": ident,
        "source": "bead",
        "kind": kind,
        "from": asker,
        "title": title,
        "question": question,
        "body": decision_body(description),
        "summary": decision_summary(decision_body(description)),
        "options": options,
        "context": {
            "bead": ident,
            "epic": label_value(labels, "goal:"),
            "run_id": _run_id(header),
            "evidence": _evidence(header),
            "host": host,
            "labels": labels,
            "resource_class": _field(description, "Resource class"),
            "member_kind": _member_kind(description),
            "spend_usd": _declared_spend(description),
            "approval_kind": None,
            "targets": [],
            "deletes": False,
            "recipient": None,
            "system": names_system(settings.decisions.systems, title, description),
        },
        "since": since,
        "age": _age(since, now),
        "answer_command": _answer_command(ident, options),
    }


def _decision_from_approval(
    approval: Approval, now: datetime, settings: Settings | None = None
) -> dict[str, Any]:
    created_by = approval.created_by or "cube"
    origin = created_by.split("/", 1)[0]
    systems = settings.decisions.systems if settings is not None else []
    return {
        "id": approval.id,
        "source": "approval",
        "kind": "approval",
        "from": f"role:{origin}" if origin and ":" not in origin else (origin or "cube"),
        "title": approval.summary(),
        "question": f"Approve this {approval.kind}: {approval.summary()}?",
        "body": _approval_body(approval),
        "summary": decision_summary(_approval_body(approval)),
        "options": list(APPROVE_REJECT),
        "context": {
            "bead": approval.bead,
            "epic": None,
            "run_id": approval.run_id,
            "evidence": [item for item in (approval.body_file, approval.diff_file) if item],
            "host": None,
            "labels": [],
            "resource_class": None,
            "member_kind": None,
            "spend_usd": 0.0,
            "approval_kind": approval.kind,
            "targets": _approval_targets(approval),
            "deletes": _approval_deletes(approval),
            "recipient": approval.person or approval.to,
            # The summary, subject and target paths name the system; the body does
            # not: a diff whose comment says "on ws" is still a checkout change.
            "system": names_system(
                systems,
                approval.summary(),
                approval.subject,
                approval.target_dir,
                *_approval_targets(approval),
            ),
        },
        "since": approval.created,
        "age": _age(approval.created, now),
        "answer_command": _answer_command(approval.id, list(APPROVE_REJECT)),
    }


def pending_decisions(
    settings: Settings, beads: Beads | None = None, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Every open question, permission, approval and proposal, newest last."""
    now = now or datetime.now(UTC)
    items: list[dict[str, Any]] = []
    if beads is not None and beads.available():
        try:
            for bead in beads.list_issues("--label", "needs:robert", "--status", "open"):
                item = _decision_from_bead(settings, bead, now)
                if item is not None:
                    items.append(item)
        except BeadsError:
            pass
    for approval in ApprovalStore(settings.state_dir()).items("pending"):
        items.append(_decision_from_approval(approval, now, settings))
    if settings.fleet_enabled:
        from cube.sysops import pending

        for record in pending(settings):
            payload = record["payload"]
            lines = [
                f"Host: {payload['host']}",
                f"Rationale: {payload['rationale']}",
                f"Expected impact: {payload['impact']}",
            ]
            for phase in ("prechecks", "commands", "postchecks", "rollback"):
                lines += [f"{phase}:", *[shlex.join(argv) for argv in payload[phase]]]
            lines += ["Evidence: " + ", ".join(payload["evidence"])]
            body = "\n".join(lines)
            items.append(
                {
                    "id": record["id"],
                    "kind": "sysadmin-change",
                    "from": "agent:sysadmin",
                    "title": f"Prepared changes on {payload['host']}",
                    "body": body,
                    "summary": body,
                    "options": ["approve", "deny", "free"],
                    "age": 0,
                    "context": {"critical": "security", "system": payload["host"]},
                    "since": now.isoformat(),
                    "answer_command": f"cube decide {record['id']}",
                }
            )
    items.sort(key=lambda item: (-int(item["age"]), str(item["id"])))
    return _fold_duplicates(items)


def _fold_duplicates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identical asks (kind, asker, title, body) show once; the shown one lists the rest.

    Answering the shown decision answers its duplicates too (see ``decide``).
    """
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    folded: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item["kind"]),
            str(item["from"]),
            str(item["title"]),
            str(item.get("body") or ""),
        )
        first = seen.get(key)
        if first is None:
            item["duplicates"] = []
            seen[key] = item
            folded.append(item)
        else:
            first["duplicates"].append(str(item["id"]))
    return folded


def _unfolded(settings: Settings, beads: Beads | None, now: datetime) -> dict[str, dict[str, Any]]:
    """Every pending decision by id, duplicates included."""
    items = pending_decisions(settings, beads, now=now)
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        by_id[str(item["id"])] = item
        for dup in item.get("duplicates", []):
            copy = dict(item, id=dup, duplicates=[])
            copy["context"] = dict(
                item["context"],
                bead=dup if item["source"] == "bead" else item["context"].get("bead"),
            )
            copy["answer_command"] = [
                dup if part == item["id"] else part for part in item["answer_command"]
            ]
            by_id[dup] = copy
    return by_id


def decisions_log(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / DECISIONS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def answered_decisions(state_dir: Path, limit: int = ANSWERED_LIMIT) -> list[dict[str, Any]]:
    """The last answers Robert gave, newest last."""
    return [
        {
            "id": str(row.get("id") or ""),
            "choice": row.get("choice"),
            "text": row.get("text"),
            "ts": row.get("ts"),
            "by": row.get("by") or "robert",
        }
        for row in decisions_log(state_dir)[-limit:]
    ]


def decisions_payload(
    settings: Settings, beads: Beads | None = None, *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    decisions = pending_decisions(settings, beads, now=now)
    for item in decisions:
        item["policy_preview"] = policy_preview(settings, item, now=now)
    return {
        "generated": now.isoformat(timespec="seconds"),
        "decisions": decisions,
        "answered": answered_decisions(settings.state_dir()),
    }


def decisions_text(payload: dict[str, Any]) -> str:
    rows = payload.get("decisions") or []
    if not rows:
        return "nothing waiting for you"
    return "\n".join(
        f"{row['id']:<12} {row['kind']:<10} {row['from']:<20} {row['question']}" for row in rows
    )


# --- asking -----------------------------------------------------------------


ASK_RE = re.compile(r"^(?:agent|role|patrol):[a-z][a-z0-9-]*$")
CRITICAL_KINDS = {"security", "privacy"}
COORDINATOR_ASKER = "agent:coordinator"


def question_xid(sender: str, text: str) -> str:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:8]
    return f"question:{sender}:{digest}"


def ask(
    settings: Settings,
    beads: Beads,
    *,
    sender: str,
    text: str,
    options: list[str] | None = None,
    bead: str | None = None,
    epic: str | None = None,
    run_id: str | None = None,
    dry_run: bool = True,
    now: datetime | None = None,
    critical: str | None = None,
) -> dict[str, Any]:
    """File one free-text or multiple-choice question and stop.

    Robert, 2026-09-08 (ADR-0027): a question reaches Robert only when it is
    security-critical or privacy-critical (``critical``); every other question is
    the coordinator's to settle, so it is filed for ``agent:coordinator`` and never
    carries ``needs:robert``.
    """
    if not ASK_RE.match(sender):
        raise DecisionError("--from must be agent:<name>, role:<name> or patrol:<name>")
    if not text.strip():
        raise DecisionError("a question needs text")
    if critical is not None and critical not in CRITICAL_KINDS:
        raise DecisionError(f"--critical must be one of {', '.join(sorted(CRITICAL_KINDS))}")
    now = now or datetime.now(UTC)
    xid = question_xid(sender, text)
    existing = beads.find_by_xid(xid) if beads.available() else None
    if existing is not None:
        return {
            "bead": str(existing.get("id") or ""),
            "xid": xid,
            "created": False,
            "dry_run": dry_run,
            "question": text.strip(),
            "options": options or list(FREE),
        }
    if run_id:
        provenance = [Provenance(source=f"runs/{run_id}", locator="result.json", seen=now.date())]
    elif bead:
        provenance = [Provenance(source=f"bead:{bead}", locator="question", seen=now.date())]
    else:
        provenance = [Provenance(source=sender, locator="cube question new", seen=now.date())]
    labels = ["kind:question", sender, "privacy:internal"]
    if critical:
        labels += ["needs:robert", f"critical:{critical}"]
        decider = "robert"
    elif sender == COORDINATOR_ASKER:
        raise DecisionError(
            "the coordinator settles questions itself (ADR-0027); add --critical "
            "security or --critical privacy when the matter is Robert's"
        )
    else:
        labels.append(COORDINATOR_ASKER)
        decider = "coordinator"
    if epic:
        labels.append(f"goal:{epic}")
    body = f"Question: {text.strip()}"
    if options:
        body += "\nOptions: " + " | ".join(options)
    bead_id = beads.create(
        f"Question from {sender}: {text.strip()[:60]}",
        header=BeadHeader(xid=xid, provenance=provenance, privacy=Privacy.internal),
        body=body,
        labels=labels,
        acceptance=(
            "Robert answers in the cockpit or on Mattermost; the answer reaches the asker."
            if decider == "robert"
            else "The coordinator answers on this bead and tells the asker (ADR-0027)."
        ),
    )
    if not dry_run and decider == "robert":
        append_event(
            settings.state_dir(),
            make_event(
                "attention",
                source="decisions",
                title=f"{sender} asks Robert: {text.strip()[:80]}",
                bead=bead_id,
                data={"kind": "needs_robert", "decision": bead_id, "from": sender},
            ),
        )
    return {
        "bead": bead_id,
        "xid": xid,
        "created": True,
        "dry_run": dry_run,
        "question": text.strip(),
        "options": options or list(FREE),
        "decider": decider,
    }


# --- answering --------------------------------------------------------------


def _record(
    state_dir: Path,
    decision: dict[str, Any],
    choice: str | None,
    text: str | None,
    now: datetime,
    by: str = "robert",
) -> dict[str, Any]:
    row = {
        "id": decision["id"],
        "choice": choice,
        "text": text,
        "ts": now.isoformat(timespec="seconds"),
        "kind": decision["kind"],
        "source": decision["source"],
        "from": decision["from"],
        "by": by,
    }
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / DECISIONS_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _positive(choice: str | None) -> bool | None:
    if choice is None:
        return None
    value = choice.strip().lower()
    if value in POSITIVE:
        return True
    if value in NEGATIVE:
        return False
    return None


def _answer_text(choice: str | None, text: str | None) -> str:
    return (text or "").strip() or (choice or "").strip()


def _validate(decision: dict[str, Any], choice: str | None, text: str | None) -> None:
    if not choice and not text:
        raise DecisionError("an answer needs --choice or --text")
    options = [str(item) for item in decision.get("options") or []]
    if choice and options and options != FREE and choice.strip().lower() not in options:
        raise DecisionError(f"{choice!r} is not one of {', '.join(options)}")


def _approval_result(approval: Approval, approve: bool) -> dict[str, Any]:
    """The shape `cube approve`/`cube reject` return, so the cockpit sees one contract."""
    if approve:
        result = (
            "queued_for_send" if approval.kind not in ("org_edit", "file_change") else "applied"
        )
        if approval.kind == "email":
            result = "draft_opened"
        message = (
            f"approved; run `cube deliver {approval.id} --apply` to perform it "
            f"({approval.summary()})"
        )
    else:
        result, message = "rejected", f"rejected: {approval.reason}"
    return {
        "ok": True,
        "id": approval.id,
        "action": "approve" if approve else "reject",
        "result": result,
        "message": message,
        "approval": approval.cockpit(),
    }


def _recruit_member(settings: Settings, description: str) -> tuple[str, str | None]:
    """Return the candidate and the functional role `cube pipeline recruit` needs."""
    member = _field(description, "Candidate") or ""
    if not member:
        raise DecisionError("the recruitment request names no candidate")
    prefix, _, name = member.partition(":")
    if prefix == "role":
        return member, name
    if prefix == "agent":
        try:
            return member, load_agent(settings.root, name).role
        except AgentError as exc:
            raise DecisionError(str(exc)) from exc
    return member, None


RESOURCE_STEP_RE = re.compile(re.escape(RESOURCE_STEP_SEPARATOR) + r"(?P<step>.+)$")


def _resource_needs(title: str, description: str) -> tuple[str, dict[str, Any]]:
    """Return the step title and the declared needs of a `resource:approval` bead."""
    match = RESOURCE_STEP_RE.search(title)
    step = match.group("step") if match else title
    body = description.split("Declared needs:", 1)
    needs: dict[str, Any] = {}
    if len(body) == 2:
        loaded = yaml.safe_load(body[1])
        if isinstance(loaded, dict):
            needs = dict(loaded)
    return step, needs


def relay_command(agent_name: str, answer: str) -> list[str]:
    """The delivery command the cockpit re-runs on the agent's own host."""
    return [
        "cube",
        "agent",
        "tell",
        agent_name,
        f"Robert answered: {answer}",
        "--from",
        "robert",
        "--apply",
        "--json",
    ]


def _deliver_to_asker(
    settings: Settings,
    beads: Beads,
    decision: dict[str, Any],
    answer: str,
    *,
    dry_run: bool,
    now: datetime,
) -> dict[str, Any]:
    """Put the answer where the asker will read it: an inbox, or a follow-up bead."""
    origin = str(decision["from"])
    if origin.startswith("agent:"):
        name = origin.split(":", 1)[1]
        try:
            agent = load_agent(settings.root, name)
        except AgentError as exc:
            return {"delivery": None, "note": str(exc)}
        if agent.host != settings.host:
            # The bead is answered here; only the inbox append has to happen on the
            # agent's own machine, exactly as `cube agent inbox` relays its pass.
            return {
                "delivery": f"relay:{agent.host}",
                "relay": agent.host,
                "command": relay_command(agent.name, answer),
            }
        if not dry_run:
            append_inbox(settings.root, agent, f"Robert answered: {answer}", sender="robert")
        return {"delivery": f"inbox:agent:{agent.name}"}
    if origin.startswith("role:"):
        role_name = origin.split(":", 1)[1]
        follow_up = beads.create(
            f"Robert answered: {decision['title']}",
            header=BeadHeader(
                xid=f"answer:{decision['id']}:{now.strftime('%Y%m%d-%H%M%S')}",
                provenance=[
                    Provenance(
                        source=f"bead:{decision['id']}", locator="Robert's answer", seen=now.date()
                    )
                ],
                privacy=Privacy.internal,
            ),
            body=f"Question: {decision['question']}\nRobert: {answer}",
            labels=["kind:request", f"role:{role_name}", "privacy:internal", ANSWER_LABEL],
            acceptance=f"{role_name} acts on Robert's answer and closes this bead.",
        )
        return {"delivery": f"bead:{follow_up}" if follow_up else "bead:(planned)"}
    return {"delivery": None}


def decide(
    settings: Settings,
    beads: Beads,
    ident: str,
    *,
    choice: str | None = None,
    text: str | None = None,
    dry_run: bool = True,
    by: str = "robert",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Answer one pending decision (and its duplicates) and route the answer back.

    ``by`` records who answered: ``robert`` by hand, or ``policy:<index>`` when a
    rule in ``decisions.policy`` answered it. A policy answer raises no attention
    event; it appears in the digest line instead.
    """
    now = now or datetime.now(UTC)
    if ident.startswith("sys-"):
        from cube import sysops

        if by != "robert":
            raise DecisionError("system changes cannot be approved by policy")
        action = choice or "modify"
        if action in POSITIVE:
            action = "approve"
        elif action in NEGATIVE:
            action = "deny"
        note = (text or "").removeprefix("modify").strip(" :")
        record = sysops.decide(settings, ident, action, note, dry_run=dry_run)
        if not dry_run:
            if action == "approve":
                record = sysops.execute(settings, ident, dry_run=False)
            try:
                append_inbox(
                    settings.root,
                    load_agent(settings.root, "sysadmin"),
                    f"System bundle {ident}: {record['status']}. {note}",
                    sender="robert",
                )
            except AgentError:
                pass
        return {
            "id": ident,
            "kind": "sysadmin-change",
            "from": "agent:sysadmin",
            "answer": action,
            "status": record["status"],
            "dry_run": dry_run,
            "record": record,
        }
    pending = _unfolded(settings, beads, now)
    decision = pending.get(ident)
    if decision is None:
        raise DecisionError(f"no pending decision {ident!r}")
    _validate(decision, choice, text)
    duplicates = [dup for dup in decision.get("duplicates", []) if dup in pending]
    plan = _decide_one(
        settings, beads, decision, choice=choice, text=text, dry_run=dry_run, by=by, now=now
    )
    plan["duplicates"] = [
        _decide_one(
            settings, beads, pending[dup], choice=choice, text=text, dry_run=dry_run, by=by, now=now
        )["id"]
        for dup in duplicates
    ]
    return plan


def _decide_one(
    settings: Settings,
    beads: Beads,
    decision: dict[str, Any],
    *,
    choice: str | None,
    text: str | None,
    dry_run: bool,
    now: datetime,
    by: str = "robert",
) -> dict[str, Any]:
    state_dir = settings.state_dir()
    ident = str(decision["id"])
    answer = _answer_text(choice, text)
    yes = _positive(choice)
    plan: dict[str, Any] = {
        "id": ident,
        "kind": decision["kind"],
        "source": decision["source"],
        "from": decision["from"],
        "choice": choice,
        "text": text,
        "answer": answer,
        "dry_run": dry_run,
        "by": by,
        "decision": decision,
    }

    kind = str(decision["kind"])
    if kind == "approval":
        plan.update(_route_approval(settings, ident, yes, answer, dry_run=dry_run))
    elif kind == "permission":
        plan.update(
            _route_permission(settings, beads, decision, yes, answer, dry_run=dry_run, now=now)
        )
    elif kind == "recruit":
        plan.update(_route_recruit(settings, beads, decision, yes, answer, dry_run=dry_run))
    else:
        plan.update(
            _route_bead_answer(settings, beads, decision, choice, answer, dry_run=dry_run, now=now)
        )

    if not dry_run:
        # Recorded only once the answer was routed, so a routing failure leaves no
        # ledger line claiming a decision was answered.
        plan["recorded"] = _record(state_dir, decision, choice, text, now, by)
        acknowledge(state_dir, f"att-{ident}", reason=f"answered: {answer}", now=now)
    if not dry_run and by == "robert":
        # A policy answer is not news: it goes in the digest, not on the attention list.
        append_event(
            state_dir,
            make_event(
                "attention",
                source="decisions",
                title=f"Robert answered {ident}: {answer}",
                bead=decision["context"].get("bead"),
                data={
                    "kind": "answered",
                    "decision": ident,
                    "choice": choice,
                    "to": decision["from"],
                },
            ),
        )
    plan["acknowledged"] = f"att-{ident}"
    return plan


def _route_approval(
    settings: Settings, ident: str, yes: bool | None, answer: str, *, dry_run: bool
) -> dict[str, Any]:
    if yes is None:
        raise DecisionError("an outbound approval needs --choice approve or --choice reject")
    if dry_run:
        return {
            "route": "approval",
            "plan": f"cube {'approve' if yes else 'reject'} {ident}",
        }
    store = ApprovalStore(settings.state_dir())
    try:
        approval = store.decide(
            ident, approve=yes, by="robert", reason=None if yes else (answer or "rejected")
        )
    except ApprovalError as exc:
        raise DecisionError(str(exc)) from exc
    return {"route": "approval", "result": _approval_result(approval, yes)}


def _route_permission(
    settings: Settings,
    beads: Beads,
    decision: dict[str, Any],
    yes: bool | None,
    answer: str,
    *,
    dry_run: bool,
    now: datetime,
) -> dict[str, Any]:
    if yes is None:
        raise DecisionError("a permission needs --choice yes or --choice no")
    ident = str(decision["id"])
    bead = beads.show(ident) if beads.available() else {}
    description = str(bead.get("description") or "")
    labels = bead_labels(bead) or []
    out: dict[str, Any] = {"route": "permission", "grant": None}
    if LAPTOP_READ_LABEL in labels:
        # Robert, 2026-09-08 (ADR-0027): a laptop read outside the readable
        # directories. Yes keeps the request open, marked approved, for the
        # liaison's next tick; no closes it with his words.
        if yes:
            beads.add_labels(ident, [APPROVED_LABEL])
            beads.remove_labels(ident, [NEEDS_ROBERT_LABEL])
            beads.comment(
                ident, f"Robert approved this laptop read{f': {answer}' if answer else ''}"
            )
            out.update({"approved": ident, "closed": None, "labels": [APPROVED_LABEL]})
        else:
            beads.close(ident, f"robert: no{f' ({answer})' if answer else ''}")
            out["closed"] = ident
        return out
    if yes and "resource:approval" in labels:
        agent_name = label_value(labels, "agent:")
        step_title, needs = _resource_needs(str(decision["title"]), description)
        if agent_name:
            if dry_run:
                out["grant"] = {"agent": agent_name, "step_title": step_title, "needs": needs}
            else:
                out["grant"] = add_grant(
                    grants_path(settings, agent_name),
                    step_title=step_title,
                    needs=needs,
                    now=now,
                )
                out["grant"]["agent"] = agent_name
    beads.close(ident, f"robert: {'yes' if yes else 'no'}{f' ({answer})' if answer else ''}")
    out["closed"] = ident
    return out


def _route_recruit(
    settings: Settings,
    beads: Beads,
    decision: dict[str, Any],
    yes: bool | None,
    answer: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    from cube.pipeline import recruit

    if yes is None:
        raise DecisionError("a recruitment request needs --choice yes or --choice no")
    ident = str(decision["id"])
    epic = decision["context"].get("epic")
    if not epic:
        raise DecisionError(f"{ident} has no goal: label naming its pipeline epic")
    bead = beads.show(ident) if beads.available() else {}
    member, role_name = _recruit_member(settings, str(bead.get("description") or ""))
    why = answer or ("Robert approved this request in the cockpit.")
    if not yes:
        why = answer or "Robert declined this request in the cockpit."
    result = recruit(
        settings,
        beads,
        str(epic),
        member=member,
        role_name=role_name,
        why=why,
        deny=not yes,
        dry_run=dry_run,
    )
    return {"route": "recruit", "member": member, "result": result}


def _route_bead_answer(
    settings: Settings,
    beads: Beads,
    decision: dict[str, Any],
    choice: str | None,
    answer: str,
    *,
    dry_run: bool,
    now: datetime,
) -> dict[str, Any]:
    ident = str(decision["id"])
    beads.comment(ident, f"Robert: {answer}")
    out: dict[str, Any] = {"route": str(decision["kind"]), "commented": ident}
    if decision["kind"] == "proposal" and _positive(choice):
        beads.add_labels(ident, ["approved:robert"])
        out["labels"] = ["approved:robert"]
        out["closed"] = None
    else:
        beads.close(ident, f"robert: {answer}")
        out["closed"] = ident
    out.update(_deliver_to_asker(settings, beads, decision, answer, dry_run=dry_run, now=now))
    return out


# --- policy: the answers Robert would give anyway ----------------------------

# Decision kinds that are a free-text or multiple-choice question to Robert.
QUESTION_KINDS = {"question"}
# Approval kinds that reach a person; answering one automatically is never allowed.
OUTBOUND_APPROVAL_KINDS = {"email", "mattermost_dm", "mattermost_channel", "github", "portal"}
# Robert, 2026-09-08 (ADR-0027): a message to Robert himself is not contact with a
# person (doctrine 3 is about everyone else); the policy may approve it.
ROBERT_RECIPIENTS = {
    "robert",
    "robert-hoehndorf",
    "roberthoehndorf",
    "robert.hoehndorf",
    "robert.hoehndorf@kaust.edu.sa",
}


def is_robert(recipient: str | None) -> bool:
    """True when RECIPIENT (person id, handle or address) is Robert."""
    if not recipient:
        return False
    value = str(recipient).strip().lower().lstrip("@")
    return value in ROBERT_RECIPIENTS


def options_for_rule_kind(kind: str) -> list[str]:
    """The answers a policy rule may give for one decision kind (empty: free text)."""
    if kind in {"permission", "recruit"}:
        return list(YES_NO)
    if kind == "approval":
        return list(APPROVE_REJECT)
    if kind in {"proposal", "finding", "conflict"}:
        return list(ACCEPT_REJECT_FREE)
    return []


def decision_guards(settings: Settings, decision: dict[str, Any], *, now: datetime) -> list[str]:
    """Which `never_automatic` guards this decision trips, in `DECISION_GUARDS` order."""
    context = decision.get("context") or {}
    labels = [str(item) for item in (context.get("labels") or [])]
    kind = str(decision.get("kind") or "")
    approval_kind = context.get("approval_kind")
    guards: set[str] = set()
    if approval_kind in OUTBOUND_APPROVAL_KINDS and not is_robert(context.get("recipient")):
        guards.add("outbound")
    if "people" in labels or "kind:people" in labels:
        guards.add("people")
    if "integrity" in labels:
        guards.add("integrity")
    if kind == "conflict" or "kind:conflict" in labels:
        guards.add("conflict")
    if kind in QUESTION_KINDS:
        guards.add("question")
    if context.get("deletes"):
        guards.add("deletion")
    if not within_budget(settings, float(context.get("spend_usd") or 0.0), now=now):
        guards.add("spend_over_budget")
    return [guard for guard in DECISION_GUARDS if guard in guards]


def within_budget(
    settings: Settings, spend_usd: float = 0.0, *, now: datetime | None = None
) -> bool:
    """True when today's and this week's spend, plus SPEND_USD, stay under the ceilings."""
    from cube.router import BudgetLedger  # noqa: PLC0415 - avoid a config/router import cycle

    ledger = BudgetLedger(settings.state_dir(), settings)
    daily_cap = settings.budget.daily_total_usd
    weekly_cap = settings.budget.weekly_total_usd
    today = ledger.spend_today(now)
    week = ledger.spend_window(7, now)
    spent_today = max(float(today["cost_usd"]), float(today["equivalent_usd"]))
    spent_week = max(float(week["cost_usd"]), float(week["equivalent_usd"]))
    if daily_cap is not None and daily_cap > 0 and spent_today + spend_usd > daily_cap:
        return False
    return not (weekly_cap is not None and weekly_cap > 0 and spent_week + spend_usd > weekly_cap)


def _matches(
    settings: Settings, rule: DecisionRule, decision: dict[str, Any], now: datetime
) -> bool:
    """Every key the rule declares must hold; keys it leaves out are not looked at."""
    if rule.kind != str(decision.get("kind") or ""):
        return False
    match = rule.match
    context = decision.get("context") or {}
    labels = [str(item) for item in (context.get("labels") or [])]
    if match.resource_class and context.get("resource_class") not in match.resource_class:
        return False
    if match.within_budget is not None:
        spend = float(context.get("spend_usd") or 0.0)
        if within_budget(settings, spend, now=now) is not match.within_budget:
            return False
    if match.member_kind and context.get("member_kind") not in match.member_kind:
        return False
    if match.asker and str(decision.get("from") or "") not in match.asker:
        return False
    if match.title_prefix and not str(decision.get("title") or "").startswith(match.title_prefix):
        return False
    if match.approval_kind and context.get("approval_kind") not in match.approval_kind:
        return False
    if match.target_within:
        targets = [str(item) for item in (context.get("targets") or [])]
        if not targets or not all(
            any(target.startswith(prefix) for prefix in match.target_within) for target in targets
        ):
            return False
    if match.labels_all and not set(match.labels_all) <= set(labels):
        return False
    if match.names_system is not None and bool(context.get("system")) is not match.names_system:
        return False
    if match.recipient:
        recipient = context.get("recipient")
        wanted = {item.lower() for item in match.recipient}
        if "robert" in wanted and is_robert(recipient):
            pass
        elif str(recipient or "").lower() not in wanted:
            return False
    return True


def policy_preview(
    settings: Settings, decision: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any] | None:
    """The rule that would answer this decision at the next tick, or None."""
    now = now or datetime.now(UTC)
    guards = decision_guards(settings, decision, now=now)
    blocked = [g for g in guards if g in settings.decisions.never_automatic]
    if blocked:
        return None
    for index, rule in enumerate(settings.decisions.policy):
        if _matches(settings, rule, decision, now):
            return {
                "rule": index,
                "by": f"policy:{index}",
                "kind": rule.kind,
                "answer": rule.answer,
                "note": rule.note,
            }
    return None


def apply_policy(
    settings: Settings,
    beads: Beads | None = None,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Answer every pending decision a policy rule covers; leave the rest for Robert.

    Rules are tried in order and the first match wins. A decision under one of the
    `never_automatic` guards (outbound, people, integrity, conflict, question,
    deletion, spend over budget) is never answered here, whatever the rules say.
    """
    now = now or datetime.now(UTC)
    if dry_run and beads is not None:
        beads.dry_run = True
    out: list[dict[str, Any]] = []
    for decision in pending_decisions(settings, beads, now=now):
        ident = str(decision["id"])
        preview = policy_preview(settings, decision, now=now)
        row: dict[str, Any] = {
            "id": ident,
            "kind": decision["kind"],
            "from": decision["from"],
            "title": decision["title"],
            "answered": False,
            "policy": preview,
            "guards": decision_guards(settings, decision, now=now),
        }
        if preview is None or beads is None:
            out.append(row)
            continue
        try:
            plan = decide(
                settings,
                beads,
                ident,
                choice=str(preview["answer"]),
                text=f"policy: {preview['note']}",
                dry_run=dry_run,
                by=str(preview["by"]),
                now=now,
            )
        except (DecisionError, BeadsError) as exc:
            row["error"] = str(exc)
            out.append(row)
            continue
        row["answered"] = True
        row["answer"] = preview["answer"]
        row["note"] = preview["note"]
        row["plan"] = plan.get("route")
        out.append(row)
    return out


def _policy_digest_item(row: dict[str, Any]) -> str:
    note = str(row.get("text") or "").removeprefix("policy: ")
    return f"{row.get('id')} {row.get('choice') or ''} ({note})".strip()


def policy_digest_lines(state_dir: Path, day: date) -> list[str]:
    """One line for the brief: what the policy answered on DAY, with ids and notes."""
    rows = [
        row
        for row in decisions_log(state_dir)
        if str(row.get("by") or "").startswith("policy:")
        and str(row.get("ts") or "").startswith(day.isoformat())
    ]
    if not rows:
        return []
    items = ", ".join(_policy_digest_item(row) for row in rows)
    return ["## Policy", "", f"- Policy answered {len(rows)} decisions: {items}"]


# --- Mattermost: announce to hermes-ws, answer from a reply -------------------
#
# Robert, 2026-09-07: "can needs:robert run through the agent that has access to
# Mattermost, so I can approve (or not) on Mattermost?" The decisions patrol
# leaves one message per new pending decision in hermes-ws's inbox; the Hermes
# outbox cron posts unread inbox lines to Robert's DM (ADR-0020). Robert replies
# in the DM; hermes-ws runs `cube decide --reply "<his words>" --apply`, which
# parses the id and the answer below and routes it like any `cube decide`.
# Identity is the gateway's MATTERMOST_ALLOWED_USERS allowlist: only Robert's
# messages reach hermes-ws, so an answer from the DM is his.

MATTERMOST_AGENT = "hermes-ws"
ANNOUNCED_FILE = "decisions-announced.json"


def announced_path(settings: Settings) -> Path:
    return settings.state_dir() / "agents" / MATTERMOST_AGENT / ANNOUNCED_FILE


def _load_announced(settings: Settings) -> dict[str, str]:
    path = announced_path(settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save_announced(settings: Settings, data: dict[str, str]) -> None:
    path = announced_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def decision_message(item: dict[str, Any]) -> str:
    """One Mattermost message for a pending decision: what, from whom, how to answer."""
    ident = str(item["id"])
    options = [str(o) for o in item.get("options") or []]
    days = int(item.get("age") or 0) // 86400  # `age` is seconds since it was asked
    when = "today" if days == 0 else f"{days} day(s) old"
    head = f"Decision {ident} ({item.get('kind')} from {item.get('from')}, {when}): {item['title']}"
    body = str(item.get("summary") or "").strip()
    if options and options != FREE:
        how = " or ".join(f'"{ident} {o}"' for o in options if o != "free")
        if "free" in options:
            how += f' or "{ident}: <your words>"'
    else:
        how = f'"{ident}: <your answer>"'
    lines = [head]
    if body:
        lines.append(body if item.get("kind") == "sysadmin-change" else body[:600])
    lines.append(f"Reply {how}")
    return "\n".join(lines)


def announce_pending(
    settings: Settings,
    beads: Beads | None,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Leave one inbox message for hermes-ws per pending decision not announced yet.

    A decision is announced once; when it is no longer pending it leaves the
    announced set, so a reopened one is announced again. Without a hermes-ws
    agent on this host nothing is written.
    """
    from cube.agents import AgentError, append_inbox, load_agent  # noqa: PLC0415

    now = now or datetime.now(UTC)
    try:
        agent = load_agent(settings.root, MATTERMOST_AGENT, validate_role=False)
    except AgentError:
        return []
    if agent.host != settings.host:
        return []
    pending = pending_decisions(settings, beads, now=now)
    announced = _load_announced(settings)
    if settings.fleet_enabled:
        from cube.resources import load_limits

        last = announced.get("_last_batch")
        if (
            last
            and (now - datetime.fromisoformat(last)).total_seconds()
            < load_limits(settings).decision_digest_hours * 3600
        ):
            return []
    live = {str(item["id"]) for item in pending}
    rows: list[dict[str, Any]] = []
    for item in pending:
        ident = str(item["id"])
        if ident in announced:
            continue
        text = decision_message(item)
        rows.append({"id": ident, "kind": item.get("kind"), "text": text, "dry_run": dry_run})
        if not dry_run and not settings.fleet_enabled:
            append_inbox(settings.root, agent, text, sender="cube")
            announced[ident] = now.isoformat(timespec="seconds")
    if settings.fleet_enabled and rows:
        # One digest, bounded to one complete decision bundle at a minimum.
        chosen: list[dict[str, Any]] = []
        size = 0
        for row in rows:
            if chosen and size + len(row["text"]) > 12000:
                break
            chosen.append(row)
            size += len(row["text"]) + 2
        rows = chosen
        if not dry_run:
            append_inbox(
                settings.root,
                agent,
                "Decisions for your next review. Approve, deny, or request a modification.\n\n"
                + "\n\n".join(row["text"] for row in rows),
                sender="cube",
            )
            for row in rows:
                announced[row["id"]] = now.isoformat(timespec="seconds")
            announced["_last_batch"] = now.isoformat(timespec="seconds")
    if not dry_run:
        _save_announced(
            settings, {k: v for k, v in announced.items() if k in live or k == "_last_batch"}
        )
    return rows


_REPLY_ID = re.compile(
    r"\b(cube-[a-z0-9]+(?:\.[0-9]+)*|apr-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}|sys-[0-9a-f]{64})\b", re.I
)
_TRAILING_PUNCT = " \t\r\n:,.;!-"


def parse_reply(text: str, pending: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Robert's DM reply -> {id, choice, text}.

    Accepted shapes: ``<id> approve``, ``approve <id>``, ``<id>: some words``,
    ``yes <id>``. The id must be a pending decision; a word that is one of its
    options (or a synonym: yes/approve/accept, no/reject/deny) is the choice,
    anything else is free text.
    """
    match = _REPLY_ID.search(text or "")
    if not match:
        raise DecisionError("no decision id in the reply")
    ident = match.group(1)
    decision = pending.get(ident) or next(
        (item for key, item in pending.items() if key.lower() == ident.lower()), None
    )
    if decision is None:
        raise DecisionError(f"{ident} is not a pending decision")
    ident = str(decision["id"])
    rest = (text[: match.start()] + " " + text[match.end() :]).strip(_TRAILING_PUNCT)
    options = [str(o) for o in decision.get("options") or []]
    word = rest.strip().lower()
    if word and options and options != FREE:
        if word in options:
            return {"id": ident, "choice": word, "text": None}
        positive = _positive(word)
        if positive is True:
            yes = next((o for o in options if o in POSITIVE), None)
            if yes:
                return {"id": ident, "choice": yes, "text": None}
        if positive is False:
            no = next((o for o in options if o in NEGATIVE), None)
            if no:
                return {"id": ident, "choice": no, "text": None}
    if not rest:
        raise DecisionError(f"{ident}: say what to do, for example '{ident} approve'")
    if options and options != FREE and "free" not in options:
        raise DecisionError(f"{ident}: answer with one of {', '.join(options)}")
    return {"id": ident, "choice": None, "text": rest}


def decide_from_reply(
    settings: Settings,
    beads: Beads,
    text: str,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Answer the decision Robert's Mattermost reply names."""
    now = now or datetime.now(UTC)
    if settings.fleet_enabled and text.strip().lower().startswith("limits set "):
        from cube.resources import update_limits

        parts = text.strip().split()
        if len(parts) != 4:
            raise DecisionError("use: limits set <name> <number>")
        try:
            value = json.loads(parts[3])
            change = update_limits(
                settings, {parts[2]: value}, f"Robert Mattermost reply: {text}", dry_run=dry_run
            )
        except ValueError as exc:
            raise DecisionError(str(exc)) from exc
        return {
            "id": "fleet-limits",
            "kind": "limits",
            "from": "hermes-ws",
            "answer": text,
            "change": change,
            "dry_run": dry_run,
        }
    pending = _unfolded(settings, beads, now)
    parsed = parse_reply(text, pending)
    plan = decide(
        settings,
        beads,
        parsed["id"],
        choice=parsed["choice"],
        text=parsed["text"],
        dry_run=dry_run,
        now=now,
    )
    plan["reply"] = text
    return plan
