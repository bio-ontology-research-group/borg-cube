"""Bounded standing grant work on the existing research workday and ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cube.agents import Agent
from cube.beads import Beads
from cube.config import Settings
from cube.engine.context import bead_labels
from cube.model import BeadHeader, Privacy, Provenance


def grant_step(
    settings: Settings,
    ledger: Beads,
    agent: Agent,
    issues: list[dict[str, Any]],
    now: datetime,
    *,
    dry_run: bool,
) -> dict[str, Any] | None:
    """One unfinished milestone; daily proposal work and weekly discovery."""
    own = [row for row in issues if "agent:grants" in bead_labels(row)]
    if any(row.get("status") not in {"closed", "done"} for row in own):
        return None
    year, week, _ = now.isocalendar()
    candidates = [
        (f"proposal:{now.date().isoformat()}", "Improve active proposals, starting with CRG2026"),
        (f"discovery:{year}-W{week:02}", "Find and rank suitable funding opportunities"),
    ]
    done = {label for row in own for label in bead_labels(row)}
    selected = next((item for item in candidates if f"grant-cycle:{item[0]}" not in done), None)
    if selected is None:
        return None
    cycle, title = selected
    body = (
        f"{title}. Follow {agent.charter}. Read previous artifacts in "
        "state/agents/grants/work/ and related beads before choosing one small deliverable. "
        f"Find project source references through {settings.dirs['pa']} and "
        f"{settings.dirs['org']}, and the research KG at {settings.dirs['rkg']}. "
        "Do not assume CRG2026's directory, status or call from its name. Missing laptop "
        "sources need one deduplicated liaison request, never a ws pull. For a proposal "
        "milestone, audit actual call criteria and improve the highest-priority supported "
        "gap; for discovery, verify official current calls and maintain the deduplicated "
        "ranked register. Coordinate bounded expert requests through linked work beads. "
        "Preserve local-only privacy for all private context and derived drafts. Return "
        "artifact paths for independent review. No external contact or submission. "
        "If essential sources are absent, record the blocker and work on available public "
        "funding evidence, without inventing proposal contents. Routine progress belongs "
        "on the ledger, not in separate Mattermost messages."
    )
    ident = None
    if not dry_run:
        ident = ledger.create(
            title,
            header=BeadHeader(
                xid=f"grants:{cycle}",
                privacy=Privacy.local_only,
                provenance=[Provenance(source=str(agent.charter))],
            ),
            body=body,
            labels=[
                "agent:grants",
                "role:grant-writer",
                "kind:experiment",
                "stage:implement",
                "tier:local",
                "privacy:local-only",
                f"grant-cycle:{cycle}",
            ],
            acceptance="A source-backed funding or proposal artifact, independently reviewed.",
        )
    return {
        "title": title,
        "bead": ident,
        "needs": {"compute_target": "ws"},
        "prompt_text": body,
        "autonomous": True,
    }
