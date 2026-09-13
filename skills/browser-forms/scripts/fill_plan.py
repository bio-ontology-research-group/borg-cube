#!/usr/bin/env python3
"""Create an ordered, redacted, submit-free browser form fill plan.

The form definition and answers use the schema documented by the kaust-admin
skill. The output always has ``dry_run: true`` and ends with a
``stop_before_submit`` step. ``--check-url`` is restricted to loopback and
checks simple id or name selectors against the local mock form.

Example:
  fill_plan.py --form definition.yaml --answers answers.yaml --json
  fill_plan.py --form definition.yaml --answers answers.yaml \
      --check-url http://127.0.0.1:8765/ --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

import yaml

ALLOWED_CONTROLS = {
    "text",
    "textarea",
    "email",
    "tel",
    "date",
    "number",
    "select",
    "checkbox",
    "radio",
    "yes-no",
}
CHOICE_CONTROLS = {"checkbox", "radio", "yes-no"}
FORBIDDEN_RE = re.compile(
    r"(?:password|passwd|\bpwd\b|credential|api[_ -]?key|access[_ -]?token|"
    r"auth(?:entication|orization)?[_ -]?token|private[_ -]?key)",
    re.IGNORECASE,
)
PERSONAL_RE = re.compile(
    r"(?:passport|salary|grade|\bgpa\b|health|medical|visa|contract|iqama|"
    r"national[_ -]?id|identity|date[_ -]?of[_ -]?birth|birth[_ -]?date|"
    r"address|phone|email|full[_ -]?name|requester[_ -]?name|student[_ -]?name)",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}\b", re.IGNORECASE),
)
PLACEHOLDER_RE = re.compile(
    r"(?:unverified|to be supplied|to supply|placeholder|example\.invalid|<[^>]+>)",
    re.IGNORECASE,
)
ID_SELECTOR_RE = re.compile(r"^#([A-Za-z][\w:.-]*)$")
NAME_SELECTOR_RE = re.compile(
    r"^(?:[A-Za-z][\w-]*)?\[name=(?:\"([^\"]+)\"|'([^']+)'|([^\]]+))\]$"
)


class PlanError(Exception):
    """A safe, user-facing input error."""


class FormParser(HTMLParser):
    """Collect form controls and label text for simple selector checks."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[dict[str, str]] = []
        self.labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag in {"input", "textarea", "select", "button"}:
            self.elements.append({"tag": tag, **attr_map})
        if tag == "label":
            self._label_for = attr_map.get("for")
            self._label_text = []

    def handle_data(self, data: str) -> None:
        if self._label_for is not None:
            self._label_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_for is not None:
            self.labels[self._label_for] = " ".join("".join(self._label_text).split())
            self._label_for = None
            self._label_text = []


