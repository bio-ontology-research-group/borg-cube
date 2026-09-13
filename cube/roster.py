"""Pure roster fact collection, reconciliation, and people.yaml rendering."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

from cube.sources.org import GroupRoster, match_staff_entry, parse_staff
from cube.sources.rkg import ResearchKg, RosterEntry
from cube.sources.website import WebsiteProfile

SourceName = Literal["staff_org", "website", "roster_md", "kg", "people_yaml"]
SOURCE_NAMES: tuple[SourceName, ...] = (
    "staff_org",
    "website",
    "roster_md",
    "kg",
    "people_yaml",
)


@dataclass(frozen=True)
class RosterPolicy:
    """Configured source precedence, rather than an embedded roster exception."""

    authority: SourceName = "website"
    fields_from: dict[str, tuple[SourceName, ...]] = field(
        default_factory=lambda: {
            "program": ("website", "staff_org"),
            "start": ("staff_org",),
            "org_file": ("people_yaml", "staff_org"),
        }
    )
    membership_exceptions: dict[str, str] = field(default_factory=dict)


def load_roster_policy(path: Path) -> RosterPolicy:
    """Read the roster stanza without widening the global Settings schema."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = data.get("roster") if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    authority = raw.get("authority", "website")
    if authority not in SOURCE_NAMES:
        authority = "website"
    fields: dict[str, tuple[SourceName, ...]] = {}
    for name, sources in (raw.get("fields_from") or {}).items():
        if not isinstance(name, str) or not isinstance(sources, list):
            continue
        valid = tuple(source for source in sources if source in SOURCE_NAMES)
        if valid:
            fields[name] = valid
    exceptions = raw.get("membership_exceptions") or {}
    return RosterPolicy(
        authority=authority,
        fields_from=fields or RosterPolicy().fields_from,
        membership_exceptions={str(k): str(v) for k, v in exceptions.items()}
        if isinstance(exceptions, dict)
        else {},
    )


def slugify(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


@dataclass
class SourceFact:
    source: SourceName
    slug: str
    name: str
    role: str | None = None
    program: str | None = None
    current: bool | None = True
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RosterPerson:
    slug: str
    name: str
    role: str
    program: str | None
    present: dict[SourceName, bool]
    status: str
    conflicts: list[dict[str, Any]]
    membership: Literal["current", "former"] = "former"
    pending: str | None = None
    selected: dict[str, Any] = field(default_factory=dict, repr=False)
    facts: list[SourceFact] = field(default_factory=list, repr=False)
    existing: dict[str, Any] = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "role": self.role,
            "program": self.program,
            "in": dict(self.present),
            "status": self.status,
            "conflicts": self.conflicts,
            "membership": self.membership,
            "pending": self.pending,
        }


@dataclass
class _Identity:
    slug: str
    name: str
    facts: list[SourceFact] = field(default_factory=list)


def _tokens(name: str) -> list[str]:
    normal = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+", normal)


def _same_token(left: str, right: str) -> bool:
    if left == right:
        return True
    return len(left) >= 5 and len(right) >= 5 and left[:5] == right[:5]


def _same_name(left: str, right: str) -> bool:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return False
    if len(a) == 1 or len(b) == 1:
        return _same_token(a[0], b[0])
    return _same_token(a[0], b[0]) and _same_token(a[-1], b[-1])


def _find_identity(identities: list[_Identity], fact: SourceFact) -> _Identity | None:
    exact = [identity for identity in identities if identity.slug == fact.slug]
    if len(exact) == 1:
        return exact[0]
    names = [identity for identity in identities if _same_name(identity.name, fact.name)]
    return names[0] if len(names) == 1 else None


def normalise_role(value: str | None, *, section: str = "") -> str | None:
    low = f"{value or ''} {section}".lower()
    if "student" in low or "phd" in low or re.search(r"\bmsc?\b|\bm\.s", low):
        return "student"
    if "postdoc" in low:
        return "postdoc"
    if "research scientist" in low or "scientist" in low:
        return "research-scientist"
    if "intern" in low:
        return "intern"
    if "visiting" in low or "visitor" in low:
        return "visiting"
    if any(
        word in low
        for word in ("staff", "manager", "specialist", "engineer", "curator", "technician", "pi")
    ):
        return "staff"
    if "alumni" in low or "former member" in low:
        return "alumni"
    return None


