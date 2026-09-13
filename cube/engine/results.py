"""Apply a validated RunResult: comments, labels, review gate, escalations, approvals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.approvals import APPROVAL_KINDS, ApprovalStore, intent_from_file
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.engine import review_gate
from cube.engine.context import bead_labels, label_value, title_key
from cube.model import BeadHeader, Escalation, Privacy, Provenance, RunResult
from cube.roles import Role

OUTBOUND_ARTIFACT_KINDS = {"outbound", *APPROVAL_KINDS}


@dataclass
class Applied:
    comments: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    review_bead: str | None = None
    verdict: dict[str, Any] | None = None
    escalations: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pipeline: dict[str, Any] | None = None
    artifacts: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Relative artifact paths a run may materialise outside its own run directory.
# Everything else (roles, brain, agents, people.yaml, ~) needs an approval.
INLINE_ARTIFACT_PREFIXES = ("state/", "runs/", "briefings/")


def write_inline_artifacts(root: Path, run_dir: Path, result: RunResult) -> dict[str, list[str]]:
    """Save every artifact that carries ``content``.

    The copy under the run directory is provenance and always written. A relative
    path under ``state/``, ``runs/`` or ``briefings/`` is written there too so the
    reader the artifact names (Robert, the cockpit, a patrol) finds it; any other
    target is noted and left to the approval path. Absolute paths never.
    """
    written: list[str] = []
    skipped: list[str] = []
    for art in result.artifacts:
        if art.content is None:
            continue
        raw = Path(art.path)
        name = raw.name or f"{art.kind}.md"
        run_copy = run_dir / name
        run_dir.mkdir(parents=True, exist_ok=True)
        run_copy.write_text(art.content, encoding="utf-8")
        written.append(str(run_copy))
        if raw.is_absolute() or ".." in raw.parts:
            skipped.append(f"artifact {art.path}: outside the repo; kept under the run dir only")
            continue
        posix = raw.as_posix()
        if posix.startswith(INLINE_ARTIFACT_PREFIXES) and not posix.startswith(str(run_dir)):
            target = root / raw
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(art.content, encoding="utf-8")
            written.append(str(target))
        elif not (root / raw).resolve().is_relative_to(run_dir.resolve()):
            skipped.append(
                f"artifact {art.path}: not under state/, runs/ or briefings/; "
                "kept under the run dir only"
            )
    return {"written": written, "skipped": skipped}


def _artifact_path(root: Path, run_dir: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    for base in (run_dir, root):
        if (base / p).exists():
            return base / p
    return run_dir / p


# --- escalation routing -----------------------------------------------------

# The bead kind label each escalation kind files under.
ESCALATION_KIND_LABEL = {
    "decision": "kind:finding",
    "permission": "kind:request",
    "integrity": "kind:finding",
    "people": "kind:finding",
    "conflict": "kind:conflict",
    "blocked": "kind:finding",
    "note": "kind:note",
}
# Extra labels that let the policy and the cockpit see what must stay human.
ESCALATION_EXTRA_LABEL = {"integrity": "integrity", "people": "people"}
# A blocked escalation whose text names one of these is the sysadmin's, not the
# coordinator's; everything else goes to the coordinator to unblock.
SYSADMIN_WORDS = ("tool", "path", "network", "permission", "binary", "install", "credential")


def blocked_owner(esc: Escalation) -> str:
    """Who fixes a `blocked` escalation: the sysadmin for tooling, else the coordinator."""
    text = f"{esc.summary} {esc.condition}".lower()
    return "role:sysadmin" if any(word in text for word in SYSADMIN_WORDS) else "agent:coordinator"


ROBERT_KINDS = ("people", "integrity")
"""Escalation kinds that are Robert's whatever the flag: a person's data is
privacy-critical, suspected fabrication is what pa ADR-0002 exists for."""

COORDINATOR = "agent:coordinator"


def _owner_label(to: str) -> str:
    return to if to.startswith("agent:") else f"role:{to}"


def escalation_labels(esc: Escalation, role_name: str) -> list[str]:
    """Labels for one escalation bead. Robert sees only the critical ones.

    Robert, 2026-09-07: fewer escalations. Only a security-critical (a change to a
    running system, spend over budget, outbound contact) or privacy-critical (a
    person, secrets, local-only data) matter reaches ``needs:robert``; the run
    says so with ``critical``. ``people`` and ``integrity`` are always his. A
    ``decision``, ``permission`` or ``conflict`` without the flag is the
    coordinator's to settle; ``blocked`` is the group's; a ``note`` closes itself.
    """
    to = esc.to.strip().lower()
    to_robert = to in ("robert", "needs:robert", "")
    labels = [ESCALATION_KIND_LABEL.get(esc.kind, "kind:finding"), f"from:{role_name}"]
    if esc.kind == "blocked":
        # The group handles a tooling or input gap; Robert is never asked for one.
        labels.append("blocked")
        labels.append(_owner_label(to) if not to_robert else blocked_owner(esc))
        return labels
    if esc.kind == "note":
        # A note is closed on arrival and never labelled needs:robert.
        if not to_robert:
            labels.append(_owner_label(to))
        return labels
    if not to_robert:
        labels.append(_owner_label(to))
        if esc.critical:
            labels.append(f"critical:{esc.critical}")
        return labels
    if esc.kind in ROBERT_KINDS or esc.critical:
        labels.append("needs:robert")
        extra = ESCALATION_EXTRA_LABEL.get(esc.kind)
        if extra:
            labels.append(extra)
        if esc.critical:
            labels.append(f"critical:{esc.critical}")
        return labels
    labels.append(COORDINATOR)
    return labels


def escalation_xid(role_name: str, esc: Escalation) -> str:
    """One bead per role and subject: the numbers of the day never make a new one."""
    return f"esc:{role_name}:{title_key(esc.condition) or 'escalation'}"


def open_escalation(beads: Beads, xid: str) -> dict[str, Any] | None:
    """The open bead already filed for this escalation subject, if any."""
    try:
        issues = beads.list_issues("--all")
    except BeadsError:
        return None
    for issue in issues:
        ref = str(issue.get("external_ref") or "")
        if ref != xid and not ref.startswith(xid + ":"):
            continue
        if str(issue.get("status") or "open") in {"closed", "done"}:
            continue
        return issue
    return None


# Beads whose result is a diagnosis, an answer or information: filing it is the
# work, and the review gate (doctrine 2) is for designs and implementations.
NO_REVIEW_KINDS = frozenset(
    {
        "finding",
        "incident",
        "request",
        "question",
        "note",
        "conflict",
        "proposal",
        "approval",
        "reading-list",
        "meeting-note",
    }
)


def has_parent(bead: dict[str, Any]) -> bool:
    """Child work: Beads copies the parent's labels onto it, so labels alone lie."""
    labels = bead_labels(bead)
    return (
        bool(bead.get("parent"))
        or "." in str(bead.get("id") or "")
        or any(label.startswith(("goal:", "pipeline-stage:", "reviews:")) for label in labels)
    )