def load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PlanError(f"cannot read {label} YAML: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError(f"{label} YAML must be a mapping")
    return data


def text_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def has_value(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def looks_secret(value: Any) -> bool:
    if not has_value(value):
        return False
    rendered = text_value(value)
    return any(pattern.search(rendered) for pattern in SECRET_PATTERNS)


def answer_entry(answers: dict[str, Any], field_id: str) -> tuple[bool, Any, bool]:
    if field_id not in answers:
        return False, None, False
    raw = answers[field_id]
    if isinstance(raw, dict) and ("value" in raw or "present" in raw or "evidence" in raw):
        value = raw.get("value")
        present = bool(raw.get("present", has_value(value)))
        evidence = raw.get("evidence")
        has_evidence = bool(evidence) and evidence != [{}]
        return present, value, has_evidence
    return has_value(raw), raw, False


def personal_field(field: dict[str, Any]) -> bool:
    sensitivity = str(field.get("sensitivity", "none")).lower()
    return sensitivity in {"personal", "local-only", "sensitive"} or bool(
        PERSONAL_RE.search(f"{field.get('id', '')} {field.get('label', '')}")
    )


def expected_tag(field: dict[str, Any]) -> tuple[str, str | None]:
    control = field["control"]
    if control == "textarea":
        return "textarea", None
    if control == "select":
        return "select", None
    if control == "checkbox":
        return "input", "checkbox"
    if control in {"radio", "yes-no"}:
        return "input", "radio"
    return "input", control


def selector_matches(parser: FormParser, selector: str) -> list[dict[str, str]] | None:
    id_match = ID_SELECTOR_RE.match(selector)
    if id_match:
        return [element for element in parser.elements if element.get("id") == id_match.group(1)]
    name_match = NAME_SELECTOR_RE.match(selector)
    if name_match:
        name = next(group for group in name_match.groups() if group is not None).strip()
        return [element for element in parser.elements if element.get("name") == name]
    return None


def check_loopback_url(url: str) -> FormParser:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise PlanError("--check-url accepts only http://127.0.0.1 or http://localhost")
    if parsed.username or parsed.password:
        raise PlanError("credentials in --check-url are forbidden")
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310, loopback checked above
            payload = response.read(1_000_000).decode("utf-8", errors="replace")
    except OSError as exc:
        raise PlanError(f"cannot read local mock form: {exc}") from exc
    parser = FormParser()
    parser.feed(payload)
    return parser


def validate_inputs(
    data: dict[str, Any], answers_data: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    form = data.get("form")
    fields = data.get("fields")
    answers = answers_data.get("answers")
    if not isinstance(form, dict):
        raise PlanError("form definition needs a 'form' mapping")
    if not isinstance(fields, list) or not fields:
        raise PlanError("form definition needs a non-empty 'fields' list")
    if not isinstance(answers, dict):
        raise PlanError("answers YAML needs an 'answers' mapping")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(fields, 1):
        if not isinstance(raw, dict):
            raise PlanError(f"field {index} must be a mapping")
        field = dict(raw)
        field_id = str(field.get("id", "")).strip()
        label = str(field.get("label", "")).strip()
        selector = str(field.get("selector", "")).strip()
        control = str(field.get("control", "text")).strip().lower()
        if not field_id or not label or not selector:
            raise PlanError(f"field {index} needs id, label, and selector")
        if field_id in seen:
            raise PlanError(f"duplicate field id: {field_id}")
        seen.add(field_id)
        if FORBIDDEN_RE.search(f"{field_id} {label} {selector}") or control == "password":
            raise PlanError("password and credential fields are forbidden")
        if control not in ALLOWED_CONTROLS:
            raise PlanError(f"field {field_id}: unsupported control {control!r}")
        action = str(field.get("action", "")).lower()
        if action in {"submit", "sign", "approve", "pay", "purchase", "send"}:
            raise PlanError(f"field {field_id}: external action is forbidden")
        field.update(id=field_id, label=label, selector=selector, control=control)
        normalized.append(field)
    return form, normalized, answers


def definition_gaps(form: dict[str, Any], fields: list[dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    for key in ("id", "title", "workflow"):
        if not str(form.get(key, "")).strip():
            gaps.append(f"form.{key} is missing")
    source = form.get("source")
    if not isinstance(source, dict):
        gaps.append("form.source must be a mapping")
    else:
        source_location = str(source.get("path") or source.get("url") or "").strip()
        locator = str(source.get("locator") or "").strip()
        verified = str(source.get("verified_on") or "").strip()
        if not source_location:
            gaps.append("form.source needs path or url")
        elif PLACEHOLDER_RE.search(source_location):
            gaps.append("form.source path or url is a placeholder")
        if not locator:
            gaps.append("form.source needs locator")
        elif PLACEHOLDER_RE.search(locator):
            gaps.append("form.source locator is a placeholder")
        try:
            dt.date.fromisoformat(verified)
        except ValueError:
            gaps.append("form.source.verified_on must be an ISO date")
    for field in fields:
        if PLACEHOLDER_RE.search(field["selector"]):
            gaps.append(f"{field['id']}: selector is a placeholder")
    return gaps


def field_action(field: dict[str, Any], value: Any) -> str:
    control = field["control"]
    if control == "select":
        return "select_option"
    if control == "checkbox":
        return "check" if value is True else "uncheck"
    if control in {"radio", "yes-no"}:
        return "click_choice"
    return "fill"


def build_plan(
    form_data: dict[str, Any],
    answers_data: dict[str, Any],
    parser: FormParser | None = None,
) -> dict[str, Any]:
    form, fields, answers = validate_inputs(form_data, answers_data)
    plan: list[dict[str, Any]] = []
    missing_required: list[str] = []
    missing_evidence: list[str] = []
    invalid_answers: list[str] = []
    blocked_secrets: list[str] = []
    layout_changes: list[str] = []
    definition_gaps_found = definition_gaps(form, fields)
    known_ids = {field["id"] for field in fields}
    unknown = sorted(str(key) for key in answers if str(key) not in known_ids)
    if unknown:
        definition_gaps_found.append("answers contain unknown fields: " + ", ".join(unknown))

    for order, field in enumerate(fields, 1):
        field_id = field["id"]
        required = bool(field.get("required")) or field["control"] in CHOICE_CONTROLS
        present, value, has_evidence = answer_entry(answers, field_id)
        if not present and required:
            missing_required.append(field_id)
        if present and not has_evidence:
            missing_evidence.append(field_id)
        if present and field["control"] == "checkbox" and not isinstance(value, bool):
            invalid_answers.append(field_id)
        if present and field["control"] == "yes-no" and not (
            isinstance(value, bool) or str(value).strip().lower() in {"yes", "no"}
        ):
            invalid_answers.append(field_id)
        secret = present and looks_secret(value)
        if secret:
            blocked_secrets.append(field_id)
        personal = personal_field(field)
        if not present:
            display = "[MISSING]"
            action = "skip_missing"
            redacted = False
        elif secret:
            display = "[REDACTED: secret]"
            action = "blocked_secret"
            redacted = True
        elif personal:
            display = "[REDACTED: personal]"
            action = field_action(field, value)
            redacted = True
        else:
            display = text_value(value)
            action = field_action(field, value)
            redacted = False
        plan.append(
            {
                "order": order,
                "field": field_id,
                "label": field["label"],
                "selector": field["selector"],
                "action": action,
                "value": display,
                "redacted": redacted,
                "evidence": "present" if has_evidence else "missing",
            }
        )
        if parser is not None:
            matches = selector_matches(parser, field["selector"])
            if matches is None:
                layout_changes.append(
                    f"{field_id}: selector cannot be checked by the local checker"
                )
                continue
            expected_count = int(field.get("expected_matches", 1))
            if len(matches) != expected_count:
                layout_changes.append(
                    f"{field_id}: selector matched {len(matches)} elements, "
                    f"expected {expected_count}"
                )
                continue
            tag, input_type = expected_tag(field)
            for match in matches:
                if match.get("tag") != tag:
                    layout_changes.append(
                        f"{field_id}: selector points to {match.get('tag')}, expected {tag}"
                    )
                if input_type and match.get("type", "text").lower() != input_type:
                    layout_changes.append(
                        f"{field_id}: control type is {match.get('type', 'text')}, "
                        f"expected {input_type}"
                    )
            id_match = ID_SELECTOR_RE.match(field["selector"])
            if id_match and parser.labels.get(id_match.group(1)) != field["label"]:
                layout_changes.append(
                    f"{field_id}: label changed or is not attached to the control"
                )

    submit_selector = str(form.get("submit_selector", "")).strip()
    if not submit_selector:
        definition_gaps_found.append("form.submit_selector is missing")
        submit_selector = "[submit selector not defined]"
    plan.append(
        {
            "order": len(plan) + 1,
            "field": None,
            "label": "Submission boundary",
            "selector": submit_selector,
            "action": "stop_before_submit",
            "value": None,
            "redacted": False,
            "evidence": "not applicable",
        }
    )
    blockers = (
        missing_required
        + missing_evidence
        + invalid_answers
        + blocked_secrets
        + layout_changes
        + definition_gaps_found
    )
    return {
        "form_id": str(form.get("id", "unknown")),
        "workflow": str(form.get("workflow", "unknown")),
        "dry_run": True,
        "stops_before_submit": True,
        "plan": plan,
        "missing_required": missing_required,
        "missing_evidence": missing_evidence,
        "invalid_answers": invalid_answers,
        "blocked_secrets": blocked_secrets,
        "layout_changes": layout_changes,
        "definition_gaps": definition_gaps_found,
        "ready_to_fill": not blockers,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Dry-run fill plan: {result['form_id']}",
        "",
        f"Workflow: `{result['workflow']}`",
        "Dry run: yes",
        "Stops before submit: yes",
        "",
        "| Order | Field | Selector | Action | Value | Evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in result["plan"]:
        values = (
            entry["order"],
            entry["field"] or "submission boundary",
            entry["selector"],
            entry["action"],
            entry["value"] if entry["value"] is not None else "",
            entry["evidence"],
        )
        cells = " | ".join(text_value(value).replace("|", "\\|") for value in values)
        lines.append(f"| {cells} |")
    for key, heading in (
        ("missing_required", "Missing required answers"),
        ("missing_evidence", "Missing evidence"),
        ("invalid_answers", "Invalid answers"),
        ("blocked_secrets", "Blocked secret-like values"),
        ("layout_changes", "Layout changes"),
        ("definition_gaps", "Definition gaps"),
    ):
        lines.extend(["", f"## {heading}", ""])
        lines.extend(f"- {item}" for item in result[key])
        if not result[key]:
            lines.append("- none")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--form", required=True, type=Path, help="form definition YAML")
    parser.add_argument("--answers", required=True, type=Path, help="answers YAML")
    parser.add_argument(
        "--check-url",
        help="check simple selectors against a local mock URL; loopback HTTP only",
    )
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parser = check_loopback_url(args.check_url) if args.check_url else None
        form_data = load_yaml(args.form, "form definition")
        # Refuse a credential-bearing definition before opening the answer file.
        empty_answers = {"answers": {}}
        validate_inputs(form_data, empty_answers)
        answers_data = load_yaml(args.answers, "answers")
        result = build_plan(
            form_data,
            answers_data,
            parser,
        )
    except PlanError as exc:
        print(f"fill-plan: {exc}", file=sys.stderr)
        return 1
    rendered = (
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.json
        else render_markdown(result)
    )
    if "\u2014" in rendered:
        print("fill-plan: em dash in output", file=sys.stderr)
        return 1
    print(rendered, end="")
    return 0 if result["ready_to_fill"] else 2


if __name__ == "__main__":
    sys.exit(main())