def normalise_program(value: str | None, *, position: str = "") -> str | None:
    if not value:
        return None
    low = value.lower()
    if low == "visiting" or "visiting" in position.lower():
        return "visiting"
    degree: str | None = None
    combined = f"{position} {value}".lower()
    if "phd" in combined or "ph.d" in combined:
        degree = "PhD"
    elif "msc" in combined or "m.s" in combined or re.search(r"\bms\b", combined):
        degree = "MS"
    elif value.startswith(("PhD-", "MS-")):
        return value
    if degree is None:
        return value
    if "bioeng" in low:
        return f"{degree}-Bioeng"
    if "computer" in low or re.search(r"\bcs\b", low):
        return f"{degree}-CS"
    if "biosci" in low:
        return f"{degree}-Biosci"
    return degree


def load_people_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def collect_facts(
    staff: GroupRoster,
    website: Iterable[WebsiteProfile],
    roster_md: Iterable[RosterEntry],
    graph: ResearchKg,
    people_data: dict[str, Any],
) -> list[SourceFact]:
    """Collect roster sources, using the KG only to enrich already known identities."""
    facts: list[SourceFact] = []
    for block, is_current in (("people", True), ("former", False)):
        rows = people_data.get(block) or {}
        if not isinstance(rows, dict):
            continue
        for slug, raw in rows.items():
            if not isinstance(raw, dict):
                continue
            facts.append(
                SourceFact(
                    source="people_yaml",
                    slug=str(slug),
                    name=str(raw.get("name") or slug),
                    role=normalise_role(str(raw.get("role") or "")),
                    program=normalise_program(raw.get("program")),
                    current=is_current,
                    data=dict(raw),
                )
            )
    for roster_entry in roster_md:
        facts.append(
            SourceFact(
                source="roster_md",
                slug=roster_entry.slug,
                name=roster_entry.name,
                role=normalise_role(roster_entry.detail, section=roster_entry.section),
                program=roster_entry.program,
            )
        )
    for profile in website:
        profile_role = (
            "pi"
            if profile.group == "principal-investigators"
            else ("visiting-faculty" if "visiting" in profile.title.lower() else profile.role)
        )
        facts.append(
            SourceFact(
                source="website",
                slug=profile.slug,
                name=profile.name,
                role=profile_role,
                program=profile.program,
                data={"program": profile.program, "profile": profile.url},
            )
        )
    staff_entries = parse_staff(staff.path)
    for group_entry in staff.current:
        detail = group_entry.role_text or ""
        notes = match_staff_entry(staff_entries, group_entry.name)
        staff_data: dict[str, Any] = {}
        if notes is not None:
            start = notes.first("start") or notes.first("transfer_phd")
            if start and start.when:
                staff_data["start"] = start.when.isoformat()
            staff_data["milestones"] = [estimate.raw for estimate in notes.estimates]
        facts.append(
            SourceFact(
                source="staff_org",
                slug=slugify(group_entry.name),
                name=group_entry.name,
                role=normalise_role(detail, section=group_entry.section)
                or ("student" if group_entry.section.lower() == "students" else "staff"),
                program=(
                    normalise_program(detail, position=detail)
                    if group_entry.section.lower() == "students"
                    else None
                ),
                data=staff_data,
            )
        )
    for alumnus in staff.alumni:
        facts.append(
            SourceFact(
                source="staff_org",
                slug=slugify(alumnus.name),
                name=alumnus.name,
                role=None,
                current=False,
            )
        )

    identities = _group_facts(facts)
    for person in graph.people:
        probe = SourceFact(source="kg", slug=person.slug, name=person.name)
        identity = _find_identity(identities, probe)
        if identity is None:
            continue
        same_people = [candidate for candidate in graph.people if candidate.slug == person.slug]
        if person is not same_people[0]:
            continue
        current_people = [candidate for candidate in same_people if candidate.is_current]
        chosen = current_people[0] if current_people else same_people[0]
        position = chosen.position or ""
        is_former = "former" in position.lower()
        identity.facts.append(
            SourceFact(
                source="kg",
                slug=chosen.slug,
                name=chosen.name,
                role=normalise_role(position),
                program=normalise_program(chosen.program, position=position),
                current=True if chosen.is_current else (False if is_former else None),
            )
        )
    return [fact for identity in identities for fact in identity.facts]


