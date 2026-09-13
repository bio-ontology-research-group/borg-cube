#!/usr/bin/env python3
"""Turn a research plan (YAML) into bead creation commands with provenance headers.

The plan holds the question, the competing hypotheses, an experiment matrix, the
risks and the checkpoints. Every experiment must name at least one baseline, a
success threshold and a kill criterion; every bead must carry at least one
acceptance criterion someone other than the owner can check. A plan that misses
any of these exits 2, names the item and the missing field, and writes nothing.

Each bead gets a stable xid (``experiment:<plan>:<id>``, ``risk:<plan>:<id>``,
``checkpoint:<plan>:<id>``) and a description that starts with the repository's
fenced YAML header (``xid``, ``provenance``, ``deadline``, ``privacy``), the same
shape ``cube.model.BeadHeader`` renders and parses. Labels follow the delegation
skill: ``kind:``, ``stage:``, ``privacy:``, ``role:``.

The script is a dry run by default: it prints the exact ``bd create`` commands
and runs nothing. ``--apply`` executes them in order.

Example:
  plan_to_beads.py --plan assets/plan.yaml.example
  plan_to_beads.py --plan runs/9/plan.yaml --json --out runs/9/beads.json
  plan_to_beads.py --plan runs/9/plan.yaml --apply
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROLES = {
    "group-leader",
    "senior",
    "programmer",
    "auditor",
    "editor",
    "lecturer",
    "scribe",
    "advisor",
    "sysadmin",
    "secretary",
    "sentinel",
    "marshal",
    "concierge",
    "robert",
}
PRIVACY = {"public", "internal", "local-only"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER_RE = re.compile(r"\d")
CHECKABLE_RE = re.compile(
    r"`[^`]+`|/|\d|\b(exit|exists?|passes|pass|fails?|equals?|contains?|matches|lists?|"
    r"reports?|returns?|confirms?|records?|at least|at most|no more than|above|below|"
    r"within|per|table|figure|file|column|row)\b",
    re.IGNORECASE,
)
STAGE = "design"


class PlanError(Exception):
    """The plan file cannot be read."""


# --------------------------------------------------------------------------- loading


def load_plan(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PlanError(f"{path}: plan must be a YAML mapping")
    for key in ("hypotheses", "experiments", "risks", "checkpoints"):
        value = data.get(key) or []
        if not isinstance(value, list):
            raise PlanError(f"{path}: '{key}' must be a list")
        data[key] = value
    return data


def as_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"\s*;\s*", value) if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


def provenance_entries(value: Any) -> list[dict[str, str]]:
    """``path::locator`` or ``{source, locator}`` to the header's provenance shape."""
    out: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else as_list(value):
        if isinstance(item, dict):
            entry = {k: str(v) for k, v in item.items() if v not in (None, "")}
            if entry.get("source"):
                out.append(entry)
            continue
        text = str(item).strip()
        if not text:
            continue
        if "::" in text:
            source, locator = text.split("::", 1)
            out.append({"source": source.strip(), "locator": locator.strip()})
        else:
            out.append({"source": text})
    return out


# --------------------------------------------------------------------------- validation


def checkable(text: str) -> bool:
    return bool(CHECKABLE_RE.search(text))


