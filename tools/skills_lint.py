#!/usr/bin/env python3
"""Lint borg-cube skills against the agentskills.io spec and the house rules.

Checks (see doc/plan.md, "Skill quality gates"):

* spec: SKILL.md frontmatter (name matches directory, lowercase-hyphen, <= 64
  chars; description 1..1024 chars; only allowed keys), SKILL.md <= 500 lines
  and about 5000 tokens.
* grounding: ``metadata.grounding`` lists >= 3 manifest ids (>= 5 for advisor
  and lecturer skills and for the writing skills); every id exists in
  ``corpus/sources.yaml`` and is cited in a ``references/*.md`` Sources block.
* references: every references file starts with a Sources block; synced files
  match ``corpus/distilled/<topic>.md`` byte for byte.
* style: no U+2014, no banned meta phrases, sentence-case headings.
* hermes: ``metadata.hermes.category`` and ``metadata.borg-role`` in their sets.
* scripts: every ``scripts/*.py`` imports stdlib + pyyaml only, answers
  ``--help`` with exit 0, and has a test under ``tests/skills/``.

Exit status is 1 when any error was found, unless ``--report`` is given.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillslib import (  # noqa: E402
    DEFAULT_DISTILLED,
    DEFAULT_MANIFEST,
    DEFAULT_SKILLS_DIR,
    DEFAULT_TESTS_DIR,
    EM_DASH,
    HEADING_RE,
    SKILL_NAME_RE,
    ToolError,
    discover_skills,
    grounding_ids,
    load_manifest,
    parse_frontmatter,
    parse_sources_block,
    read_sync_manifest,
    reference_files,
    sources_block_is_first,
    token_estimate,
    validate_manifest,
)

ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_COMPATIBILITY_LEN = 500
MAX_SKILL_LINES = 500
MAX_SKILL_TOKENS = 5000

HERMES_CATEGORIES = {"advising", "research", "teaching", "software", "lead", "infra", "admin"}
BORG_ROLES = {"advisor", "researcher", "lecturer", "auditor", "lead", "infra"}
HIGH_GROUNDING_ROLES = {"advisor", "lecturer"}
WRITING_SKILLS = {
    "paper-writing",
    "thesis-writing",
    "literature-review",
    "response-to-reviewers",
    "grant-writing",
}
MIN_GROUNDING = 3
MIN_GROUNDING_HIGH = 5

BANNED_PHRASES: list[tuple[str, re.Pattern[str]]] = [
    ("Note that", re.compile(r"\bNote that\b", re.IGNORECASE)),
    ("Key insight", re.compile(r"\bKey insights?\b", re.IGNORECASE)),
    ("Importantly", re.compile(r"\bImportantly\b", re.IGNORECASE)),
    ("Honest", re.compile(r"\bHonest\b")),
]

TITLE_CASE_ALLOW = {
    "Robert",
    "Hoehndorf",
    "KAUST",
    "CEMSE",
    "Hermes",
    "Claude",
    "Codex",
    "Beads",
    "Python",
    "GitHub",
    "Crossref",
    "PLOS",
    "BORG",
    "Markdown",
    "Anthropic",
    "Emacs",
    "Org",
    "Mattermost",
    "Zenodo",
    "JOSS",
    "English",
    "American",
    "British",
    "Carpentries",
    "Turing",
    "Way",
    "Vitae",
    "IBEX",
    "Scrum",
    "Google",
    "Bash",
    "Linux",
    "Docker",
    "Slurm",
    "I",
    "Wave",
    "Phase",
    "Sources",
    "Grounding",
}

STDLIB_MODULES = set(sys.stdlib_module_names) | {"yaml", "__future__"}


@dataclass
class Finding:
    skill: str
    level: str  # "error" | "warning"
    check: str
    message: str
    path: str | None = None


@dataclass
class LintContext:
    manifest_path: Path = DEFAULT_MANIFEST
    distilled_dir: Path = DEFAULT_DISTILLED
    tests_dir: Path = DEFAULT_TESTS_DIR
    spec_only: bool = False
    run_scripts: bool = True
    allowlist: set[str] = field(default_factory=lambda: set(TITLE_CASE_ALLOW))
    _manifest_ids: set[str] | None = None
    _manifest_problems: list[str] | None = None

    def manifest_ids(self) -> set[str]:
        if self._manifest_ids is None:
            sources = load_manifest(self.manifest_path)
            self._manifest_problems = validate_manifest(sources)
            self._manifest_ids = {s.id for s in sources}
        return self._manifest_ids

    def manifest_problems(self) -> list[str]:
        self.manifest_ids()
        return list(self._manifest_problems or [])


@dataclass
class LintResult:
    findings: list[Finding]
    skills: list[str]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "skills": self.skills,
            "findings": [asdict(f) for f in self.findings],
            "summary": {"errors": len(self.errors), "warnings": len(self.warnings)},
        }


# --------------------------------------------------------------------------- spec checks


def check_spec(skill_dir: Path) -> tuple[list[Finding], dict[str, Any]]:
    """agentskills.io conformance. Returns findings and the parsed frontmatter."""
    name = skill_dir.name
    out: list[Finding] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        out.append(Finding(name, "error", "spec.skill-md", "SKILL.md missing"))
        return out, {}
    text = skill_md.read_text(encoding="utf-8")
    try:
        fm = parse_frontmatter(text)
    except ToolError as exc:
        out.append(Finding(name, "error", "spec.frontmatter", str(exc), str(skill_md)))
        return out, {}
    data = fm.data
    if fm.end_line < 0:
        out.append(Finding(name, "error", "spec.frontmatter", "no YAML frontmatter", str(skill_md)))
        return out, {}

    unknown = sorted(set(data) - ALLOWED_FRONTMATTER_KEYS)
    if unknown:
        out.append(
            Finding(
                name, "error", "spec.keys", f"unknown frontmatter keys: {unknown}", str(skill_md)
            )
        )

    fm_name = data.get("name")
    if not isinstance(fm_name, str) or not fm_name:
        out.append(Finding(name, "error", "spec.name", "name missing", str(skill_md)))
    else:
        if fm_name != name:
            out.append(
                Finding(name, "error", "spec.name", f"name {fm_name!r} != directory {name!r}")
            )
        if len(fm_name) > MAX_NAME_LEN:
            out.append(Finding(name, "error", "spec.name", f"name longer than {MAX_NAME_LEN}"))
        if not SKILL_NAME_RE.match(fm_name):
            out.append(
                Finding(
                    name,
                    "error",
                    "spec.name",
                    "name must be lowercase letters, digits and single hyphens",
                )
            )

    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        out.append(Finding(name, "error", "spec.description", "description missing or empty"))
    elif len(desc) > MAX_DESCRIPTION_LEN:
        out.append(
            Finding(
                name,
                "error",
                "spec.description",
                f"description is {len(desc)} chars (max {MAX_DESCRIPTION_LEN})",
            )
        )

    compat = data.get("compatibility")
    if compat is not None and (not isinstance(compat, str) or len(compat) > MAX_COMPATIBILITY_LEN):
        out.append(
            Finding(
                name, "error", "spec.compatibility", "compatibility must be a string <= 500 chars"
            )
        )
    if "license" in data and not isinstance(data["license"], str):
        out.append(Finding(name, "error", "spec.license", "license must be a string"))
    if "metadata" in data and not isinstance(data["metadata"], dict):
        out.append(Finding(name, "error", "spec.metadata", "metadata must be a mapping"))
    if "allowed-tools" in data and not isinstance(data["allowed-tools"], str):
        out.append(Finding(name, "error", "spec.allowed-tools", "allowed-tools must be a string"))

    n_lines = len(text.splitlines())
    if n_lines > MAX_SKILL_LINES:
        out.append(
            Finding(
                name, "error", "spec.size", f"SKILL.md has {n_lines} lines (max {MAX_SKILL_LINES})"
            )
        )
    tokens = token_estimate(text)
    if tokens > MAX_SKILL_TOKENS:
        out.append(
            Finding(
                name,
                "error",
                "spec.size",
                f"SKILL.md is about {tokens} tokens (max {MAX_SKILL_TOKENS}, 4 chars/token)",
            )
        )
    return out, data


# --------------------------------------------------------------------------- style checks


def _strip_code(text: str) -> str:
    """Blank out fenced code blocks and inline code spans, keeping line count."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        out.append(re.sub(r"`[^`]*`", "", line))
    return "\n".join(out)


def heading_is_title_case(text: str, allow: set[str]) -> bool:
    """Heuristic: a capitalised ordinary word after the first word means Title Case.

    Words in ``allow`` (proper nouns, acronyms) and capitalised words directly
    following one of them ("Claude Code") are ignored, as are words after a
    colon or sentence end, and tokens that look like code or contain digits.
    """
    words = re.sub(r"`[^`]*`", "", text).split()
    if len(words) < 2:
        return False
    prev = words[0]
    prev_is_name = words[0].strip("\"'()[]{}:;,.!?*_") in allow
    for word in words[1:]:
        bare = word.strip("\"'()[]{}:;,.!?*_")
        starts_sentence = prev.endswith((":", ".", "?", "!"))
        prev = word
        if not bare:
            prev_is_name = False
            continue
        is_acronym = bare.isupper() and len(bare) >= 2
        is_name = bare in allow or is_acronym
        if starts_sentence or is_name or prev_is_name:
            prev_is_name = is_name or (prev_is_name and bool(re.match(r"^[A-Z]", bare)))
            continue
        prev_is_name = False
        if any(ch in bare for ch in "./_@") or any(ch.isdigit() for ch in bare):
            continue
        if re.match(r"^[A-Z][a-z]", bare):
            return True
    return False


def check_style(skill_dir: Path, allow: set[str]) -> list[Finding]:
    name = skill_dir.name
    out: list[Finding] = []
    for path in sorted(skill_dir.rglob("*.md")):
        rel = str(path.relative_to(skill_dir))
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                out.append(
                    Finding(name, "error", "style.em-dash", f"{rel}:{i}: U+2014 em-dash", rel)
                )
        fm = parse_frontmatter(text) if text.startswith("---") else None
        body_offset = (fm.end_line + 1) if fm else 0
        body = "\n".join(text.splitlines()[body_offset:])
        prose = _strip_code(body)
        for i, line in enumerate(prose.splitlines(), body_offset + 1):
            for label, pattern in BANNED_PHRASES:
                if pattern.search(line):
                    out.append(
                        Finding(name, "error", "style.banned-phrase", f"{rel}:{i}: {label!r}", rel)
                    )
            m = HEADING_RE.match(line)
            if m and heading_is_title_case(m.group(2), allow):
                out.append(
                    Finding(
                        name,
                        "error",
                        "style.title-case",
                        f"{rel}:{i}: heading looks Title Case: {m.group(2)!r}",
                        rel,
                    )
                )
    return out


# --------------------------------------------------------------------------- grounding


def check_grounding(skill_dir: Path, data: dict[str, Any], ctx: LintContext) -> list[Finding]:
    name = skill_dir.name
    out: list[Finding] = []
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    try:
        ids = grounding_ids(metadata)
    except ToolError as exc:
        return [Finding(name, "error", "grounding.format", str(exc))]
    try:
        known = ctx.manifest_ids()
    except ToolError as exc:
        return [Finding(name, "error", "grounding.manifest", str(exc))]
    for problem in ctx.manifest_problems():
        out.append(Finding("corpus", "error", "manifest.schema", problem))

    role = metadata.get("borg-role")
    needed = (
        MIN_GROUNDING_HIGH
        if (role in HIGH_GROUNDING_ROLES or name in WRITING_SKILLS)
        else MIN_GROUNDING
    )
    if len(ids) < needed:
        out.append(
            Finding(
                name,
                "error",
                "grounding.count",
                f"metadata.grounding has {len(ids)} ids, needs >= {needed}",
            )
        )
    if len(set(ids)) != len(ids):
        out.append(Finding(name, "error", "grounding.duplicate", "duplicate grounding ids"))

    cited: set[str] = set()
    for ref in reference_files(skill_dir):
        body = parse_frontmatter(ref.read_text(encoding="utf-8")).body
        ref_ids, _ = parse_sources_block(body)
        cited.update(ref_ids)
    for gid in ids:
        if gid not in known:
            out.append(Finding(name, "error", "grounding.unknown", f"{gid!r} not in manifest"))
        if gid not in cited:
            out.append(
                Finding(
                    name,
                    "error",
                    "grounding.uncited",
                    f"{gid!r} not cited in any references/*.md Sources block",
                )
            )
    return out


def check_references(skill_dir: Path, ctx: LintContext) -> list[Finding]:
    name = skill_dir.name
    out: list[Finding] = []
    refs = reference_files(skill_dir)
    try:
        known = ctx.manifest_ids()
    except ToolError:
        known = set()
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for ref in refs:
        rel = f"references/{ref.name}"
        fm = parse_frontmatter(ref.read_text(encoding="utf-8"))
        if not sources_block_is_first(fm.body):
            out.append(
                Finding(
                    name,
                    "error",
                    "references.sources-block",
                    f"{rel} must begin with a Sources block",
                    rel,
                )
            )
        ids, _ = parse_sources_block(fm.body)
        for rid in ids:
            if known and rid not in known:
                out.append(
                    Finding(
                        name,
                        "error",
                        "references.unknown-id",
                        f"{rel}: {rid!r} not in manifest",
                        rel,
                    )
                )
        if ref.name not in skill_text:
            out.append(
                Finding(
                    name,
                    "error",
                    "references.unlisted",
                    f"{rel} is not mentioned in SKILL.md (Grounding section)",
                    rel,
                )
            )
        if fm.data and fm.data.get("reviewed_by") in (None, "", "unreviewed"):
            out.append(
                Finding(
                    name, "warning", "references.unreviewed", f"{rel} has no reviewed_by line", rel
                )
            )
    for topic in read_sync_manifest(skill_dir):
        src = ctx.distilled_dir / f"{topic}.md"
        dst = skill_dir / "references" / f"{topic}.md"
        if not src.exists():
            out.append(
                Finding(name, "error", "references.drift", f"corpus/distilled/{topic}.md missing")
            )
        elif not dst.exists():
            out.append(
                Finding(
                    name,
                    "error",
                    "references.drift",
                    f"references/{topic}.md not synced (run skills-sync)",
                )
            )
        elif src.read_bytes() != dst.read_bytes():
            out.append(
                Finding(
                    name,
                    "error",
                    "references.drift",
                    f"references/{topic}.md differs from corpus/distilled/{topic}.md",
                )
            )
    return out


def check_hermes(skill_dir: Path, data: dict[str, Any]) -> list[Finding]:
    name = skill_dir.name
    out: list[Finding] = []
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    role = metadata.get("borg-role")
    if role is not None and role not in BORG_ROLES:
        out.append(
            Finding(
                name, "error", "hermes.borg-role", f"borg-role {role!r} not in {sorted(BORG_ROLES)}"
            )
        )
    hermes = metadata.get("hermes")
    if not isinstance(hermes, dict) or "category" not in hermes:
        out.append(Finding(name, "error", "hermes.category", "metadata.hermes.category missing"))
    elif hermes["category"] not in HERMES_CATEGORIES:
        out.append(
            Finding(
                name,
                "error",
                "hermes.category",
                f"category {hermes['category']!r} not in {sorted(HERMES_CATEGORIES)}",
            )
        )
    return out


# --------------------------------------------------------------------------- scripts


def script_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_covers_script(tests_dir: Path, skill: str, script: Path) -> bool:
    if not tests_dir.is_dir():
        return False
    stem = script.stem
    for test in tests_dir.rglob("test_*.py"):
        if stem in test.stem:
            return True
        try:
            text = test.read_text(encoding="utf-8")
        except OSError:
            continue
        if script.name in text and skill in text:
            return True
    return False


def check_scripts(skill_dir: Path, ctx: LintContext) -> list[Finding]:
    name = skill_dir.name
    out: list[Finding] = []
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return out
    siblings = {p.stem for p in scripts_dir.glob("*.py")}
    for script in sorted(scripts_dir.glob("*.py")):
        rel = f"scripts/{script.name}"
        try:
            mods = script_imports(script)
        except SyntaxError as exc:
            out.append(Finding(name, "error", "scripts.syntax", f"{rel}: {exc}", rel))
            continue
        bad = sorted(m for m in mods if m not in STDLIB_MODULES and m not in siblings)
        if bad:
            out.append(
                Finding(name, "error", "scripts.imports", f"{rel}: non-stdlib imports {bad}", rel)
            )
        if not test_covers_script(ctx.tests_dir, name, script):
            out.append(
                Finding(
                    name, "error", "scripts.untested", f"{rel}: no test under {ctx.tests_dir}", rel
                )
            )
        if ctx.run_scripts:
            try:
                proc = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if proc.returncode != 0:
                    out.append(
                        Finding(
                            name,
                            "error",
                            "scripts.help",
                            f"{rel}: --help exited {proc.returncode}",
                            rel,
                        )
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                out.append(
                    Finding(name, "error", "scripts.help", f"{rel}: --help failed: {exc}", rel)
                )
    return out


# --------------------------------------------------------------------------- seeded index


def check_seeded_index(skills_dir: Path) -> list[Finding]:
    """Warn when an entry of skills/seeded/index.yaml points at a missing path."""
    import yaml

    index = skills_dir / "seeded" / "index.yaml"
    if not index.exists():
        return []
    out: list[Finding] = []
    with index.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    for entry in data.get("skills", []):
        raw = entry.get("path")
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not (path / "SKILL.md").is_file():
            out.append(
                Finding(
                    "seeded",
                    "warning",
                    "seeded.missing",
                    f"{entry.get('name', '?')}: {raw} has no SKILL.md",
                )
            )
    return out


# --------------------------------------------------------------------------- driver


def lint_skill(skill_dir: Path, ctx: LintContext) -> list[Finding]:
    findings, data = check_spec(skill_dir)
    if not data and any(
        f.check.startswith("spec.skill-md") or f.check == "spec.frontmatter" for f in findings
    ):
        return findings
    if ctx.spec_only:
        return findings
    findings += check_style(skill_dir, ctx.allowlist)
    findings += check_hermes(skill_dir, data)
    findings += check_grounding(skill_dir, data, ctx)
    findings += check_references(skill_dir, ctx)
    findings += check_scripts(skill_dir, ctx)
    return findings


def load_allowlist(skills_dir: Path) -> set[str]:
    allow = set(TITLE_CASE_ALLOW)
    extra = skills_dir / "lint-allowlist.txt"
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            word = line.split("#", 1)[0].strip()
            if word:
                allow.add(word)
    return allow


def run_lint(paths: list[Path], ctx: LintContext, skills_dir: Path | None = None) -> LintResult:
    findings: list[Finding] = []
    names: list[str] = []
    seen_manifest_problem = False
    for skill_dir in paths:
        names.append(skill_dir.name)
        for f in lint_skill(skill_dir, ctx):
            if f.check == "manifest.schema":
                if seen_manifest_problem:
                    continue
            findings.append(f)
        seen_manifest_problem = seen_manifest_problem or any(
            f.check == "manifest.schema" for f in findings
        )
    if skills_dir is not None and not ctx.spec_only:
        findings += check_seeded_index(skills_dir)
    return LintResult(findings=findings, skills=names)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "paths", nargs="*", type=Path, help="skill directories (default: all under --skills-dir)"
    )
    p.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="corpus/sources.yaml")
    p.add_argument(
        "--distilled", type=Path, default=DEFAULT_DISTILLED, help="corpus/distilled directory"
    )
    p.add_argument(
        "--tests-dir", type=Path, default=DEFAULT_TESTS_DIR, help="where script tests live"
    )
    p.add_argument(
        "--spec-only", action="store_true", help="agentskills.io checks only (for foreign skills)"
    )
    p.add_argument(
        "--no-run-scripts", action="store_true", help="do not execute scripts/*.py --help"
    )
    p.add_argument("--report", action="store_true", help="print findings but always exit 0")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = [p.resolve() for p in args.paths] or discover_skills(args.skills_dir)
    ctx = LintContext(
        manifest_path=args.manifest,
        distilled_dir=args.distilled,
        tests_dir=args.tests_dir,
        spec_only=args.spec_only,
        run_scripts=not args.no_run_scripts,
        allowlist=load_allowlist(args.skills_dir),
    )
    result = run_lint(paths, ctx, skills_dir=None if args.paths else args.skills_dir)
    if args.json:
        print(json.dumps(result.to_json(), indent=2))
    else:
        for f in result.findings:
            print(f"{f.level.upper():7} {f.skill}: [{f.check}] {f.message}")
        status = "ok" if result.ok else "FAILED"
        print(
            f"skills-lint: {len(result.skills)} skill(s), {len(result.errors)} error(s), "
            f"{len(result.warnings)} warning(s): {status}"
        )
    if args.report:
        return 0
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