def _group_facts(facts: Iterable[SourceFact]) -> list[_Identity]:
    identities: list[_Identity] = []
    for fact in facts:
        identity = _find_identity(identities, fact)
        if identity is None:
            identity = _Identity(slug=fact.slug, name=fact.name)
            identities.append(identity)
        identity.facts.append(fact)
    return identities


def _source_values(facts: list[SourceFact], field_name: str) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    for fact in facts:
        raw = getattr(fact, field_name)
        if raw is None:
            continue
        value = "current" if raw is True else ("alumni" if raw is False else str(raw))
        values.setdefault(fact.source, [])
        if value not in values[fact.source]:
            values[fact.source].append(value)
    return {source: " | ".join(source_values) for source, source_values in values.items()}


def _conflict(field_name: str, values: dict[str, str]) -> dict[str, Any] | None:
    if len(set(values.values())) <= 1:
        return None
    return {"field": field_name, "values": values}


def _value(fact: SourceFact, name: str) -> Any:
    if name in {"role", "program", "current"}:
        return getattr(fact, name)
    return fact.data.get(name)


def _configured_value(facts: list[SourceFact], name: str, policy: RosterPolicy) -> Any:
    sources = policy.fields_from.get(name, (policy.authority,))
    for source in sources:
        for fact in facts:
            if fact.source == source and (value := _value(fact, name)) is not None:
                return value
    return None


def _membership(
    identity: _Identity, policy: RosterPolicy
) -> tuple[Literal["current", "former"], str | None]:
    by_source = {fact.source for fact in identity.facts}
    explicit = policy.membership_exceptions.get(identity.slug)
    if explicit == "former":
        return "former", None
    if policy.authority in by_source:
        return "current", None
    staff_current = any(f.source == "staff_org" and f.current is True for f in identity.facts)
    if staff_current:
        return "current", "not on roster of record"
    return "former", None


def reconcile_roster(
    facts: Iterable[SourceFact], policy: RosterPolicy | None = None
) -> list[RosterPerson]:
    policy = policy or RosterPolicy()
    people: list[RosterPerson] = []
    for identity in _group_facts(facts):
        present = {source: False for source in SOURCE_NAMES}
        for fact in identity.facts:
            present[fact.source] = True
        conflicts = [
            conflict
            for field_name in ("role", "program", "current")
            if (conflict := _conflict(field_name, _source_values(identity.facts, field_name)))
            is not None
        ]
        for conflict in conflicts:
            if conflict["field"] == "current":
                conflict["field"] = "status"
        agreed_role = _configured_value(identity.facts, "role", policy)
        if agreed_role is None:
            agreed_role = next(
                (fact.role for fact in identity.facts if fact.role is not None), "alumni"
            )
        program = _configured_value(identity.facts, "program", policy)
        staff_alumni = any(
            fact.source == "staff_org" and fact.current is False for fact in identity.facts
        )
        status = (
            "alumni"
            if staff_alumni
            else (
                "conflict"
                if conflicts
                else ("agree" if present["staff_org"] and present["website"] else "only-in")
            )
        )
        existing = next((fact.data for fact in identity.facts if fact.source == "people_yaml"), {})
        membership, pending = _membership(identity, policy)
        if pending:
            conflicts.append(
                {
                    "field": "membership",
                    "values": {policy.authority: "absent", "staff_org": "current"},
                }
            )
        selected = {
            field_name: _configured_value(identity.facts, field_name, policy)
            for field_name in policy.fields_from
        }
        people.append(
            RosterPerson(
                slug=identity.slug,
                name=identity.name,
                role=str(agreed_role),
                program=program,
                present=present,
                status=status,
                conflicts=conflicts,
                facts=identity.facts,
                existing=existing,
                membership=membership,
                pending=pending,
                selected=selected,
            )
        )
    return sorted(people, key=lambda person: (person.name.lower(), person.slug))


