"""Shared helpers for the borg-cube skill and corpus tools.

Everything here is stdlib plus PyYAML. The tools in this directory import it
as a sibling module (``python tools/<tool>.py`` puts ``tools/`` on sys.path).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "corpus" / "sources.yaml"
DEFAULT_DISTILLED = REPO_ROOT / "corpus" / "distilled"
DEFAULT_SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_TESTS_DIR = REPO_ROOT / "tests" / "skills"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EM_DASH = "\u2014"

MANIFEST_TYPES = {"article", "book", "report", "web", "institutional", "spec"}
MANIFEST_VERIFIED_BY = {"web-search", "fetch", "robert", "memory"}
MANIFEST_EXCERPT_OK = {True, False, "quote-rules-only"}


class ToolError(Exception):
    """Raised for user-facing failures; the CLI prints the message and exits 1."""


# --------------------------------------------------------------------------- manifest


@dataclass
class Source:
    id: str
    type: str
    citation: str
    license: str
    oa: bool | str
    excerpt_ok: bool | str
    topics: list[str]
    verified_by: str
    doi: str | None = None
    url: str | None = None
    fetched: str | None = None
    sha256: str | None = None
    notes: str | None = None
    doi_registry: str = "crossref"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Source:
        known = {
            "id",
            "type",
            "citation",
            "license",
            "oa",
            "excerpt_ok",
            "topics",
            "verified_by",
            "doi",
            "url",
            "fetched",
            "sha256",
            "notes",
            "doi_registry",
        }
        missing = [
            k
            for k in ("id", "type", "citation", "license", "oa", "excerpt_ok", "topics")
            if k not in data
        ]
        if missing:
            raise ToolError(f"manifest entry {data.get('id', '?')!r} lacks {missing}")
        kwargs = {k: data.get(k) for k in known if k in data}
        kwargs.setdefault("verified_by", "memory")
        return cls(raw=data, **kwargs)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[Source]:
    """Load ``corpus/sources.yaml`` and return its entries in file order."""
    if not path.exists():
        raise ToolError(f"manifest not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ToolError(f"manifest {path} must contain a top-level 'sources' list")
    sources = [Source.from_dict(e) for e in entries]
    seen: set[str] = set()
    for s in sources:
        if s.id in seen:
            raise ToolError(f"duplicate manifest id {s.id!r}")
        seen.add(s.id)
    return sources


def manifest_ids(path: Path = DEFAULT_MANIFEST) -> set[str]:
    return {s.id for s in load_manifest(path)}


def validate_manifest(sources: list[Source]) -> list[str]:
    """Return a list of schema problems (empty when the manifest is clean)."""
    problems: list[str] = []
    for s in sources:
        if not ID_RE.match(s.id):
            problems.append(f"{s.id}: id must match {ID_RE.pattern}")
        if s.type not in MANIFEST_TYPES:
            problems.append(f"{s.id}: type {s.type!r} not in {sorted(MANIFEST_TYPES)}")
        if s.verified_by not in MANIFEST_VERIFIED_BY:
            problems.append(f"{s.id}: verified_by {s.verified_by!r} not allowed")
        if s.excerpt_ok not in MANIFEST_EXCERPT_OK:
            problems.append(f"{s.id}: excerpt_ok {s.excerpt_ok!r} not allowed")
        if not (isinstance(s.oa, bool) or s.oa == "web"):
            problems.append(f"{s.id}: oa must be true, false or 'web'")
        if not s.topics:
            problems.append(f"{s.id}: topics must not be empty")
        if s.doi and not s.doi.startswith("10."):
            problems.append(f"{s.id}: doi {s.doi!r} must start with '10.'")
        if s.type == "book" and s.excerpt_ok is not False:
            problems.append(f"{s.id}: books are cite-only (excerpt_ok must be false)")
    return problems


def update_manifest_fields(path: Path, entry_id: str, updates: dict[str, Any]) -> None:
    """Rewrite scalar fields of one manifest entry in place, preserving comments.

    The manifest is edited line by line: the block for ``entry_id`` starts at
    ``- id: <entry_id>`` and ends before the next ``- id:`` line. Each key in
    ``updates`` must already exist in that block.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*-\s+id:\s*{re.escape(entry_id)}\s*$", line):
            start = i
            break
    if start is None:
        raise ToolError(f"manifest entry {entry_id!r} not found in {path}")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*-\s+id:", lines[j]):
            end = j
            break
    pending = dict(updates)
    for k in range(start, end):
        m = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", lines[k])
        if not m or k > start and lines[k].lstrip().startswith("- "):
            continue
        indent, key, _ = m.groups()
        if key in pending:
            value = _yaml_scalar(pending.pop(key))
            lines[k] = f"{indent}{key}: {value}\n"
    if pending:
        raise ToolError(f"fields {sorted(pending)} not present in manifest entry {entry_id!r}")
    path.write_text("".join(lines), encoding="utf-8")


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    dumped = yaml.safe_dump(value, default_flow_style=True).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[:-4].strip()
    return dumped


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- frontmatter