def is_goal_bead(bead: dict[str, Any]) -> bool:
    """A goal epic: the unit Robert asked for, closed only when its child work is.

    Stage and child beads inherit ``kind:goal`` from their epic; they are not goals.
    """
    if has_parent(bead):
        return False
    return "kind:goal" in bead_labels(bead) or str(bead.get("issue_type") or "") == "epic"


def is_intake_child(bead: dict[str, Any]) -> bool:
    """Child work created under a Mattermost goal intake.

    Beads copies the parent's labels onto a child, so every child of an intake
    carries ``intake:goal`` and ``kind:request`` although it is a design or
    implementation task. On 2026-09-09 that shortcut closed cube-r1n.1 and
    cube-r1n.2 as "result filed" with no drop and no repository (cube-in1).
    """
    return "intake:goal" in bead_labels(bead) and has_parent(bead)


def closes_without_review(bead: dict[str, Any]) -> bool:
    if is_goal_bead(bead) or is_intake_child(bead):
        return False
    kind = label_value(bead_labels(bead), "kind:")
    return kind in NO_REVIEW_KINDS


DESIGN_ROLES = frozenset({"senior", "group-leader"})
BRIEF_WORDS = ("brief", "spec", "design", "plan")


def _looks_like_brief(kind: str | None, path: str | None) -> bool:
    text = f"{kind or ''} {Path(path or '').name}".lower()
    return any(word in text for word in BRIEF_WORDS)


