"""Assemble the run context: bd prime, bead show, resolved refs, privacy filter, skill paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Tier
from cube.roles import Role

PRIME_LIMIT = 6000
DESCRIPTION_LIMIT = 12000
COMMENT_LIMIT = 6
# Lines with these words never enter a model context from bead text or resolved refs (doctrine 5).
FORBIDDEN_WORDS = re.compile(
    r"\b(grade|grades|gpa|salary|salaries|passport|disciplinary|"
    r"contract value|contract (?:renewal|extension|expiry|expiration|end)|"
    r"diagnosed with|sick leave|visa expires|visa application|iqama)\b",
    re.IGNORECASE,
)
REDACTED = "[redacted: grades/HR material never enters a model context (doctrine 5)]"
PRIVACY_RANK = {Privacy.public: 0, Privacy.internal: 1, Privacy.local_only: 2}


@dataclass
class Context:
    text: str
    privacy: Privacy = Privacy.internal
    labels: list[str] = field(default_factory=list)
    bead: dict[str, Any] = field(default_factory=dict)
    tier_label: Tier | None = None
    refs: dict[str, str] = field(default_factory=dict)
    skill_paths: dict[str, Path | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def privacy_filter(text: str) -> tuple[str, int]:
    out: list[str] = []
    hits = 0
    for line in text.splitlines():
        if FORBIDDEN_WORDS.search(line):
            out.append(REDACTED)
            hits += 1
        else:
            out.append(line)
    return "\n".join(out), hits


def bead_labels(bead: dict[str, Any]) -> list[str]:
    raw = bead.get("labels") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("name"):
            out.append(str(item["name"]))
    return out


_TITLE_WORDS = re.compile(r"[a-z]+")


def title_key(title: str) -> str:
    """The subject of a title without numbers: 'ws root disk at 91%' == 'at 92%'.

    An ``Escalation from <role>:`` prefix is dropped so the same subject from the
    same role keys the same whatever the numbers of the day.
    """
    text = title.lower()
    if ":" in text and text.startswith("escalation from"):
        text = text.split(":", 1)[1]
    return " ".join(_TITLE_WORDS.findall(text)[:8])


def label_value(labels: list[str], prefix: str) -> str | None:
    for label in labels:
        if label.startswith(prefix):
            return label[len(prefix) :]
    return None


def bead_privacy(bead: dict[str, Any], labels: list[str]) -> Privacy:
    header = BeadHeader.parse(str(bead.get("description") or ""))
    if header:
        return header.privacy
    value = label_value(labels, "privacy:")
    if value:
        try:
            return Privacy(value)
        except ValueError:
            pass
    return Privacy.internal


def bead_tier(labels: list[str]) -> Tier | None:
    value = label_value(labels, "tier:")
    if not value:
        return None
    try:
        return Tier(value)
    except ValueError:
        return None


def load_people(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "people.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    people = data.get("people") if isinstance(data, dict) else None
    if not isinstance(people, dict):
        return {}
    return {str(k): dict(v) for k, v in people.items() if isinstance(v, dict)}


def resolve_person(slug: str, people: dict[str, dict[str, Any]]) -> str:
    rec = people.get(slug)
    if not rec:
        return f"person:{slug}: not in people.yaml (unresolved; do not guess)"
    fields = [f"{k}={v}" for k, v in rec.items() if k in ("name", "role", "program", "start")]
    org = rec.get("org_file")
    extra = f"; notes in ~/org/{org}" if org else ""
    src = rec.get("source")
    return f"person:{slug}: {', '.join(fields)}{extra} (source: people.yaml <- {src})"


def resolve_external(settings: Settings, kind: str, ident: str) -> str | None:
    """Use cube.sources when it exists and exposes resolve_ref; never a hard dependency."""
    try:
        from cube import sources  # noqa: PLC0415 - optional sibling module
    except ImportError:
        return None
    fn = getattr(sources, "resolve_ref", None)
    if not callable(fn):
        return None
    try:
        out = fn(settings, kind, ident)
    except Exception as exc:  # noqa: BLE001 - a broken resolver must not stop a run
        return f"{kind}:{ident}: resolver error: {exc}"
    return str(out) if out else None


def resolve_refs(settings: Settings, labels: list[str]) -> dict[str, str]:
    people = load_people(settings.root)
    refs: dict[str, str] = {}
    for label in labels:
        if label.startswith("person:"):
            refs[label] = resolve_person(label[len("person:") :], people)
        elif label.startswith(("project:", "paper:", "repo:", "course:")):
            kind, ident = label.split(":", 1)
            refs[label] = resolve_external(settings, kind, ident) or (
                f"{label}: not resolvable here (cube.sources absent); read the bead's provenance"
            )
    return refs


def resolve_skills(settings: Settings, names: list[str]) -> dict[str, Path | None]:
    """Skill dirs: skills/<name> in this repo, then the skills library, then seeded index."""
    out: dict[str, Path | None] = {}
    seeded: dict[str, Path] = {}
    index = settings.root / "skills" / "seeded" / "index.yaml"
    if index.exists():
        data = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
        for item in data.get("skills") or [] if isinstance(data, dict) else []:
            if isinstance(item, dict) and item.get("name") and item.get("path"):
                seeded[str(item["name"])] = Path(str(item["path"])).expanduser()
    for name in names:
        candidates = [
            settings.root / "skills" / name,
            settings.dirs["skills_library"] / name,
            Path("~/.claude/skills").expanduser() / name,
        ]
        if name in seeded:
            candidates.insert(1, seeded[name])
        found = next((c for c in candidates if (c / "SKILL.md").exists()), None)
        out[name] = found
    return out


def _comments(bead: dict[str, Any]) -> list[str]:
    raw = bead.get("comments") or []
    out: list[str] = []
    for c in raw[-COMMENT_LIMIT:]:
        if isinstance(c, dict):
            out.append(f"- {c.get('author', '?')} {c.get('created_at', '')}: {c.get('text', '')}")
        else:
            out.append(f"- {c}")
    return out


def build_context(
    settings: Settings,
    beads: Beads,
    role: Role,
    bead_id: str | None,
    *,
    prompt_text: str | None = None,
    worktree: Path | None = None,
) -> Context:
    ctx = Context(text="")
    parts: list[str] = []
    prime = ""
    if beads.available():
        try:
            prime = beads.prime()
        except BeadsError as exc:
            ctx.warnings.append(f"bd prime failed: {exc}")
    if prime.strip():
        parts.append("### bd prime\n\n" + prime.strip()[:PRIME_LIMIT])
    if bead_id:
        bead: dict[str, Any] = {}
        if beads.available():
            try:
                bead = beads.show(bead_id)
            except BeadsError as exc:
                ctx.warnings.append(f"bd show {bead_id} failed: {exc}")
        ctx.bead = bead
        ctx.labels = bead_labels(bead)
        ctx.privacy = bead_privacy(bead, ctx.labels)
        ctx.tier_label = bead_tier(ctx.labels)
        shown = {
            k: bead.get(k)
            for k in ("id", "title", "status", "issue_type", "priority", "assignee", "parent")
            if k in bead
        }
        desc, hits = privacy_filter(str(bead.get("description") or "")[:DESCRIPTION_LIMIT])
        if hits:
            ctx.warnings.append(f"{hits} line(s) redacted from bead description")
        section = [
            f"### Bead {bead_id}",
            "```json",
            json.dumps(shown, ensure_ascii=False, indent=1, default=str),
            "```",
            f"labels: {', '.join(ctx.labels) or '(none)'}",
            f"privacy: {ctx.privacy.value}",
            "",
            desc.strip() or "(no description)",
        ]
        comments = _comments(bead)
        if comments:
            text, hits = privacy_filter("\n".join(comments))
            section += ["", "recent comments:", text]
        parts.append("\n".join(section))
        ctx.refs = resolve_refs(settings, ctx.labels)
        if ctx.refs:
            text, hits = privacy_filter("\n".join(f"- {v}" for v in ctx.refs.values()))
            parts.append("### Resolved references\n\n" + text)
        agent_name = label_value(ctx.labels, "agent:")
        if agent_name:
            # Named-agent identity is an additive context block.  The engine still
            # owns role, tier, privacy and outbound enforcement for this bead.
            try:
                from cube.agents import context_block  # noqa: PLC0415 - avoids import cycle

                text, hits = privacy_filter(context_block(settings, agent_name))
                if hits:
                    ctx.warnings.append(f"{hits} line(s) redacted from standing-agent context")
                parts.append(text)
            except Exception as exc:  # noqa: BLE001 - a bad memory file must not block a bead
                ctx.warnings.append(f"agent:{agent_name} context unavailable: {exc}")
    if worktree:
        parts.append(
            f"### Worktree\n\nYou are started in `{worktree}` on branch `cube/{bead_id}`; "
            "stay inside it."
        )
    if prompt_text:
        parts.append("### Instruction\n\n" + prompt_text.strip())
    ctx.skill_paths = resolve_skills(settings, role.skills)
    ctx.text = "\n\n".join(parts)
    return ctx


def privacy_allowed(role: Role, privacy: Privacy) -> bool:
    return PRIVACY_RANK[privacy] <= PRIVACY_RANK[role.privacy_max]
