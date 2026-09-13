#!/usr/bin/env python3
"""Turn audit facts into findings with severity, location, fix and sources, plus a fix list.

Each rule maps a fact to a finding: severity per assets/severity-scale.md,
location as file:line where the collector has one (otherwise the evidence
command), a one-line problem, a one-line fix and the corpus ids the rule rests
on (see references/*.md). The Markdown report is rendered from
assets/code-audit-report.md; ``--beads`` writes the fix list as beads JSON
shaped for the delegation skill. ``--published`` raises the severity of test
and documentation gaps for software that a paper cites.

The agent judgement pass (reading the code behind each finding, adding
findings the collector cannot see, deciding what is info in context) happens
after this script and is written into the Judgement section.

Example:
  audit_report.py --facts runs/12/facts.json --out runs/12/audit.md \
      --beads runs/12/fixes.json --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "code-audit-report.md"
ORDER = ("high", "medium", "low", "info")

SW = ["wilson2014", "wilson2017", "taschuk-wilson2017", "hunter-zinck2021"]
DOC = ["lee2018-documenting", "list2017", "joss-review-checklist"]
FAIR = [
    "fair4rs2022",
    "jimenez2017",
    "joss-review-criteria",
    "citation-file-format",
    "smith2016-software-citation",
]
SEC = ["owasp-top-ten", "cwe-top25", "openssf-scorecard"]
DOCKER = ["nust2020"]


def finding(
    fid: str,
    severity: str,
    location: str,
    problem: str,
    fix: str,
    sources: list[str],
    owner: str = "programmer",
) -> dict[str, Any]:
    return {
        "id": fid,
        "severity": severity,
        "location": location,
        "problem": problem,
        "fix": fix,
        "sources": sources,
        "owner_role": owner,
    }


def raise_if(published: bool, severity: str) -> str:
    if not published:
        return severity
    return {"low": "medium", "medium": "high"}.get(severity, severity)


def derive(
    facts: dict[str, Any], published: bool
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    f: list[dict[str, Any]] = []
    passed: list[str] = []
    not_checked: list[str] = []
    docs = facts.get("docs", {})
    g = facts.get("git", {})
    tests = facts.get("tests", {})
    ci = facts.get("ci", {})
    deps = facts.get("dependencies", {})
    files = facts.get("files", {})
    issues = facts.get("issues", {})

    # secrets and risky calls
    for s in facts.get("secrets", []):
        f.append(
            finding(
                f"secret:{s['file']}:{s['line']}",
                "high",
                f"{s['file']}:{s['line']}",
                f"possible {s['pattern']} committed ({s['match']})",
                "remove the value, rotate the credential, move it to a gitignored .env, and purge "
                "it from history; report to Robert only",
                SEC,
                owner="robert",
            )
        )
    if not facts.get("secrets"):
        passed.append("no secret patterns in tracked text files")
    for r in facts.get("risky_calls", []):
        loc = f"{r['file']}:{r['line']}"
        if r.get("in_test"):
            f.append(
                finding(
                    f"risk:{loc}",
                    "info",
                    loc,
                    f"{r['pattern']} in a test file",
                    "confirm the input is fixed test data; no change needed if so",
                    SEC,
                )
            )
            continue
        if r["pattern"] in ("eval", "exec", "shell-true", "os-system", "curl-pipe-sh"):
            f.append(
                finding(
                    f"risk:{loc}",
                    "high",
                    loc,
                    f"{r['pattern']}: {r['snippet']}",
                    "pass an argument list without a shell, or validate and quote the input; if "
                    "the input is a constant, downgrade to info with the reason",
                    SEC + ["hunter-zinck2021"],
                )
            )
        elif r["pattern"] in ("pickle-load", "yaml-unsafe-load"):
            f.append(
                finding(
                    f"risk:{loc}",
                    "medium",
                    loc,
                    f"{r['pattern']} deserialises untrusted data: {r['snippet']}",
                    "use yaml.safe_load, or load only files produced by this software and verify a "
                    "checksum before unpickling",
                    SEC,
                )
            )
        elif r["pattern"] == "verify-false":
            f.append(
                finding(
                    f"risk:{loc}",
                    "medium",
                    loc,
                    f"TLS verification disabled: {r['snippet']}",
                    "remove verify=False; pin the CA bundle if the server certificate is private",
                    SEC,
                )
            )
        else:
            f.append(
                finding(
                    f"risk:{loc}",
                    "low",
                    loc,
                    f"{r['pattern']}: {r['snippet']}",
                    "restrict permissions to what the step needs",
                    SEC,
                )
            )

    # license and citation
    if not docs.get("license"):
        f.append(
            finding(
                "license:missing",
                "high",
                "repository root",
                "no LICENSE file; without one all rights are reserved and nobody may reuse the "
                "code",
                "add an OSI-approved license file (MIT, Apache-2.0 or BSD-3-Clause unless a "
                "dependency forces GPL) and name it in README",
                FAIR + ["wilson2017"],
            )
        )
    elif docs["license"].get("type") == "unknown":
        f.append(
            finding(
                "license:unknown",
                "medium",
                docs["license"]["path"],
                "license text not recognised as a standard license",
                "replace with the exact text of a standard license so tools and readers can "
                "identify it",
                FAIR,
            )
        )
    else:
        passed.append(f"LICENSE present ({docs['license']['type']})")
    cff = docs.get("citation_cff")
    if not cff:
        f.append(
            finding(
                "citation:missing",
                raise_if(published, "low"),
                "repository root",
                "no CITATION.cff",
                "add CITATION.cff with cff-version, title, authors, version, date-released and the "
                "DOI of the release or paper",
                FAIR,
            )
        )
    elif not cff.get("parseable"):
        f.append(
            finding(
                "citation:invalid",
                "medium",
                cff["path"],
                "CITATION.cff does not parse as YAML",
                "validate with cffconvert and fix the syntax",
                FAIR,
            )
        )
    else:
        missing = [k for k in ("cff-version", "title", "authors") if k not in cff.get("fields", [])]
        if missing:
            f.append(
                finding(
                    "citation:fields",
                    "low",
                    cff["path"],
                    f"CITATION.cff lacks {', '.join(missing)}",
                    "add the missing fields",
                    FAIR,
                )
            )
        else:
            passed.append("CITATION.cff present and parseable")

    # README
    readme = docs.get("readme")
    if not readme:
        f.append(
            finding(
                "readme:missing",
                "high",
                "repository root",
                "no README",
                "add a README with purpose, installation, one runnable example, how to cite and "
                "the license",
                DOC + ["wilson2017"],
            )
        )
    else:
        sec = readme.get("sections", {})
        if not sec.get("install"):
            f.append(
                finding(
                    "readme:install",
                    raise_if(published, "medium"),
                    readme["path"],
                    "README has no installation or requirements section",
                    "add an Installation section with the exact commands and the supported Python "
                    "or Java versions",
                    DOC,
                )
            )
        if not sec.get("usage"):
            f.append(
                finding(
                    "readme:usage",
                    raise_if(published, "medium"),
                    readme["path"],
                    "README has no usage or example section",
                    "add one complete, copy-pasteable example with expected output",
                    DOC,
                )
            )
        if not sec.get("cite") and not cff:
            f.append(
                finding(
                    "readme:cite",
                    "low",
                    readme["path"],
                    "README does not say how to cite the software",
                    "add a How to cite section pointing to the DOI or CITATION.cff",
                    FAIR,
                )
            )
        if readme.get("lines", 0) < 15:
            f.append(
                finding(
                    "readme:short",
                    "low",
                    readme["path"],
                    f"README is {readme.get('lines')} lines",
                    "describe purpose, inputs, outputs and limitations",
                    DOC,
                )
            )
        if all(sec.get(k) for k in ("install", "usage")):
            passed.append("README has installation and usage sections")

    # tests and CI
    if tests.get("source_files"):
        if tests.get("test_files", 0) == 0:
            f.append(
                finding(
                    "tests:none",
                    raise_if(published, "medium"),
                    "repository",
                    "no test files found",
                    "add tests for the main entry points (a smoke test on a small input at "
                    "minimum) and run them in CI",
                    SW + ["osborne2014"],
                )
            )
        else:
            ratio = tests.get("ratio") or 0
            if ratio < 0.1:
                f.append(
                    finding(
                        "tests:ratio",
                        "low",
                        "repository",
                        f"{tests['test_files']} test files for {tests['source_files']} source "
                        f"files (ratio {ratio})",
                        "add tests for the modules a paper result depends on first",
                        SW,
                    )
                )
            else:
                passed.append(f"tests present (ratio {ratio})")
    else:
        not_checked.append("tests: no source files in a recognised language")
    if not ci.get("configs"):
        f.append(
            finding(
                "ci:none",
                "medium",
                "repository",
                "no continuous integration configuration",
                "add a workflow that installs the package and runs the tests on every push and "
                "pull request",
                SW + ["openssf-scorecard"],
            )
        )
    else:
        passed.append(f"CI configured ({', '.join(ci['configs'][:3])})")
    for a in ci.get("actions", []):
        if not a.get("pinned_sha"):
            f.append(
                finding(
                    f"ci:unpinned:{a['file']}:{a['line']}",
                    "medium",
                    f"{a['file']}:{a['line']}",
                    f"action {a['uses']} pinned to a tag or branch, not a commit SHA",
                    "pin to the full commit SHA with the version in a comment; enable Dependabot "
                    "for actions",
                    ["openssf-scorecard"],
                )
            )
    for d in ci.get("dangerous", []):
        f.append(
            finding(
                f"ci:dangerous:{d['file']}:{d['line']}",
                "high",
                f"{d['file']}:{d['line']}",
                f"dangerous workflow pattern {d['pattern']}",
                "do not run untrusted code or interpolate event data in run steps under "
                "pull_request_target; use pull_request with restricted permissions",
                ["openssf-scorecard", "owasp-top-ten"],
            )
        )

    # dependencies
    if not deps.get("manifests"):
        f.append(
            finding(
                "deps:none",
                "medium",
                "repository",
                "no dependency manifest (pyproject.toml, requirements.txt, environment.yml, ...)",
                "declare dependencies with versions in a manifest file",
                SW + ["nust2020"],
            )
        )
    else:
        specs = deps.get("pinned_specs", 0) + deps.get("unpinned_specs", 0)
        if (
            specs
            and not deps.get("lock_files")
            and deps.get("unpinned_specs", 0) > deps.get("pinned_specs", 0)
        ):
            f.append(
                finding(
                    "deps:unpinned",
                    "medium",
                    ", ".join(deps["manifests"][:3]),
                    f"{deps['unpinned_specs']} of {specs} dependency specs unpinned and no lock "
                    "file",
                    "add a lock file (uv.lock, conda-lock.yml) or pin exact versions for the "
                    "release that a paper cites",
                    SW + ["nust2020", "openssf-scorecard"],
                )
            )
        elif deps.get("lock_files"):
            passed.append(f"lock file present ({', '.join(deps['lock_files'][:2])})")
    for u in deps.get("url_installs", []):
        f.append(
            finding(
                f"deps:url:{u['file']}:{u['line']}",
                "medium",
                f"{u['file']}:{u['line']}",
                f"dependency installed from a URL or git reference ({u.get('spec', '')})".rstrip(
                    "( )"
                ),
                "pin to a released version or a commit hash",
                ["openssf-scorecard", "nust2020"],
            )
        )

    # docker
    for d in facts.get("docker", {}).get("dockerfiles", []):
        for b in d.get("bases", []):
            if not b.get("pinned"):
                f.append(
                    finding(
                        f"docker:base:{d['file']}:{b['line']}",
                        "medium",
                        f"{d['file']}:{b['line']}",
                        f"base image {b['image']} not pinned to a version tag or digest",
                        "use an explicit version tag (or digest) for the base image",
                        DOCKER,
                    )
                )
        if not d.get("user_set"):
            f.append(
                finding(
                    f"docker:root:{d['file']}",
                    "low",
                    d["file"],
                    "container runs as root (no USER instruction)",
                    "add a non-root USER after installing dependencies",
                    DOCKER + ["owasp-top-ten"],
                )
            )
        for line in d.get("unpinned_pip_lines", []):
            f.append(
                finding(
                    f"docker:pip:{d['file']}:{line}",
                    "low",
                    f"{d['file']}:{line}",
                    "pip install without version pins in the image",
                    "install from a pinned requirements file",
                    DOCKER,
                )
            )

    # notebooks, large files, hygiene
    if files.get("notebooks_with_outputs"):
        nb = [n["file"] for n in files.get("notebooks", []) if n["code_cells_with_outputs"]][:5]
        f.append(
            finding(
                "notebooks:outputs",
                "low",
                ", ".join(nb),
                f"{files['notebooks_with_outputs']} notebook(s) committed with outputs",
                "strip outputs before committing (nbstripout as a pre-commit hook) and keep "
                "results as files",
                ["wilson2017", "taschuk-wilson2017"],
            )
        )
    for lf in files.get("large_files", []):
        f.append(
            finding(
                f"files:large:{lf['file']}",
                "medium",
                lf["file"],
                f"{lf['mb']} MB file tracked in git",
                "move data to a data repository or release asset and document how to fetch it",
                ["wilson2017", "openssf-scorecard"],
            )
        )
    if files.get("binary_count") and not files.get("large_files"):
        f.append(
            finding(
                "files:binaries",
                "low",
                ", ".join(b["file"] for b in files.get("binary_files", [])[:5]),
                f"{files['binary_count']} binary artifact(s) tracked",
                "generate them in CI or fetch them from a release; keep the repository to source",
                ["openssf-scorecard", "wilson2017"],
            )
        )
    for key, label in (
        ("contributing", "CONTRIBUTING"),
        ("security_md", "SECURITY.md"),
        ("code_of_conduct", "CODE_OF_CONDUCT"),
    ):
        if not docs.get(key):
            f.append(
                finding(
                    f"docs:{key}",
                    "low",
                    "repository root",
                    f"no {label}",
                    f"add {label} (how to report problems, how to contribute, how to reach the "
                    "maintainers)",
                    FAIR + ["sholler2019", "openssf-scorecard"],
                )
            )
        else:
            passed.append(f"{label} present")
    if not docs.get("changelog") and g.get("tags"):
        f.append(
            finding(
                "docs:changelog",
                "info",
                "repository root",
                "releases exist but no CHANGELOG",
                "keep a CHANGELOG with one entry per release",
                ["wilson2017"],
            )
        )
    if not g.get("tags"):
        f.append(
            finding(
                "release:none",
                raise_if(published, "low"),
                "git tags",
                "no release tag",
                "tag a release, archive it on Zenodo for a DOI, and record the version in "
                "CITATION.cff",
                FAIR,
            )
        )
    else:
        passed.append(f"release tag present ({g.get('last_tag')})")
    if (
        g.get("days_since_commit") is not None
        and g["days_since_commit"] > 365
        and (issues.get("open_issues") or 0) > 0
    ):
        f.append(
            finding(
                "maintenance:stale",
                "low",
                "git log",
                f"no commit for {g['days_since_commit']} days with {issues['open_issues']} open "
                "issues",
                "state the maintenance status in README (maintained, frozen, archived) and close "
                "or answer the issues",
                ["openssf-scorecard", "sholler2019"],
            )
        )
    if not g.get("gitignore"):
        f.append(
            finding(
                "git:no-gitignore",
                "low",
                "repository root",
                "no .gitignore",
                "add a .gitignore for build artifacts, environments and data",
                ["wilson2017"],
            )
        )
    if issues.get("open_issues") is None:
        not_checked.append(f"open issues: {issues.get('source') or 'not available'}")
    if not ci.get("configs"):
        not_checked.append("CI status: no configuration to query")
    else:
        not_checked.append(
            "CI run status: not queried by the collector; check the badge or gh run list"
        )
    not_checked.append(
        "correctness of results, code structure and naming: agent judgement pass, see Judgement"
    )
    return f, passed, not_checked


def render(
    facts: dict[str, Any],
    findings: list[dict[str, Any]],
    passed: list[str],
    not_checked: list[str],
    template: str,
    today: dt.date,
    published: bool,
) -> str:
    by_sev = {s: [x for x in findings if x["severity"] == s] for s in ORDER}

    def block(items: list[dict[str, Any]]) -> str:
        if not items:
            return "- none"
        return "\n".join(
            f"- [{x['severity']}] {x['location']}: {x['problem']}. Fix: {x['fix']}. Sources: "
            f"{', '.join(x['sources'])}"
            for x in items
        )

    counts = ", ".join(f"{len(by_sev[s])} {s}" for s in ORDER)
    g = facts.get("git", {})
    fixes = [x for x in findings if x["severity"] in ("high", "medium", "low")]
    values = {
        "REPO_NAME": facts.get("repo", {}).get("name", "?"),
        "REPO_PATH": facts.get("repo", {}).get("path", "?"),
        "REMOTE": g.get("remote") or "no remote",
        "COLLECTED": facts.get("collected", "?"),
        "GENERATED": today.isoformat(),
        "LAST_COMMIT": g.get("last_commit") or "unknown",
        "DAYS_SINCE_COMMIT": str(
            g.get("days_since_commit") if g.get("days_since_commit") is not None else "?"
        ),
        "FILE_COUNT": str(facts.get("files", {}).get("file_count", "?")),
        "LANGUAGES": ", ".join(
            f"{k} {v}" for k, v in facts.get("files", {}).get("languages", {}).items()
        )
        or "none detected",
        "CONTEXT": "published software (test and documentation gaps raised one level)"
        if published
        else "not marked as published; rerun with --published if a paper cites this software",
        "SUMMARY": f"{len(findings)} findings: {counts}. {len(passed)} checks passed. Checks "
        "version {facts.get('checks_version')}.",
        "HIGH": block(by_sev["high"]),
        "MEDIUM": block(by_sev["medium"]),
        "LOW": block(by_sev["low"]),
        "INFO": block(by_sev["info"]),
        "PASSED": "\n".join(f"- {p}" for p in passed) or "- none",
        "NOT_CHECKED": "\n".join(f"- {n}" for n in not_checked) or "- none",
        "FIXES": "\n".join(
            f"- [{x['severity']}] {x['id']}: {x['fix']} (owner {x['owner_role']})" for x in fixes
        )
        or "- none",
        "JUDGEMENT": "[to be written by the auditor after reading the code behind each finding; "
        "every added finding cites file:line]",
    }
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    return out.rstrip() + "\n"


def fix_beads(
    facts: dict[str, Any], findings: list[dict[str, Any]], today: dt.date
) -> dict[str, Any]:
    name = facts.get("repo", {}).get("name", "repo")
    prov = [
        f"audit of {facts.get('repo', {}).get('path')} on {facts.get('collected')} "
        f"(audit_collect.py {facts.get('checks_version')})"
    ]
    beads = []
    for x in findings:
        if x["severity"] not in ("high", "medium", "low"):
            continue
        beads.append(
            {
                "id": f"fix-{name}-{x['id']}".lower()
                .replace(":", "-")
                .replace("/", "-")
                .replace(".", "-")
                .replace(" ", "-")[:80],
                "title": f"{name}: {x['problem'][:90]}",
                "kind": "implement",
                "owner_role": x["owner_role"],
                "privacy": "internal" if x["owner_role"] == "robert" else "public",
                "objective": f"Resolve the {x['severity']} audit finding at {x['location']}: "
                "{x['problem']}",
                "output": "change in the repository plus a note in the bead; rerun "
                "audit_collect.py and audit_report.py",
                "acceptance_criteria": [
                    {
                        "check": f"finding {x['id']} is no longer reported by `audit_report.py "
                        "--facts <new facts>`",
                        "how": "command",
                    }
                ],
                "sources": [x["location"]] + [f"corpus:{s}" for s in x["sources"]],
                "out_of_scope": "any other finding; changes to results or behaviour beyond the fix",
                "provenance": prov,
                "severity": x["severity"],
                "fix": x["fix"],
                "depends_on": [],
                "deadline": None,
            }
        )
    return {
        "goal": f"resolve audit findings for {name}",
        "pattern": "parallel",
        "provenance": prov,
        "review_by": "senior",
        "generated": today.isoformat(),
        "beads": beads,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--facts", required=True, type=Path, help="JSON from audit_collect.py")
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p.add_argument("--out", type=Path, default=None, help="Markdown report path")
    p.add_argument("--beads", type=Path, default=None, help="write the fix list as beads JSON")
    p.add_argument(
        "--published",
        action="store_true",
        help="software is cited in a paper; raise test and documentation gaps",
    )
    p.add_argument(
        "--json", action="store_true", help="print findings as JSON instead of the report"
    )
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    p.add_argument("--apply", action="store_true", help="write --out and --beads (default: print)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        facts = json.loads(args.facts.read_text(encoding="utf-8"))
        template = args.template.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"audit-report: {exc}", file=sys.stderr)
        return 1
    today = args.today or dt.date.today()
    findings, passed, not_checked = derive(facts, args.published)
    findings.sort(key=lambda x: (ORDER.index(x["severity"]), x["location"]))
    if args.json:
        print(
            json.dumps(
                {"findings": findings, "passed": passed, "not_checked": not_checked}, indent=2
            )
        )
        return 0
    report = render(facts, findings, passed, not_checked, template, today, args.published)
    if "—" in report:
        print("audit-report: em-dash in output", file=sys.stderr)
        return 2
    if args.apply and args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        written = [str(args.out)]
        if args.beads:
            args.beads.parent.mkdir(parents=True, exist_ok=True)
            args.beads.write_text(
                json.dumps(fix_beads(facts, findings, today), indent=2) + "\n", encoding="utf-8"
            )
            written.append(str(args.beads))
        print(f"audit-report: {len(findings)} finding(s); wrote {', '.join(written)}")
    else:
        print(report, end="")
        if args.out or args.beads:
            print("\n[dry-run] rerun with --apply to write the report and fix list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