@dataclass
class Frontmatter:
    data: dict[str, Any]
    body: str
    raw_yaml: str
    end_line: int  # 0-based index of the closing '---' line; -1 when absent


def parse_frontmatter(text: str) -> Frontmatter:
    """Split a Markdown document into YAML frontmatter and body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter(data={}, body=text, raw_yaml="", end_line=-1)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "\n".join(lines[1:i])
            try:
                data = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:  # pragma: no cover - exercised via lint tests
                raise ToolError(f"invalid YAML frontmatter: {exc}") from exc
            if not isinstance(data, dict):
                raise ToolError("frontmatter must be a mapping")
            body = "\n".join(lines[i + 1 :])
            return Frontmatter(data=data, body=body, raw_yaml=raw, end_line=i)
    raise ToolError("frontmatter opened with '---' but never closed")


def grounding_ids(metadata: dict[str, Any] | None) -> list[str]:
    """Return ``metadata.grounding`` as a list, accepting a comma string or list."""
    if not metadata:
        return []
    value = metadata.get("grounding")
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    raise ToolError("metadata.grounding must be a comma-separated string or a list")


# --------------------------------------------------------------------------- sources blocks

SOURCES_HEADER_RE = re.compile(r"^(?:#{1,6}\s+)?Sources:?\s*$")
SOURCES_ITEM_RE = re.compile(r"^\s*[-*]\s+\[?([a-z0-9][a-z0-9.-]*)\]?(?:[:\s].*)?$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def parse_sources_block(body: str) -> tuple[list[str], int | None]:
    """Find the Sources block of a reference file.

    Returns ``(ids, line_index_of_header)``; ``ids`` is empty and the index is
    ``None`` when no block was found. The block is the header line ``Sources``
    (optionally a Markdown heading, optionally with a colon) followed by list
    items whose first token is a manifest id.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if SOURCES_HEADER_RE.match(line.strip()):
            ids: list[str] = []
            for item in lines[i + 1 :]:
                if not item.strip():
                    if ids:
                        break
                    continue
                m = SOURCES_ITEM_RE.match(item)
                if not m:
                    break
                ids.append(m.group(1))
            return ids, i
    return [], None


def sources_block_is_first(body: str) -> bool:
    """True when the Sources block precedes any content other than an H1 title."""
    ids, idx = parse_sources_block(body)
    if idx is None or not ids:
        return False
    for line in body.splitlines()[:idx]:
        stripped = line.strip()
        if not stripped:
            continue
        m = HEADING_RE.match(stripped)
        if m and len(m.group(1)) == 1:
            continue
        return False
    return True


def reference_files(skill_dir: Path) -> list[Path]:
    refs = skill_dir / "references"
    if not refs.is_dir():
        return []
    return sorted(p for p in refs.glob("*.md") if p.is_file())


def read_sync_manifest(skill_dir: Path) -> list[str]:
    """Topics listed in ``references/manifest.txt`` (one per line, ``#`` comments)."""
    path = skill_dir / "references" / "manifest.txt"
    if not path.exists():
        return []
    topics: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            topics.append(line)
    return topics


def discover_skills(skills_dir: Path = DEFAULT_SKILLS_DIR) -> list[Path]:
    """Skill directories: immediate children of ``skills/`` that contain SKILL.md."""
    if not skills_dir.is_dir():
        return []
    return sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").is_file())


def token_estimate(text: str) -> int:
    """Rough token count at four characters per token."""
    return (len(text) + 3) // 4
