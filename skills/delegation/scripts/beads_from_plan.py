#!/usr/bin/env python3
"""Turn a plan (Markdown per assets/plan-template.md, or YAML) into validated beads JSON.

Every bead must carry at least one acceptance criterion that someone other than
the owner can check, an owner role, an output (format and location), a privacy
class and provenance. A plan with a bead that lacks any of these exits 2 and
names the bead and the missing field; nothing is written. Criteria that look
unverifiable (no command, path, number, or check verb) are warnings, or errors
with ``--strict``.

Output is JSON with the plan header and a ``beads`` list shaped like
assets/bead.schema.json. ``--bd-commands`` additionally prints the ``bd create``
lines a human or the engine would run; the script never runs them.

Example:
  beads_from_plan.py --plan runs/7/plan.md --out runs/7/beads.json
  beads_from_plan.py --plan runs/7/plan.yaml --strict --bd-commands
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE.parent / "assets" / "bead.schema.json"

BEAD_HEADING_RE = re.compile(r"^##\s+Bead:\s*(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s*([A-Za-z][A-Za-z _]*?)\s*:\s*(.*?)\s*$")
HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z ]*?):\s*(.*?)\s*$")
CHECKBOX_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+?)\s*$")
ACCEPTANCE_RE = re.compile(r"^Acceptance(?: criteria)?:\s*$", re.IGNORECASE)
CHECKABLE_RE = re.compile(
    r"`[^`]+`|/|\.(py|md|org|json|yaml|yml|tsv|csv|tex|txt)\b|\d|\b(exit|"
    r"exists?|passes|pass|fails?|equals?|contains?|matches|lists?|reports?|returns?|confirms?|at least|at most|no more than|section)\b",
    re.IGNORECASE,
)
FIELD_ALIASES = {
    "owner": "owner_role",
    "owner role": "owner_role",
    "role": "owner_role",
    "depends": "depends_on",
    "depends on": "depends_on",
    "out of scope": "out_of_scope",
    "review by": "review_by",
    "reviewer": "review_by",
}
LIST_FIELDS = {"depends_on", "sources", "provenance"}


class PlanError(Exception):
    """Plan cannot be turned into beads."""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "bead"


def split_list(value: str) -> list[str]:
    if not value or value.strip().lower() in {"none", "-", "[]"}:
        return []
    return [v.strip() for v in re.split(r"[;,]", value) if v.strip()]


def parse_markdown(text: str) -> dict[str, Any]:
    plan: dict[str, Any] = {"beads": []}
    current: dict[str, Any] | None = None
    in_acceptance = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# ") and "goal" not in plan:
            plan["title"] = line[2:].strip()
            continue
        m = BEAD_HEADING_RE.match(line)
        if m:
            current = {"title": m.group(1), "acceptance_criteria": []}
            plan["beads"].append(current)
            in_acceptance = False
            continue
        if current is None:
            hm = HEADER_RE.match(line)
            if hm:
                key = hm.group(1).strip().lower().replace(" ", "_")
                plan[key] = hm.group(2).strip()
            continue
        if ACCEPTANCE_RE.match(line.strip()):
            in_acceptance = True
            continue
        cm = CHECKBOX_RE.match(line.strip())
        if cm and in_acceptance:
            current["acceptance_criteria"].append({"check": cm.group(1)})
            continue
        fm = FIELD_RE.match(line.strip())
        if fm and not in_acceptance:
            key = fm.group(1).strip().lower()
            key = FIELD_ALIASES.get(key, key.replace(" ", "_"))
            value = fm.group(2).strip()
            current[key] = split_list(value) if key in LIST_FIELDS else value
            continue
        if line.startswith("#"):
            in_acceptance = False
    return plan


def parse_yaml(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or "beads" not in data:
        raise PlanError("YAML plan needs a top-level 'beads' list")
    for bead in data["beads"]:
        for key, alias in FIELD_ALIASES.items():
            if key in bead and alias not in bead:
                bead[alias] = bead.pop(key)
        crit = bead.get("acceptance_criteria") or bead.get("acceptance") or []
        bead["acceptance_criteria"] = [
            c if isinstance(c, dict) else {"check": str(c)} for c in crit
        ]
        bead.pop("acceptance", None)
        for key in LIST_FIELDS:
            if isinstance(bead.get(key), str):
                bead[key] = split_list(bead[key])
    return data


def load_plan(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return parse_yaml(text)
    return parse_markdown(text)


def normalise(plan: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults from the plan header and derive ids."""
    header_privacy = plan.get("privacy", "internal")
    header_prov = (
        split_list(str(plan.get("provenance", "")))
        if not isinstance(plan.get("provenance"), list)
        else plan["provenance"]
    )
    review_by = plan.get("review_by")
    seen: set[str] = set()
    for n, bead in enumerate(plan["beads"], 1):
        bead.setdefault("id", slugify(bead.get("title", f"bead-{n}")))
        if bead["id"] in seen:
            bead["id"] = f"{bead['id']}-{n}"
        seen.add(bead["id"])
        bead.setdefault("kind", "implement")
        bead.setdefault("stage", "design")
        bead.setdefault("privacy", header_privacy)
        bead.setdefault("depends_on", [])
        bead.setdefault("sources", [])
        bead.setdefault("objective", bead.get("title"))
        if not bead.get("provenance"):
            bead["provenance"] = list(header_prov)
        if review_by and not bead.get("review_by"):
            bead["review_by"] = review_by
        if bead.get("deadline") in ("none", "", None):
            bead["deadline"] = None
    plan["provenance"] = header_prov
    return plan


