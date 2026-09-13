"""A hello-world drill that exercises the whole standing-agent fleet.

The drill is deliberately content-free.  It proves the machinery: the
coordinator reaches every agent, every agent answers the coordinator, one pair
of experts talks to each other without the coordinator in the middle, and the
coordinator reports back to Robert on the bead.  ``status`` never invokes a
model: it reads the bead and the inbox files and says which route is missing.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from cube.agents import Agent, load_all_agents, read_inbox
from cube.beads import Beads
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Provenance

#: Agents that never take part in the default drill.  The coordinator drives it
#: and the liaison lives on the laptop, where the drill inboxes are not written.
DRILL_EXCLUDED = ("coordinator", "liaison")
COORDINATOR = "coordinator"
#: The agent-to-agent route.  Two experts whose remits genuinely touch.
ASK_AGENT = "ontology"
ANSWER_AGENT = "machine-learning"
RELAY_MARKER = "relays"
DRILL_SOURCE = "cube fleet drill"
DRILL_LOCATOR = "Robert, 2026-09-05: sample task exercising the whole fleet"
DRILL_RULES = (
    "This is a drill: no research content is needed, keep every line under 200 "
    "characters, do not create other beads."
)
AGENTS_LINE = "Agents in this drill: "
CLOSED_STATUS = ("closed", "done")


def drill_xid(day: date) -> str:
    return f"drill:{day.isoformat()}"


def drill_title(day: date) -> str:
    return f"Fleet drill {day.isoformat()}: hello world"


def drill_labels(day: date) -> list[str]:
    return ["kind:task", "agent:coordinator", f"drill:{day.isoformat()}", "privacy:internal"]


def fleet_agents(settings: Settings, requested: list[str] | None = None) -> list[str]:
    """The drill roster: the requested names, or every loaded agent but the drivers."""
    found, _errors = load_all_agents(settings.root)
    if requested:
        missing = [name for name in requested if name not in found]
        if missing:
            raise ValueError("no such agent: " + ", ".join(sorted(missing)))
        return list(dict.fromkeys(requested))
    return [name for name in sorted(found) if name not in DRILL_EXCLUDED]


def _agent(settings: Settings, name: str) -> Agent | None:
    found, _errors = load_all_agents(settings.root)
    return found.get(name)


def _inbox(settings: Settings, name: str) -> list[dict[str, Any]]:
    agent = _agent(settings, name)
    if agent is None:
        return []
    return read_inbox(settings.root, agent)


def drill_body(reference: str, agents: list[str]) -> str:
    """The script the coordinator follows, with the bead id already filled in."""
    tells = "\n".join(
        f"   cube agent tell {name} 'drill {reference}: reply to agent:coordinator with one "
        "line: your name, your topics, and one active project from your charter' "
        "--from agent:coordinator --apply"
        for name in agents
    )
    return "\n".join(
        [
            f"Hello-world drill for the whole standing-agent fleet, bead {reference}.",
            "",
            DRILL_RULES,
            "",
            AGENTS_LINE + ", ".join(agents),
            "",
            "1. Coordinator: send one tell to every agent in the drill.",
            "",
            tells,
            "",
            "2. Every agent: reply to the coordinator with one line.",
            "",
            f"   cube agent tell coordinator 'drill {reference}: <name>: <one line>' "
            "--from agent:<name> --apply",
            "",
            "3. Route two, agent to agent, without the coordinator in the middle.",
            "",
            f"   cube agent tell {ANSWER_AGENT} 'drill {reference}: which embedding method "
            f"would you pair with an OWL ontology and why, one line' --from agent:{ASK_AGENT} "
            "--apply",
            "",
            f"   {ANSWER_AGENT} answers {ASK_AGENT} with the same command:",
            "",
            f"   cube agent tell {ASK_AGENT} 'drill {reference}: <answer>' "
            f"--from agent:{ANSWER_AGENT} --apply",
            "",
            f"   {ASK_AGENT} then forwards the answer to the coordinator:",
            "",
            f"   cube agent tell coordinator 'drill {reference}: {ASK_AGENT} {RELAY_MARKER} "
            f"{ANSWER_AGENT}: <answer>' --from agent:{ASK_AGENT} --apply",
            "",
            "4. Coordinator: once every reply is in your inbox, post one comment on this bead",
            "   listing each agent's line and the relayed answer, then close the bead.",
            "",
            f"   bd comment {reference} '<one line per agent, then the relayed answer>'",
            f"   bd close {reference} --reason 'drill complete'",
        ]
    )


def start(
    settings: Settings,
    beads: Beads,
    *,
    agents: list[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Create (or reuse) today's drill bead.  Idempotent on the xid."""
    day = today or date.today()
    roster = fleet_agents(settings, agents)
    xid = drill_xid(day)
    existing = beads.find_by_xid(xid)
    if existing and str(existing.get("status") or "open") not in CLOSED_STATUS:
        return {
            "bead": existing.get("id"),
            "xid": xid,
            "date": day.isoformat(),
            "agents": roster,
            "labels": list(existing.get("labels") or drill_labels(day)),
            "reused": True,
            "dry_run": beads.dry_run,
            "body": str(existing.get("description") or ""),
            "commands": beads.logged_commands(),
        }
    header = BeadHeader(
        xid=xid,
        provenance=[Provenance(source=DRILL_SOURCE, locator=DRILL_LOCATOR)],
        deadline=day,
        privacy=Privacy.internal,
    )
    labels = drill_labels(day)
    bead_id = beads.create(
        drill_title(day),
        header=header,
        body=drill_body(xid, roster),
        priority=2,
        labels=labels,
        acceptance="Every agent replied, the agent-to-agent answer was relayed, "
        "and the coordinator summarised the drill on the bead.",
    )
    body = drill_body(bead_id or xid, roster)
    if bead_id:
        # The script quotes the bead id, which only exists after the create.
        beads.update_description(bead_id, header.render() + "\n" + body)
    return {
        "bead": bead_id,
        "xid": xid,
        "date": day.isoformat(),
        "agents": roster,
        "labels": labels,
        "reused": False,
        "dry_run": beads.dry_run,
        "body": body,
        "commands": beads.logged_commands(),
    }