def build_roster(
    staff: GroupRoster,
    website: Iterable[WebsiteProfile],
    roster_md: Iterable[RosterEntry],
    graph: ResearchKg,
    people_data: dict[str, Any],
    policy: RosterPolicy | None = None,
) -> list[RosterPerson]:
    return reconcile_roster(collect_facts(staff, website, roster_md, graph, people_data), policy)


def roster_summary(people: Iterable[RosterPerson]) -> dict[str, int]:
    rows = list(people)
    return {
        "agree": sum(row.status == "agree" for row in rows),
        "only_in": sum(row.status == "only-in" for row in rows),
        "conflict": sum(row.status == "conflict" for row in rows),
        "alumni_still_listed": sum(
            row.status == "alumni" and any(fact.current is True for fact in row.facts)
            for row in rows
        ),
    }


def _entry_source(person: RosterPerson) -> str:
    existing = person.existing.get("source")
    if existing:
        return str(existing)
    labels = {
        "staff_org": "staff.org",
        "website": "borg.kaust.edu.sa",
        "roster_md": "roster.md",
        "kg": "projects.jsonld",
    }
    return "; ".join(
        labels[source]
        for source in SOURCE_NAMES
        if source != "people_yaml" and person.present[source]
    )


def _yaml_entry(person: RosterPerson) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": person.name}
    entry["role"] = person.role
    if person.program is not None:
        entry["program"] = person.program
    for key, value in person.existing.items():
        if key not in {"name", "role", "program", "source", "left", "pending", "previous_program"}:
            entry[key] = value
    for key, value in person.selected.items():
        if value is not None and key not in {"role", "program"}:
            entry[key] = value
    previous_program = person.existing.get("previous_program")
    old_program = person.existing.get("program")
    if previous_program:
        entry["previous_program"] = previous_program
    elif old_program and person.program and old_program != person.program:
        entry["previous_program"] = old_program
    if person.pending:
        entry["pending"] = person.pending
    if person.membership == "former":
        alumni = any(fact.source == "staff_org" and fact.current is False for fact in person.facts)
        entry["left"] = (
            "staff.org Alumni section" if alumni else "absent from roster of record 2026-09-02"
        )
    entry["source"] = _entry_source(person)
    return entry


def render_people_yaml(people: Iterable[RosterPerson], *, noted: date) -> str:
    """Render only agreed field values and carry conflicts for derive_conflicts."""
    current: dict[str, dict[str, Any]] = {}
    former: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for person in people:
        target = current if person.membership == "current" else former
        target[person.slug] = _yaml_entry(person)
        for conflict in person.conflicts:
            values = conflict["values"]
            pairs = [f"{source}: {value}" for source, value in values.items()]
            conflicts.append(
                {
                    "person": person.slug,
                    "field": conflict["field"],
                    "a": pairs[0],
                    "b": "; ".join(pairs[1:]),
                    "noted": noted.isoformat(),
                }
            )
    header = (
        "# Join table generated by `cube roster sync`. Source disagreements remain in\n"
        "# conflicts and become kind:conflict beads on `cube sync`.\n"
    )
    lines = [header.rstrip(), "people:"]
    lines.extend(f"  {slug}: {_inline_yaml(entry)}" for slug, entry in current.items())
    lines.append("former:")
    lines.extend(f"  {slug}: {_inline_yaml(entry)}" for slug, entry in former.items())
    lines.append("conflicts:")
    lines.extend(f"  - {_inline_yaml(conflict)}" for conflict in conflicts)
    return "\n".join(lines) + "\n"


def _inline_yaml(value: dict[str, Any]) -> str:
    return yaml.safe_dump(
        value,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=True,
        width=100_000,
    ).strip()
