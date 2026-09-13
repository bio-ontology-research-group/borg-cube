"""Literature-led independent work inside centrally reserved research time."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from cube.agents import Agent, append_inbox, load_agent
from cube.beads import Beads
from cube.config import Settings
from cube.goals import goal_header
from cube.model import BeadHeader, Provenance


def is_researcher(agent: Agent) -> bool:
    return agent.name != "liaison" and (
        agent.kind == "expert" or agent.name in {"research-software", "grants"}
    )


def literature_handoffs(settings: Settings, records: list[dict[str, str]]) -> None:
    grouped: dict[str, list[str]] = {}
    for record in records:
        grouped.setdefault(record["agent"], []).append(
            f"{record['identifier']}: {record['note']} Source: {record['source']}"
        )
    for name, lines in grouped.items():
        append_inbox(
            settings.root,
            load_agent(settings.root, name),
            "Literature in your scope:\n"
            + "\n".join(dict.fromkeys(lines))
            + "\nSelect reproducible results that advance your charter and active goals. "
            "Read the paper and methods, reproduce within central limits, and document "
            "code, environment, commands, data provenance, measured results and differences "
            "in borg-cube-fleet. Negative results also count. Ask a peer to review. "
            "Routine research needs no Robert approval.",
            sender="agent:literature",
        )


def exploration_step(
    settings: Settings,
    ledger: Beads,
    agent: Agent,
    issues: list[dict[str, Any]],
    now: datetime,
    *,
    dry_run: bool,
) -> dict[str, Any] | None:
    if agent.name == "grants":
        from cube.grants import grant_step

        return grant_step(settings, ledger, agent, issues, now, dry_run=dry_run)
    if agent.name.startswith("twin-"):
        from cube.student.twins import twin_step

        return twin_step(settings, ledger, agent, issues, now, dry_run=dry_run)
    goals = [
        row
        for row in issues
        if row.get("status") not in {"closed", "done"}
        and (header := goal_header(row)) is not None
        and header.status == "active"
    ]
    if not goals:
        return None
    from cube.resources import load_limits

    interval = max(1, load_limits(settings).autonomous_interval_hours * 3600)
    window = int(now.timestamp() // interval)
    xid = f"research:{agent.name}:{window}"
    existing = next((row for row in issues if xid in str(row.get("description", ""))), None)
    if existing and existing.get("status") in {"closed", "done"}:
        return None
    goal_ids = [str(g["id"]) for g in goals]
    body = (
        f"Advance your charter ({agent.charter}) against active goals {', '.join(goal_ids)}. "
        "Choose only a goal that fits your expertise. Use the literature agent's reading list "
        "to identify one tractable result to reproduce, or continue an existing experiment. "
        "Check related beads and published fleet work first to avoid duplicate experiments. "
        "Read the original methods. Record the hypothesis, baseline, dataset/license, pinned "
        "environment, commands, seeds, metrics, compute needs and stopping criterion. "
        "Implement and test autonomously; submit cluster work with cube fleet submit. "
        "Never run experiments on login nodes. Respect cube fleet limits. Document code and "
        "all measured outcomes, including failed reproduction, in borg-cube-fleet. "
        "Ask another researcher to review substantive findings. If no goal fits, record why "
        "and notify the coordinator; do not invent relevance or ask Robert for routine choices."
    )
    ident = str(existing["id"]) if existing else None
    if ident is None and not dry_run:
        ident = ledger.create(
            f"Independent research: {agent.title}",
            header=BeadHeader(
                xid=xid,
                provenance=[
                    Provenance(source=str(agent.charter)),
                    *[Provenance(source="bead", locator=g) for g in goal_ids],
                ],
            ),
            body=body,
            labels=[
                "kind:experiment",
                "stage:design",
                f"agent:{agent.name}",
                "research:autonomous",
            ],
            acceptance=(
                "Reproducible evidence and fleet documentation, or an evidenced stop decision."
            ),
        )
    return {
        "title": "Independent literature-led research",
        "bead": ident,
        "needs": {"compute_target": "ws"},
        "prompt_text": body,
        "autonomous": True,
        "key": hashlib.sha256(xid.encode()).hexdigest()[:12],
    }
