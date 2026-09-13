#!/usr/bin/env python3
"""Check a call definition's explicit requirements against a text draft.

The checker deliberately does not infer current funder rules or inspect binary
documents. A call YAML supplies the binding requirement and an evidence marker
or literal that the draft must contain. Missing evidence remains unverified.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


CATEGORIES = ("page_limits", "sections", "fonts", "annexes", "deadlines", "eligibility")


class InputError(ValueError):
    """A call definition cannot be checked safely."""


def _as_items(value: Any, category: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InputError(f"{category}: expected a list")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise InputError(f"{category}[{index}]: expected a mapping")
        if not isinstance(item.get("id"), str) or not item["id"].strip():
            raise InputError(f"{category}[{index}]: missing string id")
        items.append(item)
    return items


def load_call(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read call definition: {exc}") from exc
    except yaml.YAMLError as exc:
        raise InputError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("call definition must be a YAML mapping")
    requirements = data.get("requirements", data)
    if not isinstance(requirements, dict):
        raise InputError("requirements must be a mapping")
    normalized: dict[str, Any] = {"title": data.get("title", path.stem), "requirements": {}}
    for category in CATEGORIES:
        normalized["requirements"][category] = _as_items(requirements.get(category), category)
    return normalized


def _finding(item: dict[str, Any], category: str, status: str, detail: str) -> dict[str, Any]:
    mandatory = bool(item.get("mandatory", True))
    return {
        "category": category,
        "id": item["id"],
        "mandatory": mandatory,
        "status": status,
        "severity": "error" if mandatory else "warning",
        "detail": detail,
        "fix": item.get("fix", "Add the specified evidence to the draft or correct the call definition."),
    }


def _passed(item: dict[str, Any], category: str, detail: str) -> dict[str, Any]:
    return {
        "category": category,
        "id": item["id"],
        "mandatory": bool(item.get("mandatory", True)),
        "status": "passed",
        "severity": "info",
        "detail": detail,
    }


def _contains(draft: str, expected: str | list[str]) -> bool:
    values = [expected] if isinstance(expected, str) else expected
    return bool(values) and all(isinstance(value, str) and value.casefold() in draft.casefold() for value in values)


def _marker_value(draft: str, label: str) -> str | None:
    pattern = rf"<!--\s*{re.escape(label)}\s*:\s*(.*?)\s*-->"
    match = re.search(pattern, draft, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _check_sections(items: list[dict[str, Any]], draft: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    headings = {
        re.sub(r"\s+", " ", match.group(1).strip()).casefold()
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", draft, flags=re.MULTILINE)
    }
    for item in items:
        heading = str(item.get("heading", item["id"])).strip()
        found = re.sub(r"\s+", " ", heading).casefold() in headings
        if found and item.get("contains") is not None:
            found = _contains(draft, item["contains"])
        out.append(
            _passed(item, "sections", f"found heading: {heading}")
            if found
            else _finding(item, "sections", "unmet", f"missing required heading or content: {heading}")
        )
    return out


def _check_page_limits(items: list[dict[str, Any]], draft: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        maximum = item.get("max_pages")
        minimum = item.get("min_pages")
        if not isinstance(maximum, int) and not isinstance(minimum, int):
            out.append(_finding(item, "page_limits", "unmet", "call definition needs max_pages or min_pages"))
            continue
        label = str(item.get("marker", f"pages: {item['id']}"))
        raw = _marker_value(draft, label)
        if raw is None:
            out.append(_finding(item, "page_limits", "unverified", f"missing page-count marker <!-- {label}: N -->"))
            continue
        try:
            pages = int(raw)
        except ValueError:
            out.append(_finding(item, "page_limits", "unmet", f"page-count marker is not an integer: {raw!r}"))
            continue
        if pages < 0 or (isinstance(maximum, int) and pages > maximum) or (isinstance(minimum, int) and pages < minimum):
            bounds = ", ".join(
                part for part in [f"at most {maximum}" if isinstance(maximum, int) else "", f"at least {minimum}" if isinstance(minimum, int) else ""] if part
            )
            out.append(_finding(item, "page_limits", "unmet", f"observed {pages} pages; call requires {bounds}"))
        else:
            out.append(_passed(item, "page_limits", f"observed {pages} page(s)"))
    return out


def _check_fonts(items: list[dict[str, Any]], draft: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        allowed = item.get("allowed")
        if isinstance(allowed, str):
            allowed = [allowed]
        if not isinstance(allowed, list) or not all(isinstance(value, str) for value in allowed):
            out.append(_finding(item, "fonts", "unmet", "call definition needs an allowed font list"))
            continue
        label = str(item.get("marker", f"font: {item['id']}"))
        observed = _marker_value(draft, label)
        if observed is None:
            out.append(_finding(item, "fonts", "unverified", f"missing font marker <!-- {label}: value -->"))
        elif observed.casefold() not in {value.casefold() for value in allowed}:
            out.append(_finding(item, "fonts", "unmet", f"observed {observed!r}; allowed: {', '.join(allowed)}"))
        else:
            out.append(_passed(item, "fonts", f"observed allowed font declaration: {observed}"))
    return out


def _check_annexes(items: list[dict[str, Any]], draft: str, call_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        relative = item.get("path")
        if relative is not None:
            if not isinstance(relative, str):
                out.append(_finding(item, "annexes", "unmet", "annex path must be a string"))
                continue
            annex = call_path.parent / relative
            if annex.is_file():
                out.append(_passed(item, "annexes", f"annex file exists: {relative}"))
            else:
                out.append(_finding(item, "annexes", "unmet", f"annex file is absent: {relative}"))
            continue
        expected = item.get("contains")
        if expected is not None:
            found = _contains(draft, expected)
            detail = f"found required annex text: {expected!r}" if found else f"missing required annex text: {expected!r}"
        else:
            label = str(item.get("marker", f"annex: {item['id']}"))
            found = _marker_value(draft, label) is not None
            detail = f"found annex marker: {label}" if found else f"missing annex marker <!-- {label}: included -->"
        out.append(_passed(item, "annexes", detail) if found else _finding(item, "annexes", "unmet", detail))
    return out


def _check_deadlines(items: list[dict[str, Any]], draft: str, today: dt.date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        raw_date = item.get("date")
        try:
            due = dt.date.fromisoformat(str(raw_date))
        except ValueError:
            out.append(_finding(item, "deadlines", "unmet", "deadline must use ISO date YYYY-MM-DD"))
            continue
        if due < today:
            out.append(_finding(item, "deadlines", "unmet", f"deadline has passed: {due.isoformat()}"))
            continue
        label = str(item.get("marker", f"deadline: {item['id']}"))
        observed = _marker_value(draft, label)
        if observed is None:
            out.append(_finding(item, "deadlines", "unverified", f"missing deadline marker <!-- {label}: {due.isoformat()} -->"))
        elif observed != due.isoformat():
            out.append(_finding(item, "deadlines", "unmet", f"deadline marker {observed!r} does not match {due.isoformat()}"))
        else:
            out.append(_passed(item, "deadlines", f"deadline acknowledged: {due.isoformat()}"))
    return out


def _check_eligibility(items: list[dict[str, Any]], draft: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        expected = item.get("contains")
        if expected is not None:
            found = _contains(draft, expected)
            detail = f"found eligibility evidence: {expected!r}" if found else f"missing eligibility evidence: {expected!r}"
        else:
            label = str(item.get("marker", f"eligibility: {item['id']}"))
            found = _marker_value(draft, label) is not None
            detail = f"found eligibility marker: {label}" if found else f"missing eligibility marker <!-- {label}: confirmed-by-Robert -->"
        out.append(_passed(item, "eligibility", detail) if found else _finding(item, "eligibility", "unverified", detail))
    return out


def check_call(call: dict[str, Any], draft: str, call_path: Path, today: dt.date | None = None) -> dict[str, Any]:
    """Return deterministic findings without writing files or inferring requirements."""
    date = today or dt.date.today()
    req = call["requirements"]
    checks = []
    checks.extend(_check_page_limits(req["page_limits"], draft))
    checks.extend(_check_sections(req["sections"], draft))
    checks.extend(_check_fonts(req["fonts"], draft))
    checks.extend(_check_annexes(req["annexes"], draft, call_path))
    checks.extend(_check_deadlines(req["deadlines"], draft, date))
    checks.extend(_check_eligibility(req["eligibility"], draft))
    unmet = [check for check in checks if check["status"] != "passed"]
    mandatory_unmet = [check for check in unmet if check["mandatory"]]
    return {
        "call": call["title"],
        "checked_on": date.isoformat(),
        "checks": checks,
        "findings": unmet,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(unmet),
            "unmet": len(unmet),
            "mandatory_unmet": len(mandatory_unmet),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--call", type=Path, required=True, help="call definition YAML")
    parser.add_argument("--draft", type=Path, required=True, help="UTF-8 text or Markdown draft")
    parser.add_argument("--today", type=dt.date.fromisoformat, help="override current date for reproducible checks")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        call = load_call(args.call)
        draft = args.draft.read_text(encoding="utf-8")
        result = check_call(call, draft, args.call, args.today)
    except (InputError, OSError, UnicodeError) as exc:
        print(f"call-checklist: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["checks"]:
            print(f"{item['status'].upper():10} {item['category']}/{item['id']}: {item['detail']}")
        summary = result["summary"]
        print(f"call-checklist: {summary['passed']}/{summary['total']} passed; {summary['mandatory_unmet']} mandatory unmet")
    return 1 if result["summary"]["mandatory_unmet"] else 0


if __name__ == "__main__":
    sys.exit(main())