# --------------------------------------------------------------------------- validation


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _type_ok(value: Any, expected: Any) -> bool:
    types = expected if isinstance(expected, list) else [expected]
    mapping = {
        "string": str,
        "array": list,
        "object": dict,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    return any(isinstance(value, mapping[t]) for t in types if t in mapping)


def validate_bead(bead: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Minimal JSON-schema check: required, type, enum, minItems, minLength, pattern."""
    problems: list[str] = []
    for key in schema.get("required", []):
        if key not in bead or bead[key] in (None, "", []):
            problems.append(f"missing {key}")
    for key, spec in schema.get("properties", {}).items():
        if key not in bead or bead[key] is None:
            continue
        value = bead[key]
        if "type" in spec and not _type_ok(value, spec["type"]):
            problems.append(f"{key}: expected {spec['type']}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{key}: {value!r} not in {spec['enum']}")
        if "pattern" in spec and isinstance(value, str) and not re.match(spec["pattern"], value):
            problems.append(f"{key}: {value!r} does not match {spec['pattern']}")
        if "minLength" in spec and isinstance(value, str) and len(value) < spec["minLength"]:
            problems.append(f"{key}: shorter than {spec['minLength']} characters")
        if "minItems" in spec and isinstance(value, list) and len(value) < spec["minItems"]:
            problems.append(f"{key}: needs at least {spec['minItems']} item(s)")
        if (
            isinstance(value, list)
            and isinstance(spec.get("items"), dict)
            and spec["items"].get("type") == "object"
        ):
            for i, item in enumerate(value):
                for sub in spec["items"].get("required", []):
                    if not isinstance(item, dict) or not item.get(sub):
                        problems.append(f"{key}[{i}]: missing {sub}")
                if isinstance(item, dict):
                    check = item.get("check")
                    min_len = spec["items"]["properties"]["check"].get("minLength", 0)
                    if isinstance(check, str) and len(check) < min_len:
                        problems.append(f"{key}[{i}]: check shorter than {min_len} characters")
    return problems


def checkability_warnings(bead: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for i, crit in enumerate(bead.get("acceptance_criteria", [])):
        check = crit.get("check", "") if isinstance(crit, dict) else str(crit)
        if not CHECKABLE_RE.search(check):
            out.append(f"acceptance_criteria[{i}] may not be checkable: {check!r}")
    return out


def bd_commands(plan: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for b in plan["beads"]:
        desc = json.dumps(
            {
                "xid": None,
                "provenance": b.get("provenance", []),
                "deadline": b.get("deadline"),
                "acceptance_criteria": [c["check"] for c in b["acceptance_criteria"]],
                "output": b.get("output"),
                "out_of_scope": b.get("out_of_scope"),
            },
            ensure_ascii=False,
        )
        labels = (
            f"kind:{b['kind']},stage:{b.get('stage', 'design')},"
            f"privacy:{b['privacy']},role:{b['owner_role']}"
        )
        lines.append(
            f"bd create {json.dumps(b['title'])} --labels {labels} --description {json.dumps(desc)}"
        )
        for dep in b.get("depends_on", []):
            lines.append(f"bd dep add {b['id']} {dep}")
    return lines


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--plan", required=True, type=Path, help="plan.md or plan.yaml")
    p.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--out", type=Path, default=None, help="write beads JSON here")
    p.add_argument("--strict", action="store_true", help="treat checkability warnings as errors")
    p.add_argument(
        "--bd-commands", action="store_true", help="print bd create lines (never executed)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = normalise(load_plan(args.plan))
        schema = load_schema(args.schema)
    except (OSError, PlanError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"beads-from-plan: {exc}", file=sys.stderr)
        return 1
    if not plan["beads"]:
        print("beads-from-plan: plan has no '## Bead:' sections", file=sys.stderr)
        return 2
    errors: list[str] = []
    warnings: list[str] = []
    for bead in plan["beads"]:
        for problem in validate_bead(bead, schema):
            errors.append(f"{bead['id']}: {problem}")
        for w in checkability_warnings(bead):
            (errors if args.strict else warnings).append(f"{bead['id']}: {w}")
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"beads-from-plan: {len(errors)} error(s); nothing written", file=sys.stderr)
        return 2
    result = {
        "goal": plan.get("goal") or plan.get("title"),
        "pattern": plan.get("pattern", "single"),
        "provenance": plan.get("provenance", []),
        "review_by": plan.get("review_by"),
        "beads": plan["beads"],
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"beads-from-plan: {len(plan['beads'])} bead(s) -> {args.out}")
    else:
        print(text)
    if args.bd_commands:
        print("\n".join(bd_commands(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
