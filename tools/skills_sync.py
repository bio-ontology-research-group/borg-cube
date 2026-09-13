#!/usr/bin/env python3
"""Sync shared references from corpus/distilled into skills and refresh grounding.

For every skill with ``references/manifest.txt`` (one distilled topic per line),
copy ``corpus/distilled/<topic>.md`` to ``skills/<skill>/references/<topic>.md``.
Then set ``metadata.grounding`` in SKILL.md to the sorted union of the ids
cited in the Sources blocks of all ``references/*.md``.

``--check`` performs no writes and exits 1 on any drift (a reference that
differs from its distilled original, or a grounding list that is stale).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillslib import (  # noqa: E402
    DEFAULT_DISTILLED,
    DEFAULT_SKILLS_DIR,
    ToolError,
    discover_skills,
    grounding_ids,
    parse_frontmatter,
    parse_sources_block,
    read_sync_manifest,
    reference_files,
)


@dataclass
class SyncAction:
    skill: str
    kind: str  # "copy" | "grounding" | "error"
    detail: str


def union_reference_ids(skill_dir: Path) -> list[str]:
    ids: set[str] = set()
    for ref in reference_files(skill_dir):
        body = parse_frontmatter(ref.read_text(encoding="utf-8")).body
        found, _ = parse_sources_block(body)
        ids.update(found)
    return sorted(ids)


def set_grounding(skill_md_text: str, ids: list[str]) -> str:
    """Return SKILL.md text with ``metadata.grounding`` set to ``ids`` (inline form).

    The edit is line-based so comments and key order in the frontmatter survive.
    """
    fm = parse_frontmatter(skill_md_text)
    if fm.end_line < 0:
        raise ToolError("SKILL.md has no frontmatter")
    lines = skill_md_text.splitlines(keepends=True)
    value = ", ".join(ids)
    end = fm.end_line
    grounding_idx = None
    metadata_idx = None
    for i in range(1, end):
        stripped = lines[i].rstrip("\n")
        if re.match(r"^metadata:\s*$", stripped):
            metadata_idx = i
        if re.match(r"^\s+grounding:", stripped) and metadata_idx is not None:
            grounding_idx = i
            break
    if grounding_idx is not None:
        indent = re.match(r"^(\s*)", lines[grounding_idx]).group(1)  # type: ignore[union-attr]
        # drop a following block list, if grounding was written as one
        j = grounding_idx + 1
        while j < end and re.match(rf"^{indent}\s+-\s", lines[j]):
            j += 1
        lines[grounding_idx:j] = [f"{indent}grounding: {value}\n"]
    elif metadata_idx is not None:
        lines.insert(metadata_idx + 1, f"  grounding: {value}\n")
    else:
        lines.insert(end, "metadata:\n")
        lines.insert(end + 1, f"  grounding: {value}\n")
    return "".join(lines)


def sync_skill(skill_dir: Path, distilled: Path, check: bool, dry_run: bool) -> list[SyncAction]:
    name = skill_dir.name
    actions: list[SyncAction] = []
    for topic in read_sync_manifest(skill_dir):
        src = distilled / f"{topic}.md"
        dst = skill_dir / "references" / f"{topic}.md"
        if not src.exists():
            actions.append(SyncAction(name, "error", f"corpus/distilled/{topic}.md does not exist"))
            continue
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            continue
        actions.append(SyncAction(name, "copy", f"{src} -> {dst}"))
        if not check and not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    metadata = fm.data.get("metadata") if isinstance(fm.data.get("metadata"), dict) else {}
    current = grounding_ids(metadata)
    wanted = (
        union_reference_ids(skill_dir)
        if not (check or dry_run)
        else _expected_union(skill_dir, distilled)
    )
    if sorted(current) != wanted:
        actions.append(SyncAction(name, "grounding", f"{sorted(current)} -> {wanted}"))
        if not check and not dry_run:
            skill_md.write_text(set_grounding(text, wanted), encoding="utf-8")
    return actions


def _expected_union(skill_dir: Path, distilled: Path) -> list[str]:
    """Union of ids as it would be after syncing (reads distilled originals)."""
    ids: set[str] = set()
    synced = set(read_sync_manifest(skill_dir))
    for ref in reference_files(skill_dir):
        if ref.stem in synced:
            continue
        found, _ = parse_sources_block(parse_frontmatter(ref.read_text(encoding="utf-8")).body)
        ids.update(found)
    for topic in synced:
        src = distilled / f"{topic}.md"
        if src.exists():
            found, _ = parse_sources_block(parse_frontmatter(src.read_text(encoding="utf-8")).body)
            ids.update(found)
    return sorted(ids)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    p.add_argument("--distilled", type=Path, default=DEFAULT_DISTILLED)
    p.add_argument("--skill", action="append", default=[], help="limit to this skill (repeatable)")
    p.add_argument(
        "--check", action="store_true", help="report drift, write nothing, exit 1 on drift"
    )
    p.add_argument("--dry-run", action="store_true", help="print actions without writing")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skills = discover_skills(args.skills_dir)
    if args.skill:
        skills = [s for s in skills if s.name in set(args.skill)]
        missing = set(args.skill) - {s.name for s in skills}
        if missing:
            print(f"skills-sync: unknown skill(s) {sorted(missing)}", file=sys.stderr)
            return 1
    actions: list[SyncAction] = []
    for skill_dir in skills:
        actions += sync_skill(skill_dir, args.distilled, check=args.check, dry_run=args.dry_run)
    if args.json:
        print(json.dumps([asdict(a) for a in actions], indent=2))
    else:
        verb = "would" if (args.check or args.dry_run) else "did"
        for a in actions:
            print(f"{a.kind:9} {a.skill}: {a.detail}")
        print(f"skills-sync: {len(actions)} action(s) {verb} apply across {len(skills)} skill(s)")
    errors = [a for a in actions if a.kind == "error"]
    if errors:
        return 1
    if args.check and actions:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
