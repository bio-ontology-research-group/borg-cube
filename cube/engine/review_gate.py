"""Review gate: nothing closes without a stronger-tier review (doctrine 2, ADR-0005)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cube.beads import Beads
from cube.engine.context import bead_labels, label_value
from cube.model import BeadHeader, Privacy, Provenance, Tier
from cube.roles import Role

LABEL_APPROVED = "review:approved"
LABEL_REVISE = "review:revise"
LABEL_REJECTED = "review:rejected"
LABEL_PENDING = "review:pending"
VERDICTS = ("approve", "revise", "reject")


def is_review_bead(bead: dict[str, Any]) -> bool:
    return "kind:review" in bead_labels(bead)


def reviewed_bead(review: dict[str, Any]) -> str | None:
    return label_value(bead_labels(review), "reviews:")


def reviewer_role(review: dict[str, Any]) -> str | None:
    return label_value(bead_labels(review), "role:")


def review_satisfied(bead: dict[str, Any]) -> bool:
    return LABEL_APPROVED in bead_labels(bead)


def create_review_bead(
    beads: Beads,
    original_id: str,
    original: dict[str, Any],
    role: Role,
    *,
    summary: str,
    run_id: str,
    privacy: Privacy = Privacy.internal,
    now: datetime | None = None,
) -> str | None:
    """Create a blocking review; student supervision stays on the local tier."""
    reviewer = role.review_required_by
    if not reviewer:
        return None
    student_review = (
        role.name in {"student-researcher", "grant-writer"} and reviewer == "student-reviewer"
    )
    identity_labels: list[str] = []
    tier = Tier.plan
    if student_review:
        privacy = Privacy.local_only
        tier = Tier.local
        original_labels = bead_labels(original)
        identity_labels = [
            label
            for label in original_labels
            if label.startswith(("person:", "twin:")) and label != "twin:milestone"
        ]
        producer_agent = label_value(original_labels, "agent:")
        if producer_agent:
            identity_labels.append(f"producer-agent:{producer_agent}")
        identity_labels.extend(["agent:student-supervisor", "privacy:local-only"])
    now = now or datetime.now(UTC)
    header = BeadHeader(
        xid=f"review:{original_id}:{run_id}",
        provenance=[Provenance(source=f"runs/{run_id}", locator="result.json", seen=now.date())],
        privacy=privacy,
    )
    title = f"Review {original_id}: {str(original.get('title') or '')[:70]}".rstrip(": ")
    body = (
        f"Review the work of role `{role.name}` (run {run_id}) on bead {original_id}.\n\n"
        f"Producer summary:\n{summary}\n\n"
        "Verdict: approve | revise | reject, with file:line evidence. "
        + (
            "A separate senior reviewer runs locally. Keep source material and feedback local."
            if student_review
            else "The review runs at tier plan (never weaker than the producer)."
        )
    )
    review_id = beads.create(
        title,
        header=header,
        body=body,
        type_="task",
        priority=int(original.get("priority") or 2),
        labels=[
            "kind:review",
            f"tier:{tier.value}",
            f"role:{reviewer}",
            f"reviews:{original_id}",
            f"producer:{role.name}",
            "stage:review",
            *identity_labels,
        ],
        parent=str(original.get("parent")) if original.get("parent") else None,
    )
    beads.add_labels(original_id, [LABEL_PENDING])
    if review_id:
        beads.dep(original_id, review_id, "blocks")
    return review_id or "(dry-run review bead)"


def apply_verdict(
    beads: Beads,
    review_id: str,
    review: dict[str, Any],
    *,
    verdict: str,
    summary: str,
    by: str,
    run_id: str,
    privacy: Privacy = Privacy.internal,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply a verdict; routine student rejection stays with the local supervisor."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    now = now or datetime.now(UTC)
    original_id = reviewed_bead(review)
    out: dict[str, Any] = {"verdict": verdict, "review": review_id, "original": original_id}
    note = f"[{by} {run_id}] verdict {verdict}: {summary}"
    beads.comment(review_id, note)
    if original_id:
        beads.comment(original_id, note)
    labels = bead_labels(review)
    student_review = label_value(labels, "producer:") in {
        "student-researcher",
        "grant-writer",
    } and (reviewer_role(review) == "student-reviewer")
    if student_review:
        privacy = Privacy.local_only
    if "pipeline-stage:gate" in labels:
        gate_number = label_value(labels, "gate:") or "1"
        epic_id = label_value(labels, "goal:")
        if verdict == "approve":
            beads.add_labels(review_id, [LABEL_APPROVED])
            beads.close(review_id, f"approve ({run_id})")
            out["closed"] = [review_id]
        elif verdict == "revise":
            beads.add_labels(review_id, [LABEL_REVISE])
            followups: list[str] = []
            if epic_id:
                experiments = [
                    item
                    for item in beads.list_issues("--all")
                    if f"goal:{epic_id}" in bead_labels(item)
                    and "pipeline-stage:experiments" in bead_labels(item)
                    and not any(label.startswith("revises:") for label in bead_labels(item))
                ]
                for experiment in experiments:
                    experiment_id = str(experiment.get("id") or "")
                    xid = f"revise:{experiment_id}:{run_id}"
                    existing = beads.find_by_xid(xid)
                    pipeline_follow = str(existing.get("id") or "") if existing else ""
                    if not pipeline_follow:
                        producer = label_value(labels, "producer:") or "programmer"
                        pipeline_follow = (
                            beads.create(
                                f"Revise {experiment_id}: {summary[:60]}",
                                header=BeadHeader(
                                    xid=xid,
                                    provenance=[
                                        Provenance(
                                            source=f"runs/{run_id}",
                                            locator="result.json",
                                            seen=now.date(),
                                        )
                                    ],
                                    privacy=privacy,
                                ),
                                body=(
                                    f"Reviewer {by} asked for revision after pipeline gate "
                                    f"{gate_number} of {experiment_id}:\n\n{summary}"
                                ),
                                labels=[
                                    f"goal:{epic_id}",
                                    "pipeline-stage:experiments",
                                    f"privacy:{privacy.value}",
                                    "kind:experiment",
                                    "stage:implement",
                                    f"role:{producer}",
                                    f"revises:{experiment_id}",
                                    f"after-gate:{gate_number}",
                                ],
                                parent=epic_id,
                                acceptance=str(
                                    experiment.get("acceptance_criteria")
                                    or "The requested revision is implemented and its checks pass."
                                ),
                            )
                            or ""
                        )
                    if pipeline_follow:
                        followups.append(pipeline_follow)
            beads.close(review_id, f"revise ({run_id})")
            out["follow_ups"] = followups
        else:
            beads.add_labels(review_id, [LABEL_REJECTED, "needs:robert"])
            out["needs_robert"] = True
        return out
    if verdict == "approve":
        # The original depends on this review. Respect Beads' dependency gate;
        # never force-close an original past another unresolved blocker.
        beads.close(review_id, f"approve ({run_id})")
        if original_id:
            beads.add_labels(original_id, [LABEL_APPROVED])
            beads.close(original_id, f"review approved by {by} ({run_id})")
        out["closed"] = [x for x in (original_id, review_id) if x]
    elif verdict == "revise":
        follow: str | None = None
        if original_id:
            beads.add_labels(original_id, [LABEL_REVISE])
            header = BeadHeader(
                xid=f"revise:{original_id}:{run_id}",
                provenance=[
                    Provenance(source=f"runs/{run_id}", locator="result.json", seen=now.date())
                ],
                privacy=privacy,
            )
            producer = label_value(bead_labels(review), "producer:") or "programmer"
            follow_labels = ["stage:implement", f"role:{producer}", f"revises:{original_id}"]
            if student_review:
                follow_labels.extend(
                    label
                    for label in labels
                    if label.startswith(("person:", "twin:")) and label != "twin:milestone"
                )
                producer_agent = label_value(labels, "producer-agent:")
                if producer_agent:
                    follow_labels.append(f"agent:{producer_agent}")
                follow_labels.extend(["privacy:local-only", "tier:local"])
            follow = beads.create(
                f"Revise {original_id}: {summary[:60]}",
                header=header,
                body=f"Reviewer {by} asked for revision of {original_id}:\n\n{summary}",
                labels=follow_labels,
                parent=str(review.get("parent")) if review.get("parent") else None,
            )
            if follow:
                if student_review:
                    beads.add_labels(original_id, [f"superseded-by:{follow}"])
                    beads.close(review_id, f"revise ({run_id})")
                    beads.close(
                        original_id, f"revision required; superseded by {follow} ({run_id})"
                    )
                    out["closed"] = [original_id, review_id]
                else:
                    beads.dep(original_id, follow, "blocks")
        if not (student_review and follow):
            beads.close(review_id, f"revise ({run_id})")
        out["follow_up"] = follow or "(dry-run follow-up bead)"
    else:
        if student_review:
            if original_id:
                beads.add_labels(original_id, [LABEL_REJECTED])
            beads.add_labels(review_id, [LABEL_REJECTED, "agent:student-supervisor"])
            beads.comment(
                review_id,
                "The local supervisor stopped this research line, not approved it. "
                "Read this negative finding before choosing a refined research milestone. "
                "A routine scientific rejection does not require Robert's decision.",
            )
            beads.close(review_id, f"scientific stop ({run_id})")
            if original_id:
                beads.close(original_id, f"scientific stop by {by}: {summary[:120]} ({run_id})")
            out["closed"] = [x for x in (original_id, review_id) if x]
            out["stopped"] = True
            return out
        if original_id:
            beads.add_labels(original_id, [LABEL_REJECTED, "needs:robert"])
        beads.add_labels(review_id, ["needs:robert"])
        out["needs_robert"] = True
    return out