def _matches(text: str, reference: str | None, day: str) -> bool:
    lowered = str(text or "").lower()
    if reference and f"drill {reference}".lower() in lowered:
        return True
    return f"drill:{day}" in lowered


def _first(
    rows: list[dict[str, Any]], sender: str, reference: str | None, day: str, *, contains: str = ""
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("from") != sender:
            continue
        text = str(row.get("text") or "")
        if contains and contains.lower() not in text.lower():
            continue
        if _matches(text, reference, day):
            return row
    return None


def _roster_from_body(description: str) -> list[str]:
    match = re.search(rf"(?m)^{re.escape(AGENTS_LINE)}(.+)$", description or "")
    if not match:
        return []
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


def _comments(bead: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for row in bead.get("comments") or []:
        out.append(str(row.get("text") if isinstance(row, dict) else row))
    return out


def status(
    settings: Settings,
    beads: Beads,
    *,
    bead: str | None = None,
    day: date | None = None,
) -> dict[str, Any]:
    """Deterministic drill report.  Reads the bead and every inbox; runs no model."""
    when = day or date.today()
    record: dict[str, Any] = {}
    if bead:
        record = beads.show(bead)
    else:
        record = beads.find_by_xid(drill_xid(when)) or {}
    bead_id = str(record.get("id")) if record.get("id") else None
    description = str(record.get("description") or "")
    if record:
        header = BeadHeader.parse(description)
        if header and header.xid.startswith("drill:"):
            when = date.fromisoformat(header.xid.split(":", 1)[1])
    day_text = when.isoformat()
    roster = _roster_from_body(description) or fleet_agents(settings)

    coordinator_inbox = _inbox(settings, COORDINATOR)
    rows: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    if not record:
        missing.append(f"no drill bead for {day_text}")
    for name in roster:
        told = _first(_inbox(settings, name), f"agent:{COORDINATOR}", bead_id, day_text)
        replied = _first(coordinator_inbox, f"agent:{name}", bead_id, day_text)
        rows[name] = {
            "told": told is not None,
            "told_ts": (told or {}).get("ts"),
            "replied": replied is not None,
            "replied_ts": (replied or {}).get("ts"),
        }
        if told is None:
            missing.append(f"coordinator has not told {name}")
        if replied is None:
            missing.append(f"{name} has not replied to the coordinator")

    asked = _first(_inbox(settings, ANSWER_AGENT), f"agent:{ASK_AGENT}", bead_id, day_text)
    answered = _first(_inbox(settings, ASK_AGENT), f"agent:{ANSWER_AGENT}", bead_id, day_text)
    relayed = _first(
        coordinator_inbox, f"agent:{ASK_AGENT}", bead_id, day_text, contains=RELAY_MARKER
    )
    if asked is None:
        missing.append(f"{ASK_AGENT} has not asked {ANSWER_AGENT}")
    if answered is None:
        missing.append(f"{ANSWER_AGENT} has not answered {ASK_AGENT}")
    if relayed is None:
        missing.append(f"{ASK_AGENT} has not relayed the answer to the coordinator")

    comments = _comments(record)
    summary = any(
        "drill" in text.lower() and all(name in text for name in roster) for text in comments
    )
    closed = str(record.get("status") or "open") in CLOSED_STATUS
    if not summary:
        missing.append(f"no drill summary comment on {bead_id or day_text}")
    if not closed:
        missing.append(f"{bead_id or day_text} is not closed")

    told_count = sum(1 for row in rows.values() if row["told"])
    replied_count = sum(1 for row in rows.values() if row["replied"])
    return {
        "bead": bead_id,
        "date": day_text,
        "agents": rows,
        "routes": {
            "coordinator_to_agent": {"n": told_count, "of": len(roster)},
            "agent_to_coordinator": {"n": replied_count, "of": len(roster)},
            "agent_to_agent": {
                "asked": asked is not None,
                "answered": answered is not None,
                "relayed": relayed is not None,
            },
            "agent_to_robert": {"summary_comment": summary, "closed": closed},
        },
        "complete": not missing,
        "missing": missing,
    }


def status_text(data: dict[str, Any]) -> str:
    def tick(value: bool) -> str:
        return "x" if value else "."

    lines = [f"drill {data['bead'] or '(no bead)'} {data['date']}"]
    for name, row in data["agents"].items():
        lines.append(f"[{tick(row['told'])}] told [{tick(row['replied'])}] replied  {name}")
    routes = data["routes"]
    lines.append(
        f"coordinator to agent: {routes['coordinator_to_agent']['n']}"
        f"/{routes['coordinator_to_agent']['of']}; agent to coordinator: "
        f"{routes['agent_to_coordinator']['n']}/{routes['agent_to_coordinator']['of']}"
    )
    a2a = routes["agent_to_agent"]
    lines.append(
        f"agent to agent: asked [{tick(a2a['asked'])}] answered [{tick(a2a['answered'])}] "
        f"relayed [{tick(a2a['relayed'])}]"
    )
    a2r = routes["agent_to_robert"]
    lines.append(
        f"agent to Robert: comment [{tick(a2r['summary_comment'])}] closed [{tick(a2r['closed'])}]"
    )
    lines.append("complete" if data["complete"] else "missing:")
    lines += [f"- {item}" for item in data["missing"]]
    return "\n".join(lines)
