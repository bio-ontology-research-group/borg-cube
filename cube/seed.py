"""`cube seed`: index existing skills and doctrine from other repos, with provenance, no copies."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from cube.config import Settings

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class SeedSource:
    kind: str  # skill | doctrine | memory
    path: Path
    name: str
    description: str = ""
    exists: bool = True

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d


def skill_dirs(settings: Settings) -> list[Path]:
    d = settings.dirs
    home = Path.home()
    candidates = [
        d["infra"] / "hermes-infra" / "skills",
        d["infra"] / "skills",
        d["skills_library"] / "local",
        d["skills_library"] / "claw",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
        d["pa"] / "skill",
    ]
    return candidates


def doctrine_files(settings: Settings) -> list[Path]:
    d = settings.dirs
    home = Path.home()
    return [
        d["infra"] / "hermes-infra" / "AGENTS.md",
        d["infra"] / "AGENTS.md",
        d["infra"] / "README.md",
        d["pa"] / "CLAUDE.md",
        d["org"] / "CLAUDE.md",
        home / ".codex" / "AGENTS.md",
        d["skills_library"] / "CLAUDE.md",
    ]


def memory_dir() -> Path:
    slug = "-" + str(Path.home()).strip("/").replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug / "memory"


def read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = FRONTMATTER.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def discover(settings: Settings) -> list[SeedSource]:
    found: list[SeedSource] = []
    seen: set[Path] = set()
    for base in skill_dirs(settings):
        if not base.exists():
            found.append(SeedSource("skill-dir", base, base.name, exists=False))
            continue
        skill_files = (
            [base / "SKILL.md"] if (base / "SKILL.md").exists() else sorted(base.glob("*/SKILL.md"))
        )
        for skill in skill_files:
            real = skill.resolve()
            if real in seen:
                continue
            seen.add(real)
            fm = read_frontmatter(skill)
            found.append(
                SeedSource(
                    "skill",
                    skill.parent,
                    str(fm.get("name") or skill.parent.name),
                    str(fm.get("description") or "")[:200],
                )
            )
    for doc in doctrine_files(settings):
        found.append(SeedSource("doctrine", doc, doc.name, exists=doc.exists()))
    mem = memory_dir()
    if mem.exists():
        for path in sorted(mem.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            fm = read_frontmatter(path)
            mtype = str((fm.get("metadata") or {}).get("type") or fm.get("type") or "")
            found.append(
                SeedSource(
                    "memory",
                    path,
                    str(fm.get("name") or path.stem),
                    f"[{mtype}] {fm.get('description', '')}"[:200],
                )
            )
    return found


def write_index(sources: list[SeedSource], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_by": "cube seed", "sources": [s.as_dict() for s in sources]}
    out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