def open_children(beads: Beads, bead_id: str) -> tuple[int, list[str]]:
    """(child count, open child ids) for a goal; a ledger failure counts as unknown."""
    if not beads.available():
        return 0, []
    try:
        issues = beads.list_issues("--all")
    except BeadsError:
        return 0, []
    children = [
        row
        for row in issues
        if str(row.get("parent") or "") == bead_id
        or str(row.get("id") or "").startswith(bead_id + ".")
        or f"goal:{bead_id}" in bead_labels(row)
    ]
    still_open = [
        str(row.get("id")) for row in children if row.get("status") not in {"closed", "done"}
    ]
    return len(children), still_open


def apply_result(
    settings: Settings,
    beads: Beads,
    role: Role,
    bead_id: str | None,
    bead: dict[str, Any],
    result: RunResult,
    *,
    run_id: str,
    run_dir: Path,
    policy: ContactPolicy,
    store: ApprovalStore,
    privacy: Privacy = Privacy.internal,
    now: datetime | None = None,
    agent: str | None = None,
) -> Applied:
    now = now or datetime.now(UTC)
    applied = Applied()
    if role.name in {"liaison", "sysadmin"}:
        from cube.disclosure import release_text

        # Structured output is an execution surface too. A restricted worker may
        # not write control state, mint approvals, update another bead or send.
        result = result.model_copy(
            update={
                "summary": release_text(result.summary, personal_source=True),
                "artifacts": [
                    art.model_copy(
                        update={
                            "kind": "note",
                            "path": f"report-{i}.md",
                            "content": release_text(art.content, personal_source=True),
                        }
                    )
                    for i, art in enumerate(result.artifacts)
                    if art.content is not None
                ],
                "bead_updates": [
                    upd.model_copy(
                        update={
                            "labels_add": [],
                            "comment": release_text(upd.comment, personal_source=True)
                            if upd.comment
                            else None,
                        }
                    )
                    for upd in result.bead_updates
                    if upd.bead == bead_id
                ],
                "verdict": None,
            }
        )
    tag = f"[{role.name} {run_id}]"
    rel_run = str(run_dir)

    # 0. artifacts returned inline (roles without a Write tool) go to disk first
    applied.artifacts = write_inline_artifacts(settings.root, run_dir, result)
    for note in applied.artifacts.get("skipped", []):
        applied.notes.append(note)

    # 1. summary comment on the primary bead (provenance: the run directory)
    if bead_id:
        text = f"{tag} {result.summary.strip()}\n\nrun: {rel_run}/result.json"
        _safe(beads.comment, bead_id, text, applied=applied, note="summary comment")
        applied.comments.append(bead_id)

    pipeline_closed: set[str] = set()
    pipeline_blocked: set[str] = set()
    if bead_id and any(label.startswith("pipeline-stage:") for label in bead_labels(bead)):
        from cube.pipeline import record_plan_artifacts  # noqa: PLC0415

        try:
            applied.pipeline = record_plan_artifacts(
                settings, bead, run_dir, result, beads=beads, today=now.date()
            )
        except (OSError, ValueError, ImportError) as exc:
            applied.pipeline = {"close": False, "errors": [str(exc)]}
        if applied.pipeline.get("errors"):
            pipeline_blocked.add(bead_id)
            _safe(
                beads.add_labels,
                bead_id,
                ["needs:robert"],
                applied=applied,
                note="pipeline artifact finding",
            )
            findings = "\n".join(str(item) for item in applied.pipeline["errors"])
            _safe(
                beads.comment,
                bead_id,
                f"{tag} pipeline artifact checks failed:\n{findings}",
                applied=applied,
                note="pipeline artifact findings",
            )
            labels = bead_labels(bead)
            epic_id = label_value(labels, "goal:")
            stage = label_value(labels, "pipeline-stage:") or "artifact"
            finding_xid = f"pipe:{epic_id}:{stage}-invalid" if epic_id else ""
            try:
                existing = beads.find_by_xid(finding_xid) if finding_xid else None
                if epic_id and not existing:
                    finding_id = beads.create(
                        f"Pipeline {stage} artifact checks failed",
                        header=BeadHeader(
                            xid=finding_xid,
                            provenance=[
                                Provenance(
                                    source=f"runs/{run_id}",
                                    locator="result.json",
                                    seen=now.date(),
                                )
                            ],
                            privacy=privacy,
                        ),
                        body=findings,
                        priority=1,
                        labels=[
                            "kind:finding",
                            "needs:robert",
                            f"goal:{epic_id}",
                            f"privacy:{privacy.value}",
                        ],
                        parent=epic_id,
                    )
                    if finding_id:
                        applied.escalations.append(finding_id)
            except BeadsError as exc:
                applied.notes.append(f"pipeline finding not filed: {exc}")
        elif applied.pipeline.get("close"):
            _safe(
                beads.close,
                bead_id,
                f"validated pipeline artifacts from {run_id}",
                applied=applied,
                note="pipeline stage close",
            )
            pipeline_closed.add(bead_id)
            applied.closed.append(bead_id)

    # 2. verdicts on review beads
    if result.verdict and bead_id and review_gate.is_review_bead(bead):
        try:
            applied.verdict = review_gate.apply_verdict(
                beads,
                bead_id,
                bead,
                verdict=result.verdict,
                summary=result.summary,
                by=role.name,
                run_id=run_id,
                privacy=privacy,
                now=now,
            )
        except (ValueError, BeadsError) as exc:
            applied.notes.append(f"verdict not applied: {exc}")

    # 3. bead updates
    close_requested: set[str] = set()
    # An explicit ``close: false`` on the run's own bead is a checkpoint: the
    # run says its task is not done, so the implicit "result filed" close below
    # must not override it (cube-r1n.3 and cube-r1n.6 said exactly that on
    # 2026-09-09 and were still parked; cube-in1).
    keep_open: set[str] = set()
    for upd in result.bead_updates:
        target = upd.bead or bead_id
        if not target:
            applied.notes.append("bead_update without bead id skipped")
            continue
        if target == bead_id and not upd.close:
            keep_open.add(target)
        if upd.comment:
            _safe(beads.comment, target, f"{tag} {upd.comment}", applied=applied, note="comment")
            applied.comments.append(target)
        if upd.labels_add:
            labels = [x for x in upd.labels_add if not x.startswith("review:")]
            if labels:
                _safe(beads.add_labels, target, labels, applied=applied, note="labels")
                applied.labels += labels
        if upd.close:
            close_requested.add(target)

    # A run that returns a result on its bead has filed its work: the bead now
    # waits for the review gate (another role) or for Robert, never for the
    # next hourly tick to play it again (Robert, 2026-09-06). Pipeline stages
    # have their own artifact gate; a run that escalated (anything but a note)
    # has handed the next move to whoever the escalation names.
    if (
        bead_id
        and bead_id not in close_requested
        and bead_id not in keep_open
        and bead_id not in pipeline_closed
        and bead_id not in pipeline_blocked
        and not is_goal_bead(bead)
        and not review_gate.is_review_bead(bead)
        and not any(label.startswith("pipeline-stage:") for label in bead_labels(bead))
        and not any(esc.kind != "note" for esc in result.escalations)
    ):
        close_requested.add(bead_id)
        applied.notes.append(f"{bead_id}: result filed; review gate applies")
    elif bead_id and bead_id in keep_open and bead_id not in close_requested:
        applied.notes.append(f"{bead_id}: checkpoint, task stays open")
    elif bead_id and is_goal_bead(bead) and bead_id not in close_requested:
        applied.notes.append(f"{bead_id}: goal stays open until its child work is closed")

    if (
        bead_id
        and bead_id in keep_open
        and bead_id not in close_requested
        and role.name in DESIGN_ROLES
        and "stage:design" in bead_labels(bead)
        and any(_looks_like_brief(art.kind, art.path) for art in result.artifacts)
        and not any(esc.kind != "note" for esc in result.escalations)
    ):
        # The senior wrote the brief and stopped, as its prompt asks. Nothing
        # dispatched a programmer afterwards: cube-r1n.6 and cube-dze.2.1 spent
        # four turns re-verifying their own specs (2026-09-11). Move the bead to
        # the implement stage so the next scheduled turn runs the programmer.
        owner = label_value(bead_labels(bead), "agent:")
        add = ["stage:implement", "role:programmer"] + ([f"designed-by:{owner}"] if owner else [])
        remove = ["stage:design"] + ([f"agent:{owner}"] if owner else [])
        _safe(beads.add_labels, bead_id, add, applied=applied, note="handoff labels")
        _safe(beads.remove_labels, bead_id, remove, applied=applied, note="handoff labels")
        briefs = ", ".join(
            art.path for art in result.artifacts if _looks_like_brief(art.kind, art.path)
        )
        _safe(
            beads.comment,
            bead_id,
            f"{tag} design handoff: brief at {briefs}; the next turn runs role:programmer on it",
            applied=applied,
            note="handoff comment",
        )
        applied.labels += add
        applied.notes.append(f"{bead_id}: design handed to programmer")

    for target in sorted(close_requested):
        if target in pipeline_closed or target in pipeline_blocked:
            continue
        if applied.verdict and target in (applied.verdict.get("closed") or []):
            continue
        target_bead = bead if target == bead_id else _show(beads, target)
        if is_goal_bead(target_bead):
            # A goal is Robert's ask. Planning it is not finishing it: four P1
            # goals were closed after one decomposition turn on 2026-09-09 with
            # no child beads at all (cube-ihu, cube-7hb, cube-dze, cube-up7).
            count, still_open = open_children(beads, target)
            if count == 0:
                applied.notes.append(f"{target}: goal has no child work yet; not closed")
                continue
            if still_open:
                applied.notes.append(
                    f"{target}: goal has open child work ({', '.join(sorted(still_open)[:5])}); "
                    "not closed"
                )
                continue
        if closes_without_review(target_bead):
            # Robert, 2026-09-07: a finding, request or note is done when its
            # answer is on the ledger; reviewing a diagnosis was the queue's
            # main occupation and never a decision.
            _safe(
                beads.close,
                target,
                f"{role.name} {run_id}: result filed, no review for this kind",
                applied=applied,
                note="close",
            )
            applied.closed.append(target)
        elif role.can_close and (
            review_gate.review_satisfied(target_bead) or role.review_required_by is None
        ):
            _safe(
                beads.close,
                target,
                f"{role.name} {run_id}: {result.summary[:120]}",
                applied=applied,
                note="close",
            )
            applied.closed.append(target)
        elif role.review_required_by:
            if review_gate.LABEL_PENDING in bead_labels(target_bead):
                applied.notes.append(f"{target}: review already pending")
                continue
            try:
                applied.review_bead = review_gate.create_review_bead(
                    beads,
                    target,
                    target_bead,
                    role,
                    summary=result.summary,
                    run_id=run_id,
                    privacy=privacy,
                    now=now,
                )
            except BeadsError as exc:
                applied.notes.append(f"review bead not created: {exc}")
        else:
            applied.notes.append(f"{target}: role may not close and has no reviewer; left open")

    # 4. escalations -> beads (Robert, another role, or the group)
    for i, esc in enumerate(result.escalations):
        labels = escalation_labels(esc, role.name)
        if agent and not any(label.startswith("agent:") for label in labels):
            # Robert, 2026-09-07: the answer goes to this agent's inbox, not to a
            # role bead nobody plays (sixteen of those sat in the ready queue).
            labels.append(f"agent:{agent}")
        to_robert = "needs:robert" in labels
        base_xid = escalation_xid(role.name, esc)
        title = f"Escalation from {role.name}: {esc.condition[:60]}"
        body = esc.summary + (f"\n\nbead: {bead_id}" if bead_id else "")
        if esc.kind != "note":
            existing = open_escalation(beads, base_xid)
            if existing:
                # The same subject from the same role is already on the ledger:
                # one comment, no second bead (three beads about one disk on
                # 2026-09-07).
                existing_id = str(existing.get("id"))
                _safe(
                    beads.comment,
                    existing_id,
                    f"{tag} repeated: {esc.summary}",
                    applied=applied,
                    note="escalation repeat",
                )
                applied.notes.append(f"escalation already open as {existing_id}: {title}")
                continue
        header = BeadHeader(
            xid=f"{base_xid}:{run_id}:{i}",
            provenance=[
                Provenance(source=f"runs/{run_id}", locator="result.json", seen=now.date())
            ],
            privacy=privacy,
        )
        try:
            new_id = beads.create(
                title, header=header, body=body, priority=1 if to_robert else 2, labels=labels
            )
            if bead_id and new_id:
                beads.dep(new_id, bead_id, "related")
            if esc.kind == "note" and new_id:
                # Information, not a decision: it is recorded and closed in the same step.
                _safe(beads.comment, new_id, esc.summary, applied=applied, note="note comment")
                _safe(
                    beads.close,
                    new_id,
                    f"{role.name} {run_id}: note, no decision needed",
                    applied=applied,
                    note="note close",
                )
                applied.closed.append(new_id)
            applied.escalations.append(new_id or f"(dry-run) {title}")
        except BeadsError as exc:
            applied.notes.append(f"escalation not filed: {exc}")

    # 5. outbound intents and file changes -> approvals (never sent here)
    for art in result.artifacts:
        if art.kind not in OUTBOUND_ARTIFACT_KINDS:
            continue
        path = _artifact_path(settings.root, run_dir, art.path)
        default_kind = art.kind if art.kind in APPROVAL_KINDS else None
        intent = intent_from_file(path, default_kind=default_kind)
        if intent is None:
            applied.notes.append(f"artifact {art.path}: no valid outbound front matter; ignored")
            continue
        if intent.subject is None and art.summary:
            intent.subject = art.summary
        approval = store.create(
            intent,
            policy=policy,
            created_by=f"{role.name}/{run_id}",
            autonomous_actions=role.autonomous_actions,
            run_id=run_id,
            bead=bead_id,
            now=now,
        )
        applied.approvals.append(approval.id)
        if bead_id:
            _safe(
                beads.comment,
                bead_id,
                f"{tag} approval {approval.id} ({approval.status}): {approval.summary()}",
                applied=applied,
                note="approval comment",
            )
    return applied


def _show(beads: Beads, bead_id: str) -> dict[str, Any]:
    if not beads.available():
        return {"id": bead_id}
    try:
        return beads.show(bead_id)
    except BeadsError:
        return {"id": bead_id}


def _safe(fn: Any, *args: Any, applied: Applied, note: str) -> None:
    try:
        fn(*args)
    except BeadsError as exc:
        applied.notes.append(f"{note} failed: {exc}")
