"""Literature digest: the deterministic half of the daily arXiv and bioRxiv watch.

The ``literature_watch`` patrol collects candidates; this module builds the group context,
renders the summarisation prompt, validates the model's ``literature-digest`` artifact
against the candidate list, and writes ``briefings/literature/<date>.md`` and ``.json``.
Nothing here calls a model and nothing here reaches the network.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Provenance
from cube.sources.rkg import load_graph

MAX_ABSTRACT_CHARS = 1200
PRIORITIES = ("high", "normal", "low")
RELEVANCE_KINDS = ("student", "project", "goal", "topic", "agent")
GOAL_DEADLINE_DAYS = 30
BRIEF_ENTRIES = 5


class LiteratureError(ValueError):
    """The digest artifact does not describe the candidates it was given."""


# --- state -------------------------------------------------------------------------------


def literature_state_dir(settings: Settings) -> Path:
    return settings.state_dir() / "literature"


def candidates_path(settings: Settings, day: date) -> Path:
    return literature_state_dir(settings) / f"{day.isoformat()}.jsonl"


def load_candidates(settings: Settings, day: date) -> list[dict[str, Any]]:
    path = candidates_path(settings, day)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_candidates(settings: Settings, day: date, rows: list[dict[str, Any]]) -> Path:
    path = candidates_path(settings, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def pending_candidates(settings: Settings, day: date) -> list[dict[str, Any]]:
    return [row for row in load_candidates(settings, day) if not row.get("summarised")]


def mark_summarised(settings: Settings, day: date, ids: list[str]) -> Path:
    wanted = set(ids)
    rows = load_candidates(settings, day)
    for row in rows:
        if row.get("id") in wanted:
            row["summarised"] = True
    return write_candidates(settings, day, rows)


# --- context -----------------------------------------------------------------------------


@dataclass
class LiteratureContext:
    """What the group is working on, all of it read from a source of record."""

    topics: list[dict[str, str]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    students: list[dict[str, Any]] = field(default_factory=list)
    goals: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def refs(self) -> dict[str, set[str]]:
        return {
            "topic": {t["slug"] for t in self.topics},
            "project": {p["slug"] for p in self.projects},
            "student": {s["id"] for s in self.students},
            "goal": {str(g["id"]) for g in self.goals} | {str(g["title"]) for g in self.goals},
        }


def _topic_brief(rkg_dir: Path, slug: str) -> str:
    path = rkg_dir / "topics" / f"{slug}.md"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith(("#", "*", "-", "`")):
            continue
        return text[:300]
    return ""


def _people(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "people.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    people = data.get("people") if isinstance(data, dict) else None
    return {str(k): dict(v) for k, v in people.items()} if isinstance(people, dict) else {}


def build_context(settings: Settings, *, beads: Beads | None = None) -> LiteratureContext:
    """Topics, active projects, current students with their expertise, and open goals."""
    rkg_dir = settings.dirs["rkg"]
    graph = load_graph(rkg_dir / "projects.jsonld")
    ctx = LiteratureContext(
        sources=[str(rkg_dir / "projects.jsonld"), str(settings.root / "people.yaml")]
    )
    for slug in graph.topics:
        ctx.topics.append({"slug": slug, "brief": _topic_brief(rkg_dir, slug)})
    year = date.today().year
    person_topics: dict[str, set[str]] = {}
    for project in graph.projects:
        if project.end_year is not None and project.end_year < year:
            continue
        members = [slug for slug, _role in project.members]
        topics = sorted({topic.rsplit("/", 1)[-1].rsplit(":", 1)[-1] for topic in project.topics})
        ctx.projects.append(
            {
                "slug": project.slug,
                "name": project.name,
                "members": members,
                "topics": topics,
            }
        )
        for member in members:
            person_topics.setdefault(member, set()).update(topics)
    for pid, person in sorted(_people(settings.root).items()):
        if str(person.get("role")) not in {"student", "postdoc"}:
            continue
        ctx.students.append(
            {
                "id": pid,
                "name": str(person.get("name") or pid),
                "program": person.get("program"),
                "expertise": sorted(person_topics.get(pid, set())),
            }
        )
    if beads is not None and beads.available():
        try:
            from cube.goals import goal_header, read_goal_ledger  # noqa: PLC0415

            issues, _ready, _blocked = read_goal_ledger(beads)
        except (BeadsError, ValueError):
            issues = []
        for issue in issues:
            header = goal_header(issue)
            if header is None:
                continue
            deadline = header.deadline or header.target
            ctx.goals.append(
                {
                    "id": str(issue.get("id") or ""),
                    "title": str(issue.get("title") or ""),
                    "deadline": deadline.isoformat() if deadline else None,
                }
            )
        ctx.sources.append("cube goals --json")
    return ctx


def context_text(ctx: LiteratureContext) -> str:
    lines = ["## Group context", ""]
    lines.append("### Topics")
    lines.extend(
        f"- {topic['slug']}: {topic['brief'] or '(no brief on file)'}" for topic in ctx.topics
    )
    if not ctx.topics:
        lines.append("- (none on file)")
    lines += ["", "### Active projects"]
    lines.extend(
        f"- {p['slug']}: {p['name']}; members {', '.join(p['members']) or 'none listed'}; "
        f"topics {', '.join(p['topics']) or 'none listed'}"
        for p in ctx.projects
    )
    if not ctx.projects:
        lines.append("- (none on file)")
    lines += ["", "### Current students and postdocs"]
    lines.extend(
        f"- {s['id']}: {s['name']} ({s['program'] or 'program unknown'}); "
        f"expertise {', '.join(s['expertise']) or 'not recorded'}"
        for s in ctx.students
    )
    if not ctx.students:
        lines.append("- (none on file)")
    lines += ["", "### Open goals"]
    lines.extend(
        f"- {g['id']}: {g['title']} (deadline {g['deadline'] or 'none'})" for g in ctx.goals
    )
    if not ctx.goals:
        lines.append("- (none on file)")
    lines += ["", "Sources: " + ", ".join(ctx.sources)]
    return "\n".join(lines)


# --- prompt ------------------------------------------------------------------------------


def candidate_block(candidates: list[dict[str, Any]]) -> str:
    lines = ["## Candidate preprints", ""]
    for row in candidates:
        abstract = str(row.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
        lines += [
            f"### {row.get('id')}",
            f"- source: {row.get('source')}",
            f"- title: {row.get('title')}",
            f"- url: {row.get('url')}",
            f"- categories: {', '.join(row.get('categories') or []) or 'none'}",
            f"- matched terms: {', '.join(row.get('matched') or []) or 'none'}",
            f"- abstract: {abstract}",
            "",
        ]
    return "\n".join(lines)


def summary_prompt(
    settings: Settings, candidates: list[dict[str, Any]], context: LiteratureContext
) -> str:
    """The full deterministic prompt for one literature-digest step."""
    limit = settings.literature_watch.max_summaries_per_day
    ids = ", ".join(str(row.get("id")) for row in candidates)
    return "\n\n".join(
        [
            "# Literature watch",
            "Summarise today's new arXiv and bioRxiv submissions for the research group. "
            "Read only the candidate list below; you have no other reading material and "
            "must not add a paper from memory.",
            context_text(context),
            candidate_block(candidates),
            "## Required output\n\n"
            "Return one artifact with kind `literature-digest` whose content is strict JSON:\n\n"
            "```json\n"
            '{"kind": "literature-digest", "entries": [\n'
            '  {"id": "<candidate id>", "source": "arxiv|biorxiv", "url": "<candidate url>",\n'
            '   "title": "<candidate title>", "one_paragraph_summary": "<one paragraph>",\n'
            '   "relevance": [{"kind": "student|project|goal|topic|agent", "ref": "<slug or id>",\n'
            '                  "why": "<one sentence>"}],\n'
            '   "priority": "high|normal|low"}\n'
            "]}\n"
            "```\n\n"
            f"Rules:\n"
            f"- At most {limit} entries, best first. Fewer is fine; zero is fine when nothing "
            "is relevant.\n"
            "- Every `id` must be one of the candidate ids listed above and must appear once. "
            f"The candidate ids are: {ids or '(none)'}.\n"
            "- Every entry needs at least one relevance record, and every `why` must quote the "
            "matched term, or the project or goal title, it relates to.\n"
            "- `ref` is a student id, a project slug, a goal bead id or title, a topic slug or "
            "an agent name from the group context above.\n"
            "- Keep `url` exactly as given; an entry without its source url is not usable.\n"
            "- No em-dashes. Plain language. No claim that is not in the abstract.",
        ]
    )


# --- validation --------------------------------------------------------------------------


def parse_artifact(text: str) -> dict[str, Any]:
    """Read the JSON body of a literature-digest artifact, fenced or bare."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        body = body.rsplit("```", 1)[0]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LiteratureError(f"literature-digest artifact is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LiteratureError("literature-digest artifact must be a JSON object")
    return data


def validate_digest(
    artifact: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return the accepted entries and the reasons the rejected ones were dropped."""
    by_id = {str(row.get("id")): row for row in candidates}
    entries = artifact.get("entries")
    if not isinstance(entries, list):
        raise LiteratureError("literature-digest artifact has no entries list")
    accepted: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            errors.append("entry is not an object")
            continue
        ident = str(raw.get("id") or "")
        if ident not in by_id:
            errors.append(f"{ident or '(no id)'}: not in today's candidate list")
            continue
        if ident in seen:
            errors.append(f"{ident}: duplicate entry")
            continue
        candidate = by_id[ident]
        url = str(raw.get("url") or candidate.get("url") or "")
        if not url:
            errors.append(f"{ident}: no source url")
            continue
        summary = str(raw.get("one_paragraph_summary") or "").strip()
        if not summary:
            errors.append(f"{ident}: no summary")
            continue
        relevance: list[dict[str, str]] = []
        for item in raw.get("relevance") or []:
            if not isinstance(item, dict):
                errors.append(f"{ident}: relevance record is not an object")
                continue
            kind = str(item.get("kind") or "")
            ref = str(item.get("ref") or "").strip()
            why = str(item.get("why") or "").strip()
            if kind not in RELEVANCE_KINDS:
                errors.append(f"{ident}: relevance kind {kind or '(missing)'} is not known")
                continue
            if not ref:
                errors.append(f"{ident}: relevance without a ref")
                continue
            if not why:
                errors.append(f"{ident}: relevance to {kind} {ref} without a why")
                continue
            relevance.append({"kind": kind, "ref": ref, "why": why})
        if not relevance:
            errors.append(f"{ident}: no usable relevance record")
            continue
        priority = str(raw.get("priority") or "normal")
        if priority not in PRIORITIES:
            priority = "normal"
        seen.add(ident)
        accepted.append(
            {
                "id": ident,
                "source": str(candidate.get("source") or raw.get("source") or ""),
                "url": url,
                "title": str(raw.get("title") or candidate.get("title") or ""),
                "one_paragraph_summary": summary,
                "relevance": relevance,
                "priority": priority,
                "doi": candidate.get("doi"),
                "matched": list(candidate.get("matched") or []),
            }
        )
        if len(accepted) >= limit:
            break
    return accepted, errors


# --- rendering ---------------------------------------------------------------------------

GROUPS = (
    ("student", "For students"),
    ("project", "For projects"),
    ("goal", "For goals"),
)


def group_entries(entries: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Each entry appears once, under the first relevance target it actually has."""
    buckets: dict[str, list[dict[str, Any]]] = {title: [] for _kind, title in GROUPS}
    buckets["Other relevant"] = []
    for entry in entries:
        kinds = {record["kind"] for record in entry["relevance"]}
        title = next((title for kind, title in GROUPS if kind in kinds), "Other relevant")
        buckets[title].append(entry)
    return [(title, buckets[title]) for _kind, title in GROUPS if buckets[title]] + (
        [("Other relevant", buckets["Other relevant"])] if buckets["Other relevant"] else []
    )


def _why_lines(entry: dict[str, Any]) -> list[str]:
    return [f"  - {r['kind']} {r['ref']}: {r['why']}" for r in entry["relevance"]]


def render_digest_markdown(day: date, entries: list[dict[str, Any]]) -> str:
    lines = [f"# Literature watch {day.isoformat()}", ""]
    if not entries:
        lines.append("Nothing relevant in yesterday's and today's submissions.")
        return "\n".join(lines) + "\n"
    lines.append(
        f"{len(entries)} relevant preprint(s); "
        f"{sum(1 for e in entries if e['priority'] == 'high')} high priority."
    )
    lines.append("")
    for title, group in group_entries(entries):
        lines += [f"## {title}", ""]
        for entry in group:
            lines.append(f"- [{entry['priority']}] {entry['title']} ({entry['source']})")
            lines.append(f"  - {entry['url']}")
            lines.append(f"  - {entry['one_paragraph_summary']}")
            lines.extend(_why_lines(entry))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def digest_payload(
    day: date, entries: list[dict[str, Any]], counts: dict[str, Any]
) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "counts": dict(counts),
        "entries": entries,
    }


def digest_paths(settings: Settings, day: date) -> tuple[Path, Path]:
    base = settings.literature_watch.digest_path(settings.root)
    return base / f"{day.isoformat()}.md", base / f"{day.isoformat()}.json"


def write_digest(
    settings: Settings, day: date, entries: list[dict[str, Any]], counts: dict[str, Any]
) -> tuple[Path, Path]:
    md_path, json_path = digest_paths(settings, day)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_digest_markdown(day, entries), encoding="utf-8")
    json_path.write_text(
        json.dumps(digest_payload(day, entries, counts), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return md_path, json_path


def load_digest(settings: Settings, day: date) -> dict[str, Any] | None:
    _md, json_path = digest_paths(settings, day)
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# --- delivery ----------------------------------------------------------------------------


def urgent_goal_refs(
    context: LiteratureContext, today: date, days: int = GOAL_DEADLINE_DAYS
) -> set[str]:
    """Goal ids and titles whose deadline falls inside the attention horizon."""
    horizon = today + timedelta(days=days)
    refs: set[str] = set()
    for goal in context.goals:
        raw = goal.get("deadline")
        if not raw:
            continue
        try:
            deadline = date.fromisoformat(str(raw))
        except ValueError:
            continue
        if today <= deadline <= horizon:
            refs.update({str(goal["id"]), str(goal["title"])})
    refs.discard("")
    return refs


def needs_robert(entries: list[dict[str, Any]], context: LiteratureContext, today: date) -> bool:
    """Robert is told only about a high-priority paper touching a goal due within 30 days."""
    urgent = urgent_goal_refs(context, today)
    return any(
        entry["priority"] == "high"
        and any(r["kind"] == "goal" and r["ref"] in urgent for r in entry["relevance"])
        for entry in entries
    )


def reading_list_xid(day: date) -> str:
    return f"literature:{day.isoformat()}"


def reading_list_bead(
    beads: Beads,
    day: date,
    entries: list[dict[str, Any]],
    *,
    digest_json: Path,
    attention: bool,
) -> str | None:
    """One kind:reading-list bead per day, provenance the digest json."""
    if not entries:
        return None
    labels = ["kind:reading-list", "src:literature-watch"]
    if attention:
        labels.append("needs:robert")
    body_lines = [f"Digest: {digest_json}", ""]
    for entry in entries:
        body_lines.append(f"- [{entry['priority']}] {entry['title']} {entry['url']}")
    return beads.create(
        f"Reading list {day.isoformat()}: {len(entries)} relevant preprint(s)",
        header=BeadHeader(
            xid=reading_list_xid(day),
            provenance=[Provenance(source=str(digest_json), locator="entries", seen=day)],
            privacy=Privacy.internal,
        ),
        body="\n".join(body_lines),
        labels=labels,
        acceptance="Robert has read the digest or dismissed it.",
    )


def reading_identifier(entry: dict[str, Any]) -> str:
    """The citable identifier of an entry: the arXiv id, or the bioRxiv DOI."""
    ident = str(entry.get("id") or "")
    if ident.startswith("arxiv:"):
        return "arXiv:" + ident.split(":", 1)[1]
    return str(entry.get("doi") or ident.split(":", 1)[-1])


def reading_records(
    entries: list[dict[str, Any]], topic_agents: dict[str, list[str]]
) -> list[dict[str, str]]:
    """``append_reading`` records for the expert agents that own a matched topic."""
    out: list[dict[str, str]] = []
    for entry in entries:
        if entry["priority"] != "high":
            continue
        for record in entry["relevance"]:
            if record["kind"] != "topic":
                continue
            for name in topic_agents.get(record["ref"], []):
                out.append(
                    {
                        "agent": name,
                        "identifier": reading_identifier(entry),
                        "note": f"{entry['title']}: {record['why']}",
                        "source": entry["url"],
                    }
                )
    return out


def agents_by_topic(root: Path) -> dict[str, list[str]]:
    from cube.agents import load_all_agents  # noqa: PLC0415

    agents, _errors = load_all_agents(root)
    out: dict[str, list[str]] = {}
    for name, agent in sorted(agents.items()):
        if agent.kind != "expert":
            continue
        for topic in agent.topics:
            out.setdefault(topic, []).append(name)
    return out


# --- read views --------------------------------------------------------------------------


def literature_payload(settings: Settings, day: date) -> dict[str, Any]:
    """The ``cube literature --json`` payload: today's digest and today's counts."""
    digest = load_digest(settings, day) or {}
    candidates = load_candidates(settings, day)
    md_path, json_path = digest_paths(settings, day)
    entries = list(digest.get("entries") or [])
    return {
        "date": day.isoformat(),
        "entries": entries,
        "counts": {
            "fetched": sum(
                int(v.get("fetched", 0))
                for v in (digest.get("counts") or {}).values()
                if isinstance(v, dict)
            ),
            "matched": len(candidates),
            "summarised": len(entries),
            "pending": sum(1 for row in candidates if not row.get("summarised")),
        },
        "path": str(md_path),
        "json_path": str(json_path),
        "digest_exists": json_path.exists(),
    }


def literature_text(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    head = (
        f"Literature {payload['date']}: {counts['matched']} matched, "
        f"{counts['summarised']} summarised, {counts['pending']} pending"
    )
    lines = [head, payload["path"]]
    for entry in payload["entries"]:
        targets = ", ".join(f"{r['kind']} {r['ref']}" for r in entry["relevance"])
        lines.append(
            f"[{entry['priority']}] {entry['title']}  ({entry['source']})"
            + (f"  for: {targets}" if targets else "")
        )
    return "\n".join(lines)


def brief_block(settings: Settings, day: date, limit: int = BRIEF_ENTRIES) -> list[str]:
    """The ``Literature`` block of the morning brief: top high-priority entries only."""
    digest = load_digest(settings, day)
    md_path, _json_path = digest_paths(settings, day)
    lines = ["## Literature"]
    if digest is None:
        lines.append("- no literature digest for today")
        return lines
    high = [e for e in digest.get("entries") or [] if e.get("priority") == "high"]
    if not high:
        lines.append("- nothing high priority in today's preprints")
    for entry in high[:limit]:
        targets = ", ".join(f"{r['kind']} {r['ref']}" for r in entry.get("relevance") or [])
        lines.append(
            f"- {entry.get('title')} ({entry.get('url')})" + (f" for {targets}" if targets else "")
        )
    lines.append(f"- full digest: {md_path}")
    return lines


def entries_for_student(settings: Settings, student_id: str, day: date) -> list[dict[str, Any]]:
    """Today's digest entries that name this student, for the student digest."""
    digest = load_digest(settings, day)
    if digest is None:
        return []
    out: list[dict[str, Any]] = []
    for entry in digest.get("entries") or []:
        if any(
            r.get("kind") == "student" and r.get("ref") == student_id
            for r in entry.get("relevance") or []
        ):
            out.append(entry)
    return out


def student_digest_lines(settings: Settings, student_id: str, day: date) -> list[str]:
    """The ``Literature`` block of one student digest; empty when there is nothing."""
    entries = entries_for_student(settings, student_id, day)
    if not entries:
        return []
    _md, json_path = digest_paths(settings, day)
    lines = ["", "## Literature", ""]
    for entry in entries:
        why = next(
            (
                r["why"]
                for r in entry["relevance"]
                if r.get("kind") == "student" and r.get("ref") == student_id
            ),
            "",
        )
        lines.append(f"- {entry['title']} ({entry['url']}): {why}")
    lines.append(f"- Source: {json_path}")
    return lines
