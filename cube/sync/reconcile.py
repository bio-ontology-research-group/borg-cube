"""Compare desired beads with what bd holds and apply the difference through Beads."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from cube.beads import Beads, BeadsError
from cube.model import BeadHeader
from cube.sync.derivers import DesiredBead

Op = Literal["create", "update-labels", "close", "conflict", "noop"]

OPEN_STATES = {"open", "in_progress", "blocked", "ready", "hooked", "pinned"}


class Action(BaseModel):
    op: Op
    xid: str
    title: str
    kind: str
    bead_id: str | None = None
    parent_xid: str | None = None
    labels_add: list[str] = Field(default_factory=list)
    reason: str = ""
    deadline: str | None = None
    desired_index: int = Field(default=0, exclude=True)


def bead_status(bead: dict[str, Any]) -> str:
    return str(bead.get("status") or "open").lower()


def bead_labels(bead: dict[str, Any]) -> list[str]:
    labels = bead.get("labels") or []
    out: list[str] = []
    for lab in labels:
        if isinstance(lab, dict):
            out.append(str(lab.get("name") or lab.get("label") or ""))
        else:
            out.append(str(lab))
    return [x for x in out if x]


def index_existing(beads: Beads) -> tuple[dict[str, dict[str, Any]], str | None]:
    """xid -> bead from one ``bd list --all`` call; (empty, warning) if bd is unusable."""
    if not beads.available():
        return {}, f"bd binary {beads.bin!r} not found; treating the ledger as empty"
    try:
        issues = beads.list_issues("--all")
    except BeadsError as exc:
        return {}, f"bd list failed: {exc}; treating the ledger as empty"
    index: dict[str, dict[str, Any]] = {}
    for bead in issues:
        xid = bead.get("external_ref")
        if not xid:
            header = BeadHeader.parse(bead.get("description") or "")
            xid = header.xid if header else None
        if xid and xid not in index:
            index[str(xid)] = bead
    return index, None


def plan(desired: list[DesiredBead], existing: dict[str, dict[str, Any]]) -> list[Action]:
    actions: list[Action] = []
    virtual = {xid: dict(bead) for xid, bead in existing.items()}
    for desired_index, d in enumerate(desired):
        cur = virtual.get(d.xid)
        deadline = d.header.deadline.isoformat() if d.header.deadline else None
        if cur is None:
            if d.closed:
                actions.append(
                    Action(
                        op="noop",
                        xid=d.xid,
                        title=d.title,
                        kind=d.kind.value,
                        reason="already closed at source; never created",
                        desired_index=desired_index,
                    )
                )
                continue
            actions.append(
                Action(
                    op="create",
                    xid=d.xid,
                    title=d.title,
                    kind=d.kind.value,
                    parent_xid=d.parent_xid,
                    labels_add=d.all_labels(),
                    deadline=deadline,
                    reason="missing in ledger",
                    desired_index=desired_index,
                )
            )
            virtual[d.xid] = {"status": "open", "labels": d.all_labels()}
            continue
        bid = str(cur.get("id") or "")
        status = bead_status(cur)
        is_open = status in OPEN_STATES
        if d.closed and is_open:
            actions.append(
                Action(
                    op="close",
                    xid=d.xid,
                    title=d.title,
                    kind=d.kind.value,
                    bead_id=bid,
                    reason=d.close_reason or "closed at source",
                    desired_index=desired_index,
                )
            )
            cur["status"] = "closed"
            continue
        if not d.closed and not is_open:
            actions.append(
                Action(
                    op="conflict",
                    xid=d.xid,
                    title=d.title,
                    kind=d.kind.value,
                    bead_id=bid,
                    reason=f"bead is {status} but the source still lists it as open; not reopening",
                    desired_index=desired_index,
                )
            )
            continue
        have = set(bead_labels(cur))
        missing = [lab for lab in d.all_labels() if lab not in have]
        if missing and is_open:
            actions.append(
                Action(
                    op="update-labels",
                    xid=d.xid,
                    title=d.title,
                    kind=d.kind.value,
                    bead_id=bid,
                    labels_add=missing,
                    reason="labels drifted",
                    desired_index=desired_index,
                )
            )
            cur["labels"] = [*have, *missing]
            continue
        actions.append(
            Action(
                op="noop",
                xid=d.xid,
                title=d.title,
                kind=d.kind.value,
                bead_id=bid,
                reason="up to date",
                desired_index=desired_index,
            )
        )
    return _parents_first(actions, desired)


def _parents_first(actions: list[Action], desired: list[DesiredBead]) -> list[Action]:
    """Order creates so a parent epic precedes its children (needed to pass --parent)."""
    by_xid = {d.xid: d for d in desired}
    depth: dict[str, int] = {}

    def level(xid: str) -> int:
        if xid in depth:
            return depth[xid]
        d = by_xid.get(xid)
        depth[xid] = (
            0 if d is None or not d.parent_xid or d.parent_xid == xid else 1 + level(d.parent_xid)
        )
        return depth[xid]

    order = {"create": 0, "update-labels": 1, "close": 2, "conflict": 3, "noop": 4}
    return sorted(actions, key=lambda a: (order[a.op], level(a.xid) if a.op == "create" else 0))


def apply(
    actions: list[Action],
    desired: list[DesiredBead],
    beads: Beads,
    existing: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the plan through Beads. Honours ``beads.dry_run`` (writes are logged, not run)."""
    ids: dict[str, str] = {xid: str(b.get("id")) for xid, b in existing.items() if b.get("id")}
    results: list[dict[str, Any]] = []
    for a in actions:
        rec: dict[str, Any] = a.model_dump()
        try:
            if a.op == "create":
                d = desired[a.desired_index]
                parent_id = ids.get(d.parent_xid) if d.parent_xid else None
                if d.parent_xid and parent_id is None and not beads.dry_run:
                    rec["note"] = f"parent {d.parent_xid} has no bead id; created without --parent"
                new_id = beads.create(
                    d.title,
                    header=d.header,
                    body=d.body,
                    type_=d.type_,
                    priority=d.priority,
                    labels=d.all_labels(),
                    parent=parent_id,
                )
                if new_id:
                    ids[d.xid] = new_id
                    rec["bead_id"] = new_id
                for dep in d.deps:
                    dep_id = ids.get(dep)
                    if new_id and dep_id:
                        beads.dep(new_id, dep_id, "blocks")
            elif a.op == "update-labels" and (bead_id := a.bead_id or ids.get(a.xid)):
                beads.add_labels(bead_id, a.labels_add)
            elif a.op == "close" and (bead_id := a.bead_id or ids.get(a.xid)):
                beads.close(bead_id, a.reason)
            rec["ok"] = True
        except BeadsError as exc:
            rec["ok"] = False
            rec["error"] = str(exc)
        results.append(rec)
    return results


def summarize(actions: list[Action]) -> dict[str, Any]:
    by_op: dict[str, int] = {}
    by_kind: dict[str, dict[str, int]] = {}
    for a in actions:
        by_op[a.op] = by_op.get(a.op, 0) + 1
        by_kind.setdefault(a.kind, {})
        by_kind[a.kind][a.op] = by_kind[a.kind].get(a.op, 0) + 1
    return {"by_op": by_op, "by_kind": by_kind, "total": len(actions)}
