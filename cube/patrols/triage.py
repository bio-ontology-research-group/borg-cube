"""Triage patrol: Robert sees decisions, not a queue (ADR-0019).

Robert, 2026-09-07: 140 ready beads carried `needs:robert` findings about disk
percentages, sandbox permissions and stale deadlines. None of them is a decision.
This patrol runs every fifteen minutes over the open beads and applies the rules
in ``cube.yaml`` ``triage.rules`` in order, first match wins:

- ``route``: the bead becomes the named agent's work (``agent:<name>``), loses
  ``needs:robert``, and a later bead from the same asker with the same subject is
  closed as a duplicate.
- ``close``: informational, closed with the rule's note.
- ``deliver``: a ``Robert answered`` bead for a role goes to the inbox of the
  agent that plays the role and is closed.
- ``defer``: keeps the bead but drops ``needs:robert``.

Built in, before the rules: an advisory proposal the policy already accepted is
closed, and only the newest of the coordinator's daily goal-review proposals stays
open. Questions, conflicts, approvals and anything no rule names stay Robert's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from cube.agents import AgentError, append_inbox, load_all_agents
from cube.beads import Beads, BeadsError
from cube.config import Settings, TriageRule
from cube.engine.context import bead_labels, label_value, title_key
from cube.patrols.base import Finding, PatrolReport, register
from cube.systems import names_system

ROUTED = "triage:routed"
DEFERRED = "triage:deferred"
ROUTED_TWICE = "triage:routed-twice"
NEEDS_ROBERT = "needs:robert"
ADVISORY_PROPOSAL = ("kind:proposal", "approved:robert", "review-item")
COORDINATOR_REVIEW = "Review coordinator goal decomposition and assignments"


def asker_of(labels: list[str]) -> str:
    for prefix in ("agent:", "from:", "role:"):
        value = label_value(labels, prefix)
        if value:
            return value
    return ""


def _age_days(bead: dict[str, Any], now: datetime) -> int:
    raw = bead.get("created_at") or bead.get("created")
    try:
        created = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return 0
    created = created if created.tzinfo else created.replace(tzinfo=UTC)
    return max(0, (now - created).days)


def matches(
    rule: TriageRule,
    bead: dict[str, Any],
    *,
    now: datetime,
    systems: list[str] | None = None,
) -> bool:
    labels = bead_labels(bead)
    match = rule.match
    if match.kind and label_value(labels, "kind:") != match.kind:
        return False
    if match.asker and asker_of(labels) not in match.asker:
        return False
    if match.src and label_value(labels, "src:") not in match.src:
        return False
    if match.title_regex and not re.search(
        match.title_regex, str(bead.get("title") or ""), re.IGNORECASE
    ):
        return False
    if match.labels_all and not set(match.labels_all) <= set(labels):
        return False
    if match.labels_none and set(match.labels_none) & set(labels):
        return False
    if match.priority_min is not None and int(bead.get("priority") or 2) < match.priority_min:
        return False
    if match.age_days_min is not None and _age_days(bead, now) < match.age_days_min:
        return False
    if match.needs_robert is not None and (NEEDS_ROBERT in labels) is not match.needs_robert:
        return False
    if match.names_system is not None:
        named = names_system(
            systems or (), str(bead.get("title") or ""), str(bead.get("description") or "")
        )
        if bool(named) is not match.names_system:
            return False
    return True


def agent_for_role(settings: Settings, role: str) -> str | None:
    """The one agent that plays ROLE, else the coordinator, who brokers the group."""
    agents, _ = load_all_agents(settings.root)
    named = [name for name, agent in agents.items() if agent.role == role and name != "liaison"]
    if role == "group-leader" or len(named) != 1:
        return "coordinator" if "coordinator" in agents else None
    return named[0]


@dataclass
class TriagePatrol:
    name: str = "triage"
    now: datetime | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)

    def _act(
        self,
        ledger: Beads,
        report: PatrolReport,
        bead: dict[str, Any],
        *,
        action: str,
        note: str,
        rule: str,
        dry_run: bool,
        labels_add: list[str] | None = None,
        labels_remove: list[str] | None = None,
        close_reason: str | None = None,
    ) -> None:
        bead_id = str(bead.get("id") or "")
        row = {
            "bead": bead_id,
            "title": str(bead.get("title") or "")[:80],
            "action": action,
            "rule": rule,
            "note": note,
        }
        try:
            if not dry_run:
                if labels_add:
                    ledger.add_labels(bead_id, labels_add)
                if labels_remove:
                    present = [x for x in labels_remove if x in bead_labels(bead)]
                    if present:
                        ledger.remove_labels(bead_id, present)
                ledger.comment(bead_id, f"[triage] {action} ({rule}): {note}")
                if close_reason:
                    ledger.close(bead_id, close_reason)
        except BeadsError as exc:
            row["error"] = str(exc)
        self.actions.append(row)
        report.findings.append(
            Finding(
                f"triage:{bead_id}",
                f"{action} {bead_id}: {note}",
                "info",
                source=f"cube.yaml triage.rules[{rule}]",
            )
        )

    def _deliver(
        self,
        settings: Settings,
        ledger: Beads,
        report: PatrolReport,
        bead: dict[str, Any],
        *,
        rule: str,
        note: str,
        dry_run: bool,
    ) -> None:
        labels = bead_labels(bead)
        role = label_value(labels, "role:") or ""
        target = label_value(labels, "agent:") or agent_for_role(settings, role)
        if target is None:
            return
        agents, _ = load_all_agents(settings.root)
        agent = agents.get(target)
        if agent is None:
            return
        if agent.host != settings.host:
            return  # its own host's worker plays it (the laptop liaison)
        body = str(bead.get("description") or "").strip()
        text = f"{bead.get('title')}\n\n{body}"[:4000]
        try:
            if not dry_run:
                append_inbox(settings.root, agent, text, sender="robert")
        except (AgentError, OSError) as exc:
            report.warnings.append(f"inbox {target}: {exc}")
            return
        self._act(
            ledger,
            report,
            bead,
            action="deliver",
            note=f"{note} (inbox of agent:{target})",
            rule=rule,
            dry_run=dry_run,
            close_reason=f"triage: delivered to agent:{target}'s inbox",
        )

    def _hygiene(
        self, ledger: Beads, report: PatrolReport, issues: list[dict[str, Any]], dry_run: bool
    ) -> set[str]:
        """Accepted advisory proposals close; the coordinator's daily review dedupes."""
        done: set[str] = set()
        reviews = sorted(
            (b for b in issues if str(b.get("title") or "") == COORDINATOR_REVIEW),
            key=lambda b: str(b.get("created_at") or ""),
        )
        for bead in reviews[:-1]:
            self._act(
                ledger,
                report,
                bead,
                action="close",
                note="superseded by the newer daily review",
                rule="hygiene",
                dry_run=dry_run,
                close_reason="triage: superseded by the newer coordinator review",
            )
            done.add(str(bead.get("id")))
        for bead in issues:
            bead_id = str(bead.get("id"))
            if bead_id in done:
                continue
            if set(ADVISORY_PROPOSAL) <= set(bead_labels(bead)):
                self._act(
                    ledger,
                    report,
                    bead,
                    action="close",
                    note="advisory proposal accepted by policy; nothing left to decide",
                    rule="hygiene",
                    dry_run=dry_run,
                    close_reason="triage: accepted by policy, advisory only",
                )
                done.add(bead_id)
        return done

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        now = self.now or datetime.now(UTC)
        report = PatrolReport(self.name, today, dry_run)
        ledger = beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=dry_run)
        self.actions = []
        issues = [
            bead
            for bead in ledger.list_issues("--status", "open")
            if str(bead.get("status") or "open") == "open"
        ]
        done = self._hygiene(ledger, report, issues, dry_run)
        routed_keys: dict[tuple[str, str], str] = {}
        for bead in issues:
            labels = bead_labels(bead)
            if ROUTED in labels:
                routed_keys[(asker_of(labels), title_key(str(bead.get("title") or "")))] = str(
                    bead.get("id")
                )
        for bead in sorted(issues, key=lambda b: str(b.get("created_at") or "")):
            bead_id = str(bead.get("id"))
            if bead_id in done:
                continue
            labels = bead_labels(bead)
            for index, rule in enumerate(settings.triage.rules):
                if not matches(rule, bead, now=now, systems=settings.decisions.systems):
                    continue
                rule_name = f"{index}:{rule.name}"
                if rule.action == "route":
                    key = (asker_of(labels), title_key(str(bead.get("title") or "")))
                    first = routed_keys.get(key)
                    if first and first != bead_id:
                        self._act(
                            ledger,
                            report,
                            bead,
                            action="close",
                            note=f"duplicate of {first}",
                            rule=rule_name,
                            dry_run=dry_run,
                            close_reason=f"triage: duplicate of {first}",
                        )
                    elif ROUTED not in labels:
                        routed_keys[key] = bead_id
                        self._act(
                            ledger,
                            report,
                            bead,
                            action="route",
                            note=f"{rule.note} (to {rule.to})",
                            rule=rule_name,
                            dry_run=dry_run,
                            labels_add=[str(rule.to), ROUTED],
                            labels_remove=[NEEDS_ROBERT],
                        )
                    elif NEEDS_ROBERT in labels and ROUTED_TWICE not in labels:
                        # Robert, 2026-09-08 (ADR-0027): the agent put needs:robert
                        # back on a routed bead (cube-b09l, cube-rowz sat pending for
                        # a day). Route it once more; a second insistence stands.
                        self._act(
                            ledger,
                            report,
                            bead,
                            action="route",
                            note=f"{rule.note} (to {rule.to}, again; a third ask stays)",
                            rule=rule_name,
                            dry_run=dry_run,
                            labels_add=[str(rule.to), ROUTED_TWICE],
                            labels_remove=[NEEDS_ROBERT],
                        )
                elif rule.action == "close":
                    self._act(
                        ledger,
                        report,
                        bead,
                        action="close",
                        note=rule.note,
                        rule=rule_name,
                        dry_run=dry_run,
                        close_reason=f"triage: {rule.note}",
                    )
                elif rule.action == "deliver":
                    self._deliver(
                        settings,
                        ledger,
                        report,
                        bead,
                        rule=rule_name,
                        note=rule.note,
                        dry_run=dry_run,
                    )
                elif rule.action == "defer" and NEEDS_ROBERT in labels:
                    self._act(
                        ledger,
                        report,
                        bead,
                        action="defer",
                        note=rule.note,
                        rule=rule_name,
                        dry_run=dry_run,
                        labels_add=[DEFERRED],
                        labels_remove=[NEEDS_ROBERT],
                    )
                break
        counts: dict[str, int] = {}
        for row in self.actions:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        remaining = sum(
            1
            for bead in issues
            if NEEDS_ROBERT in bead_labels(bead)
            and str(bead.get("id")) not in {row["bead"] for row in self.actions}
        )
        report.data["actions"] = list(self.actions)
        report.data["needs_robert_after"] = remaining
        report.summary = (
            ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "nothing to triage"
        ) + f"; {remaining} bead(s) still need Robert"
        return report


register(TriagePatrol, "triage")