def _check_ids(items: list[dict[str, Any]], kind: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for n, item in enumerate(items, 1):
        ident = str(item.get("id") or "").strip()
        if not ident:
            errors.append(f"{kind}[{n}]: missing id")
            continue
        if not SLUG_RE.match(ident):
            errors.append(f"{kind} {ident}: id must be lowercase letters, digits and hyphens")
        if ident in seen:
            errors.append(f"{kind} {ident}: duplicate id")
        seen.add(ident)


def validate(plan: dict[str, Any], strict: bool) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors mean nothing is written."""
    errors: list[str] = []
    warnings: list[str] = []
    demand = errors if strict else warnings

    slug = str(plan.get("plan") or "").strip()
    if not slug:
        errors.append("plan: missing 'plan' (the slug used in every xid)")
    elif not SLUG_RE.match(slug):
        errors.append(f"plan: '{slug}' must be lowercase letters, digits and hyphens")
    if not str(plan.get("question") or "").strip():
        errors.append("plan: missing 'question'")
    if not provenance_entries(plan.get("provenance")):
        errors.append("plan: missing 'provenance' (path plus locator, bead id or Message-ID)")
    privacy = str(plan.get("privacy") or "internal")
    if privacy not in PRIVACY:
        errors.append(f"plan: privacy {privacy!r} not in {sorted(PRIVACY)}")
    owner = str(plan.get("owner") or "").strip()
    if owner and owner not in ROLES:
        errors.append(f"plan: owner role {owner!r} not in {sorted(ROLES)}")
    deadline = plan.get("deadline")
    if deadline not in (None, "") and not DATE_RE.match(str(deadline)):
        errors.append(f"plan: deadline {deadline!r} is not YYYY-MM-DD")

    hypotheses = plan["hypotheses"]
    experiments = plan["experiments"]
    _check_ids(hypotheses, "hypothesis", errors)
    _check_ids(experiments, "experiment", errors)
    _check_ids(plan["risks"], "risk", errors)
    _check_ids(plan["checkpoints"], "checkpoint", errors)

    if not hypotheses:
        errors.append("plan: no hypotheses; a plan states what could be false")
    elif len(hypotheses) < 2:
        demand.append("plan: only one hypothesis; strong inference needs a competing one")
    for hyp in hypotheses:
        ident = hyp.get("id", "?")
        if not str(hyp.get("statement") or "").strip():
            errors.append(f"hypothesis {ident}: missing statement")
        if not str(hyp.get("predicts") or "").strip():
            demand.append(f"hypothesis {ident}: missing 'predicts' (what it implies we would see)")

    known = {str(h.get("id")) for h in hypotheses}
    if not experiments:
        errors.append("plan: no experiments")
    for exp in experiments:
        ident = exp.get("id", "?")
        if not str(exp.get("title") or "").strip():
            errors.append(f"experiment {ident}: missing title")
        if not as_list(exp.get("baselines")):
            errors.append(f"experiment {ident}: missing baseline")
        threshold = str(exp.get("success_threshold") or "").strip()
        if not threshold:
            errors.append(f"experiment {ident}: missing success_threshold")
        elif not NUMBER_RE.search(threshold):
            demand.append(f"experiment {ident}: success_threshold states no number: {threshold!r}")
        if not str(exp.get("kill_criterion") or "").strip():
            errors.append(f"experiment {ident}: missing kill_criterion")
        role = str(exp.get("owner") or owner or "").strip()
        if not role:
            errors.append(f"experiment {ident}: missing owner role")
        elif role not in ROLES:
            errors.append(f"experiment {ident}: owner role {role!r} not in {sorted(ROLES)}")
        exp_privacy = str(exp.get("privacy") or privacy)
        if exp_privacy not in PRIVACY:
            errors.append(f"experiment {ident}: privacy {exp_privacy!r} not in {sorted(PRIVACY)}")
        tests = as_list(exp.get("tests"))
        if not tests:
            demand.append(f"experiment {ident}: tests no hypothesis")
        for h in tests:
            if h not in known:
                errors.append(f"experiment {ident}: tests unknown hypothesis {h!r}")
        for dep in as_list(exp.get("depends_on")):
            if dep not in {str(e.get("id")) for e in experiments}:
                errors.append(f"experiment {ident}: depends on unknown experiment {dep!r}")
        exp_deadline = exp.get("deadline")
        if exp_deadline not in (None, "") and not DATE_RE.match(str(exp_deadline)):
            errors.append(f"experiment {ident}: deadline {exp_deadline!r} is not YYYY-MM-DD")
        for i, crit in enumerate(as_list(exp.get("acceptance"))):
            if not checkable(crit):
                demand.append(f"experiment {ident}: acceptance[{i}] may not be checkable: {crit!r}")

    for risk in plan["risks"]:
        ident = risk.get("id", "?")
        if not str(risk.get("risk") or "").strip():
            errors.append(f"risk {ident}: missing 'risk'")
        if not str(risk.get("mitigation") or "").strip():
            errors.append(f"risk {ident}: missing mitigation or fallback")
        check = str(risk.get("check") or "").strip()
        if not check:
            warnings.append(f"risk {ident}: no 'check'; recorded in the plan, no bead created")
        elif not checkable(check):
            demand.append(f"risk {ident}: check may not be checkable: {check!r}")

    for cp in plan["checkpoints"]:
        ident = cp.get("id", "?")
        if not DATE_RE.match(str(cp.get("date") or "")):
            errors.append(f"checkpoint {ident}: missing or malformed date (YYYY-MM-DD)")
        if not str(cp.get("measure") or "").strip():
            errors.append(f"checkpoint {ident}: missing 'measure' (what is reported on that date)")
        if not str(cp.get("decision") or "").strip():
            errors.append(f"checkpoint {ident}: missing 'decision' (continue, revise or stop)")
    return errors, warnings


# --------------------------------------------------------------------------- beads


def header_yaml(xid: str, provenance: list[dict[str, str]], deadline: Any, privacy: str) -> str:
    payload: dict[str, Any] = {"xid": xid, "provenance": provenance}
    if deadline:
        payload["deadline"] = str(deadline)
    payload["privacy"] = privacy
    return "---\n" + yaml.safe_dump(payload, sort_keys=False).rstrip() + "\n---\n"


def _body(lines: list[tuple[str, Any]]) -> str:
    out: list[str] = []
    for label, value in lines:
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            out.append(f"{label}:")
            out += [f"- {v}" for v in value]
        else:
            out.append(f"{label}: {value}")
    return "\n".join(out) + "\n"


def build_beads(plan: dict[str, Any]) -> list[dict[str, Any]]:
    slug = str(plan["plan"])
    privacy = str(plan.get("privacy") or "internal")
    default_owner = str(plan.get("owner") or "senior")
    plan_prov = provenance_entries(plan.get("provenance"))
    hyp_by_id = {str(h.get("id")): h for h in plan["hypotheses"]}
    beads: list[dict[str, Any]] = []

    for exp in plan["experiments"]:
        ident = str(exp["id"])
        baselines = as_list(exp.get("baselines"))
        threshold = str(exp["success_threshold"]).strip()
        kill = str(exp["kill_criterion"]).strip()
        metric = str(exp.get("metric") or "the reported metric").strip()
        tests = as_list(exp.get("tests"))
        criteria = [
            f"{metric} is reported for {ident} against every baseline ({', '.join(baselines)})",
            f"the success threshold is evaluated and stated: {threshold}",
            f"the kill criterion is evaluated and stated: {kill}",
        ]
        criteria += as_list(exp.get("acceptance"))
        prov = provenance_entries(exp.get("provenance")) or plan_prov
        deadline = exp.get("deadline") or plan.get("deadline")
        body = _body(
            [
                ("Question", plan.get("question")),
                ("Tests hypotheses", [f"{h}: {hyp_by_id[h].get('statement')}" for h in tests]),
                ("Excluded if", exp.get("excludes")),
                ("Data", exp.get("data")),
                ("Baselines", baselines),
                ("Metric", exp.get("metric")),
                ("Success threshold", threshold),
                ("Kill criterion", kill),
                ("Effort budget", exp.get("effort")),
                ("Out of scope", exp.get("out_of_scope")),
                ("Acceptance criteria", criteria),
            ]
        )
        beads.append(
            {
                "xid": f"experiment:{slug}:{ident}",
                "id": ident,
                "title": str(exp["title"]),
                "kind": "experiment",
                "stage": STAGE,
                "privacy": str(exp.get("privacy") or privacy),
                "owner_role": str(exp.get("owner") or default_owner),
                "deadline": str(deadline) if deadline else None,
                "provenance": prov,
                "depends_on": [f"experiment:{slug}:{d}" for d in as_list(exp.get("depends_on"))],
                "acceptance_criteria": criteria,
                "body": body,
            }
        )

    for risk in plan["risks"]:
        check = str(risk.get("check") or "").strip()
        if not check:
            continue
        ident = str(risk["id"])
        criteria = [check]
        body = _body(
            [
                ("Risk", risk.get("risk")),
                ("Likelihood", risk.get("likelihood")),
                ("Impact", risk.get("impact")),
                ("Mitigation", risk.get("mitigation")),
                ("Acceptance criteria", criteria),
            ]
        )
        beads.append(
            {
                "xid": f"risk:{slug}:{ident}",
                "id": ident,
                "title": f"Mitigate risk: {risk['risk']}",
                "kind": "design",
                "stage": STAGE,
                "privacy": str(risk.get("privacy") or privacy),
                "owner_role": str(risk.get("owner") or default_owner),
                "deadline": str(risk["deadline"]) if risk.get("deadline") else None,
                "provenance": provenance_entries(risk.get("provenance")) or plan_prov,
                "depends_on": [],
                "acceptance_criteria": criteria,
                "body": body,
            }
        )

    for cp in plan["checkpoints"]:
        ident = str(cp["id"])
        criteria = [
            f"{cp['measure']} is reported by {cp['date']}",
            f"the decision is recorded in the plan: {cp['decision']}",
        ]
        body = _body(
            [
                ("Measure", cp.get("measure")),
                ("Decision rule", cp.get("decision")),
                ("Covers experiments", as_list(cp.get("experiments"))),
                ("Acceptance criteria", criteria),
            ]
        )
        beads.append(
            {
                "xid": f"checkpoint:{slug}:{ident}",
                "id": ident,
                "title": f"Checkpoint {cp['date']}: {cp['measure']}",
                "kind": "review",
                "stage": STAGE,
                "privacy": privacy,
                "owner_role": str(cp.get("owner") or default_owner),
                "deadline": str(cp["date"]),
                "provenance": plan_prov,
                "depends_on": [f"experiment:{slug}:{e}" for e in as_list(cp.get("experiments"))],
                "acceptance_criteria": criteria,
                "body": body,
            }
        )
    return beads


def bd_argv(bead: dict[str, Any]) -> list[str]:
    description = (
        header_yaml(bead["xid"], bead["provenance"], bead["deadline"], bead["privacy"])
        + "\n"
        + bead["body"]
    )
    labels = (
        f"kind:{bead['kind']},stage:{bead['stage']},"
        f"privacy:{bead['privacy']},role:{bead['owner_role']}"
    )
    argv = [
        "bd",
        "create",
        bead["title"],
        "--type",
        "task",
        "--priority",
        "2",
        "--external-ref",
        bead["xid"],
        "--description",
        description,
        "--labels",
        labels,
        "--silent",
    ]
    if bead["deadline"]:
        argv += ["--due", bead["deadline"]]
    if bead["depends_on"]:
        argv += ["--deps", ",".join(bead["depends_on"])]
    argv += ["--acceptance", "; ".join(bead["acceptance_criteria"])]
    return argv


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--plan", required=True, type=Path, help="research plan YAML")
    p.add_argument("--out", type=Path, default=None, help="write the beads JSON here")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--strict", action="store_true", help="treat weak thresholds and gaps as errors")
    p.add_argument(
        "--apply",
        action="store_true",
        help="run the bd create commands; without it the script only prints them",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = load_plan(args.plan)
    except (OSError, PlanError, yaml.YAMLError) as exc:
        print(f"plan-to-beads: {exc}", file=sys.stderr)
        return 1

    errors, warnings = validate(plan, args.strict)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"plan-to-beads: {len(errors)} error(s); nothing written", file=sys.stderr)
        return 2

    beads = build_beads(plan)
    commands = [bd_argv(b) for b in beads]
    result = {
        "plan": plan["plan"],
        "question": plan["question"],
        "applied": False,
        "warnings": warnings,
        "beads": beads,
        "commands": [shlex.join(c) for c in commands],
    }
    if not args.apply:
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", "utf-8")
            print(f"plan-to-beads: {len(beads)} bead(s) -> {args.out}", file=sys.stderr)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            for command in result["commands"]:
                print(command)
        print(
            f"plan-to-beads: {len(beads)} bead(s) planned (dry run, nothing created)",
            file=sys.stderr,
        )
        return 0
    for argv_ in commands:
        proc = subprocess.run(argv_, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"plan-to-beads: {argv_[2]!r} failed: {proc.stderr.strip()}", file=sys.stderr)
            return 3
        if proc.stdout.strip():
            print(proc.stdout.strip())
    result["applied"] = True
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"plan-to-beads: {len(beads)} bead(s) -> {args.out}", file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"plan-to-beads: {len(beads)} bead(s) applied", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
