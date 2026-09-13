"""Mattermost event intake (event-driven, never polled): payloads -> inbox files + beads.

A DM from a student with a live ``mattermost_dm`` grant becomes a ``kind:mentoring`` bead
(privacy local-only; the transcript stays in ``state/events/inbox/<post>.json`` and never
enters the bead). Anything else becomes a content-free ``kind:finding`` "unanswered DM" for
Robert with ``needs:robert``. Both raise an attention event carrying only the permalink.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from cube.beads import Beads
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.model import BeadHeader, Privacy, Provenance, WorkKind
from cube.patrols.base import Finding, PatrolReport, attention_event, register
from cube.sources.mattermost import DEFAULT_BASE_URL, MattermostEvent, parse_event
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import DesiredBead


def inbox_dir(settings: Settings) -> Any:
    return settings.state_dir() / "events" / "inbox"


def resolve_person(ctx: SourceContext, ev: MattermostEvent) -> Person | None:
    user = (ev.user or "").lstrip("@").lower()
    for p in ctx.people:
        if user and p.mattermost and p.mattermost.lower() == user:
            return p
        if ev.user_id and str(p.extra.get("mattermost_id") or "") == ev.user_id:
            return p
    if user:
        for c in ctx.contacts:
            if c.mattermost and c.mattermost.lower() == user:
                return ctx.person_for_ref(c.slug)
    return None


def is_dm(ev: MattermostEvent, payload: dict[str, Any]) -> bool:
    if str(payload.get("channel_type") or payload.get("channelType") or "").upper() == "D":
        return True
    if payload.get("is_dm") is True or payload.get("direct") is True:
        return True
    data = payload.get("data")
    if isinstance(data, dict) and str(data.get("channel_type") or "").upper() == "D":
        return True
    return bool(ev.channel and "__" in ev.channel)


def bead_for(
    ev: MattermostEvent,
    person: Person | None,
    *,
    granted: bool,
    dm: bool,
    today: date,
    inbox_path: str,
) -> DesiredBead:
    xid = f"mm:{ev.post_id}"
    when = ev.created.date().isoformat() if ev.created else today.isoformat()
    provenance = [
        Provenance(
            source="mattermost", locator=f"post {ev.post_id}", permalink=ev.permalink, seen=today
        )
    ]
    labels = ["src:mattermost"]
    if person:
        labels.append(f"person:{person.id}")
    if person and granted and dm:
        return DesiredBead(
            xid=xid,
            title=f"Check-in reply: {person.name} ({when})",
            kind=WorkKind.mentoring,
            labels=[*labels, "checkin", "stage:design"],
            parent_xid=f"program:{person.id}",
            header=BeadHeader(xid=xid, provenance=provenance, privacy=Privacy.local_only),
            body=(
                f"Reply from {person.name} received {when}. The transcript is local-only and "
                f"lives at {inbox_path}; it is never copied into this bead.\n"
                f"Permalink: {ev.permalink}\n"
                "Next: scribe drafts the org entry (:cube:) and Status as of paragraph on the "
                "local tier; written only after cube approve."
            ),
            priority=2,
        )
    who = person.name if person else (ev.user or ev.user_id or "unknown user")
    where = "DM" if dm else f"~{ev.channel or ev.channel_id or '?'}"
    reason = (
        "no mattermost_dm grant; the bot must not answer"
        if person and not granted
        else ("sender not in people.yaml" if person is None else "channel post, not a DM")
    )
    return DesiredBead(
        xid=xid,
        title=f"Unanswered {where} from {who}",
        kind=WorkKind.finding,
        labels=[*labels, "needs:robert", "unanswered-dm"],
        header=BeadHeader(xid=xid, provenance=provenance, privacy=Privacy.local_only),
        body=(
            f"From: {who} ({ev.user_id or '?'}) in {where} on {when}\n"
            f"Routing: Robert answers himself ({reason}).\n"
            f"Permalink: {ev.permalink}\n"
            f"The unclassified message content is local-only at {inbox_path}; it is never "
            "copied into this bead."
        ),
        priority=2,
    )


@dataclass
class MattermostEventsPatrol:
    """Not timer-driven: constructed by ``cube event`` with the payloads to ingest."""

    name: str = "mattermost_events"
    payloads: list[dict[str, Any]] = field(default_factory=list)

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(self.name, today, dry_run)
        ctx = SourceContext(settings, today, github_details=False)
        policy = ContactPolicy(settings.root / "contacts.yaml")
        granted_ids = set(policy.allowed_users("mattermost_dm", today))
        base_url = settings.env.get("MATTERMOST_URL", DEFAULT_BASE_URL)
        inbox = inbox_dir(settings)
        ingested: list[dict[str, Any]] = []
        for payload in self.payloads:
            ev = parse_event(payload, base_url=base_url, team=settings.mattermost.team)
            if ev is None:
                report.findings.append(
                    Finding("mm:unparsed", "payload without a post id skipped", "warn")
                )
                continue
            person = resolve_person(ctx, ev)
            dm = is_dm(ev, payload)
            granted = bool(person and person.id in granted_ids)
            path = inbox / f"{ev.post_id}.json"
            # Enforces CLAUDE.md's privacy-class rule: unclassified message content defaults
            # to local-only, and grades or HR details never enter beads or attention events.
            record = {
                "received": today.isoformat(),
                "privacy": Privacy.local_only.value,
                "event": ev.as_dict(),
                "person": person.id if person else None,
                "dm": dm,
                "granted": granted,
                "routing": "mentoring" if (person and granted and dm) else "robert",
            }
            if not dry_run:
                inbox.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            bead = bead_for(ev, person, granted=granted, dm=dm, today=today, inbox_path=str(path))
            report.findings.append(bead)
            report.events.append(
                attention_event(
                    self.name,
                    bead.title,
                    body=ev.permalink,
                    xid=bead.xid,
                    data={
                        "permalink": ev.permalink,
                        "person": person.id if person else None,
                        "routing": record["routing"],
                    },
                )
            )
            ingested.append(
                {
                    "received": record["received"],
                    "privacy": record["privacy"],
                    "person": record["person"],
                    "dm": dm,
                    "granted": granted,
                    "routing": record["routing"],
                    "inbox_file": str(path),
                    "xid": bead.xid,
                }
            )
        report.data["ingested"] = ingested
        mentoring = sum(1 for i in ingested if i["routing"] == "mentoring")
        report.summary = (
            f"{len(ingested)} event(s): {mentoring} check-in reply(ies), "
            f"{len(ingested) - mentoring} for Robert"
        )
        return report


register(MattermostEventsPatrol, "mattermost_events")
