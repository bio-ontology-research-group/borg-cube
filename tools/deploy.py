#!/usr/bin/env python3
"""Deploy borg-cube skills to the runtimes.

* Claude Code: symlink ``~/.claude/skills/<skill>`` -> ``skills/<skill>``.
* Codex: ``rsync -a --delete`` copy into ``~/.codex/skills/<skill>/``.
* Hermes (``--hermes HOST[:profile]``): rsync into
  ``HOST:~/.hermes[/profiles/<profile>]/skills/<category>/<skill>/`` where the
  category is ``metadata.hermes.category``.

The tool refuses to deploy unless ``skills_lint`` passes. Dry-run is the
default and prints every action; ``--apply`` executes them.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import skills_lint  # noqa: E402
from skillslib import (  # noqa: E402
    DEFAULT_DISTILLED,
    DEFAULT_MANIFEST,
    DEFAULT_SKILLS_DIR,
    DEFAULT_TESTS_DIR,
    ToolError,
    discover_skills,
    parse_frontmatter,
)

RSYNC_EXCLUDES = ["--exclude", "__pycache__", "--exclude", "*.pyc", "--exclude", ".pytest_cache"]


@dataclass
class Action:
    skill: str
    kind: str  # symlink | rsync | ssh | skip
    description: str
    argv: list[str] | None = None


def hermes_category(skill_dir: Path) -> str:
    fm = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    metadata = fm.data.get("metadata") or {}
    hermes = metadata.get("hermes") or {}
    category = hermes.get("category")
    if not category:
        raise ToolError(f"{skill_dir.name}: metadata.hermes.category missing")
    return str(category)


def plan_claude(skill_dir: Path, claude_dir: Path) -> Action:
    dest = claude_dir / skill_dir.name
    if dest.is_symlink():
        if dest.resolve() == skill_dir.resolve():
            return Action(skill_dir.name, "skip", f"{dest} already links here")
        return Action(skill_dir.name, "symlink", f"relink {dest} -> {skill_dir}")
    if dest.exists():
        raise ToolError(f"{dest} exists and is not a symlink; move it away first")
    return Action(skill_dir.name, "symlink", f"symlink {dest} -> {skill_dir}")


def plan_codex(skill_dir: Path, codex_dir: Path) -> Action:
    dest = codex_dir / skill_dir.name
    argv = ["rsync", "-a", "--delete", *RSYNC_EXCLUDES, f"{skill_dir}/", f"{dest}/"]
    return Action(skill_dir.name, "rsync", f"rsync {skill_dir}/ -> {dest}/", argv)


def hermes_remote_dir(profile: str | None, category: str, skill: str) -> str:
    base = "~/.hermes" if not profile else f"~/.hermes/profiles/{profile}"
    return f"{base}/skills/{category}/{skill}"


def plan_hermes(skill_dir: Path, host: str, profile: str | None) -> list[Action]:
    category = hermes_category(skill_dir)
    remote = hermes_remote_dir(profile, category, skill_dir.name)
    return [
        Action(
            skill_dir.name,
            "ssh",
            f"ssh {host} mkdir -p {remote}",
            ["ssh", host, "mkdir", "-p", remote],
        ),
        Action(
            skill_dir.name,
            "rsync",
            f"rsync {skill_dir}/ -> {host}:{remote}/",
            ["rsync", "-a", "--delete", *RSYNC_EXCLUDES, f"{skill_dir}/", f"{host}:{remote}/"],
        ),
    ]


def execute(action: Action, claude_dir: Path) -> None:
    if action.kind == "skip":
        return
    if action.kind == "symlink":
        dest = claude_dir / action.skill
        target = Path(action.description.split(" -> ", 1)[1])
        claude_dir.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            dest.unlink()
        os.symlink(target, dest)
        return
    if action.argv is None:
        raise ToolError(f"action {action.kind} has no command")
    if action.kind == "rsync" and ":" not in action.argv[-1]:
        Path(action.argv[-1]).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(action.argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ToolError(f"{' '.join(action.argv)} failed: {proc.stderr.strip()}")


def parse_hermes(value: str | None) -> tuple[str, str | None] | None:
    if not value:
        return None
    host, _, profile = value.partition(":")
    if not host:
        raise ToolError("--hermes needs HOST[:profile]")
    return host, (profile or None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    p.add_argument(
        "--skill", action="append", default=[], help="deploy only this skill (repeatable)"
    )
    p.add_argument("--claude-dir", type=Path, default=Path("~/.claude/skills"))
    p.add_argument("--codex-dir", type=Path, default=Path("~/.codex/skills"))
    p.add_argument("--hermes", metavar="HOST[:profile]", help="also rsync to a Hermes host")
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--no-codex", action="store_true")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="passed to skills_lint")
    p.add_argument(
        "--distilled", type=Path, default=DEFAULT_DISTILLED, help="passed to skills_lint"
    )
    p.add_argument(
        "--tests-dir", type=Path, default=DEFAULT_TESTS_DIR, help="passed to skills_lint"
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print actions (default)")
    mode.add_argument("--apply", action="store_true", help="execute the actions")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skills = discover_skills(args.skills_dir)
    if args.skill:
        skills = [s for s in skills if s.name in set(args.skill)]
        missing = set(args.skill) - {s.name for s in skills}
        if missing:
            print(f"deploy: unknown skill(s) {sorted(missing)}", file=sys.stderr)
            return 1
    if not skills:
        print("deploy: no skills found", file=sys.stderr)
        return 1

    ctx = skills_lint.LintContext(
        manifest_path=args.manifest,
        distilled_dir=args.distilled,
        tests_dir=args.tests_dir,
        allowlist=skills_lint.load_allowlist(args.skills_dir),
    )
    lint = skills_lint.run_lint(skills, ctx)
    if not lint.ok:
        for f in lint.errors:
            print(f"LINT    {f.skill}: [{f.check}] {f.message}", file=sys.stderr)
        print("deploy: refusing, skills_lint failed", file=sys.stderr)
        return 1

    claude_dir = args.claude_dir.expanduser()
    codex_dir = args.codex_dir.expanduser()
    try:
        hermes = parse_hermes(args.hermes)
        actions: list[Action] = []
        for skill_dir in skills:
            if not args.no_claude:
                actions.append(plan_claude(skill_dir, claude_dir))
            if not args.no_codex:
                actions.append(plan_codex(skill_dir, codex_dir))
            if hermes:
                actions += plan_hermes(skill_dir, *hermes)
        if args.apply:
            for action in actions:
                execute(action, claude_dir)
    except ToolError as exc:
        print(f"deploy: {exc}", file=sys.stderr)
        return 1

    mode = "applied" if args.apply else "dry-run"
    if args.json:
        print(json.dumps({"mode": mode, "actions": [asdict(a) for a in actions]}, indent=2))
    else:
        for a in actions:
            print(f"{a.kind:8} {a.skill}: {a.description}")
        print(f"deploy: {len(actions)} action(s) {mode} for {len(skills)} skill(s)")
        if not args.apply:
            print("deploy: dry-run only; pass --apply to execute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
