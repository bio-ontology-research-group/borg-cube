#!/usr/bin/env python3
"""Prepare a complete, redacted administrative form review package.

The script reads a form definition YAML and an answers YAML, then produces:

* a field-by-field table;
* missing required answers, missing evidence, and definition gaps;
* the evidence attached to each non-sensitive answer;
* a redacted approval bead body for Robert.

It cannot open a browser or submit, sign, approve, purchase, pay, or send.
Output is printed by default. ``--out`` writes only when ``--apply`` is also
given.

Example:
  form_prepare.py --form definition.yaml --answers answers.yaml --json
  form_prepare.py --form definition.yaml --answers answers.yaml \
      --screenshot runs/42/form.png --field-table runs/42/form.md \
      --out runs/42/form.md --apply
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
FORBIDDEN_FIELD_RE = re.compile(
    r"(?:password|passwd|\bpwd\b|credential|api[_ -]?key|access[_ -]?token|"
    r"auth(?:entication|orization)?[_ -]?token|private[_ -]?key)",
    re.IGNORECASE,
)
PERSONAL_FIELD_RE = re.compile(
    r"(?:passport|salary|grade|\bgpa\b|health|medical|visa|contract|iqama|"
    r"national[_ -]?id|identity|date[_ -]?of[_ -]?birth|birth[_ -]?date|"
    r"address|phone|email|full[_ -]?name|requester[_ -]?name|student[_ -]?name)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
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


class PreparationError(Exception):
    """A safe, user-facing input error."""


def load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PreparationError(f"cannot read {label} YAML: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PreparationError(f"{label} YAML must be a mapping")
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
    return any(pattern.search(rendered) for pattern in SECRET_VALUE_PATTERNS)


def is_personal(field: dict[str, Any]) -> bool:
    sensitivity = str(field.get("sensitivity", "none")).strip().lower()
    if sensitivity in {"personal", "local-only", "sensitive"}:
        return True
    haystack = f"{field.get('id', '')} {field.get('label', '')}"
    return bool(PERSONAL_FIELD_RE.search(haystack))


def evidence_strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            source = str(item.get("source", "")).strip()
            locator = str(item.get("locator", "")).strip()
            if source and locator:
                out.append(f"{source}::{locator}")
            elif source:
                out.append(source)
    return out


def answer_entry(answers: dict[str, Any], field_id: str) -> tuple[bool, Any, list[str]]:
    if field_id not in answers:
        return False, None, []
    raw = answers[field_id]
    if isinstance(raw, dict) and ("value" in raw or "present" in raw or "evidence" in raw):
        value = raw.get("value")
        present = bool(raw.get("present", has_value(value)))
        return present, value, evidence_strings(raw.get("evidence"))
    return has_value(raw), raw, []


def source_summary(source: Any) -> tuple[str, list[str]]:
    gaps: list[str] = []
    if not isinstance(source, dict):
        return "missing", ["form.source must be a mapping"]
    path = str(source.get("path") or source.get("url") or "").strip()
    locator = str(source.get("locator") or "").strip()
    verified = str(source.get("verified_on") or "").strip()
    if not path:
        gaps.append("form.source needs path or url")
    elif PLACEHOLDER_RE.search(path):
        gaps.append("form.source path or url is a placeholder")
    if not locator:
        gaps.append("form.source needs locator")
    elif PLACEHOLDER_RE.search(locator):
        gaps.append("form.source locator is a placeholder")
    try:
        dt.date.fromisoformat(verified)
    except ValueError:
        gaps.append("form.source.verified_on must be an ISO date")
    rendered = path or "missing"
    if locator:
        rendered += f"::{locator}"
    if verified:
        rendered += f" (verified {verified})"
    return rendered, gaps


def validate_definition(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    form = data.get("form")
    fields = data.get("fields")
    if not isinstance(form, dict):
        raise PreparationError("form definition needs a 'form' mapping")
    if not isinstance(fields, list) or not fields:
        raise PreparationError("form definition needs a non-empty 'fields' list")
    for key in ("id", "title", "workflow"):
        if not str(form.get(key, "")).strip():
            raise PreparationError(f"form.{key} is required")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    gaps: list[str] = []
    _, source_gaps = source_summary(form.get("source"))
    gaps.extend(source_gaps)
    for index, raw in enumerate(fields, 1):
        if not isinstance(raw, dict):
            raise PreparationError(f"field {index} must be a mapping")
        field = dict(raw)
        field_id = str(field.get("id", "")).strip()
        label = str(field.get("label", "")).strip()
        selector = str(field.get("selector", "")).strip()
        control = str(field.get("control", "text")).strip().lower()
        if not field_id or not label or not selector:
            raise PreparationError(f"field {index} needs id, label, and selector")
        if field_id in seen:
            raise PreparationError(f"duplicate field id: {field_id}")
        seen.add(field_id)
        if FORBIDDEN_FIELD_RE.search(f"{field_id} {label} {selector}"):
            raise PreparationError("password and credential fields are forbidden")
        if control == "password" or control not in ALLOWED_CONTROLS:
            raise PreparationError(f"field {field_id}: unsupported control {control!r}")
        action = str(field.get("action", "")).lower()
        if action in {"submit", "sign", "approve", "pay", "purchase", "send"}:
            raise PreparationError(f"field {field_id}: external action is forbidden")
        field.update(id=field_id, label=label, selector=selector, control=control)
        normalized.append(field)
    steps = form.get("steps")
    if not isinstance(steps, list) or not steps:
        gaps.append("form.steps must list the verified order")
    signers = form.get("signers")
    if not isinstance(signers, list) or not signers:
        gaps.append("form.signers must list verified signer or approver roles")
    evidence = form.get("evidence_requirements")
    if not isinstance(evidence, list) or not evidence:
        gaps.append("form.evidence_requirements must list required supporting evidence")
    if not str(form.get("submit_selector", "")).strip():
        gaps.append("form.submit_selector is needed only to mark the stopping point")
    return form, normalized, gaps


def answer_valid(field: dict[str, Any], value: Any) -> bool:
    control = field["control"]
    if control == "checkbox":
        return isinstance(value, bool)
    if control == "yes-no":
        return isinstance(value, bool) or str(value).strip().lower() in {"yes", "no"}
    options = field.get("options")
    if options and control in {"select", "radio"}:
        allowed = [
            text_value(option.get("value"))
            if isinstance(option, dict)
            else text_value(option)
            for option in options
        ]
        return text_value(value) in allowed
    return True


def markdown_escape(value: Any) -> str:
    return text_value(value).replace("|", "\\|").replace("\n", "<br>")


def render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Field | Control | Required | Proposed answer | Evidence | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        evidence = "; ".join(row["evidence"]) or "missing"
        lines.append(
            "| "
            + " | ".join(
                markdown_escape(value)
                for value in (
                    row["label"],
                    row["control"],
                    row["required"],
                    row["value"],
                    evidence,
                    row["status"],
                )
            )
            + " |"
        )
    return "\n".join(lines)


def safe_locator(value: Any) -> str:
    rendered = text_value(value)
    if PERSONAL_FIELD_RE.search(rendered) or FORBIDDEN_FIELD_RE.search(rendered):
        return "[REDACTED: sensitive locator]"
    if looks_secret(rendered):
        return "[REDACTED: secret]"
    return rendered


def request_provenance(data: dict[str, Any]) -> list[dict[str, str]]:
    raw = data.get("provenance")
    values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    out: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            out.append({"source": safe_locator(item.strip()), "locator": "request"})
        elif isinstance(item, dict):
            source = str(item.get("source", "")).strip()
            locator = str(item.get("locator", "")).strip()
            if source:
                out.append(
                    {
                        "source": safe_locator(source),
                        "locator": safe_locator(locator or "request"),
                    }
                )
    return out


def render_bead(
    form: dict[str, Any],
    answers_data: dict[str, Any],
    source: str,
    table: str,
    screenshot: str | None,
    field_table: str | None,
    approval_ready: bool,
    problems: list[str],
) -> str:
    request_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(answers_data.get("request_id") or "request"))
    form_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(form["id"]))
    provenance = request_provenance(answers_data)
    provenance.append({"source": safe_locator(source), "locator": "form definition"})
    header = {
        "xid": f"approval:admin-form:{request_id}:{form_id}",
        "provenance": provenance,
        "deadline": answers_data.get("deadline"),
        "privacy": "internal",
    }
    lines = [
        "---",
        yaml.safe_dump(header, sort_keys=False, allow_unicode=True).rstrip(),
        "---",
        "kind: outbound",
        f"action: Robert to review and, if appropriate, submit {form['title']}",
        f"workflow: {form['workflow']}",
        f"form source: {source}",
        f"approval ready: {'yes' if approval_ready else 'no'}",
        f"redacted screenshot: {safe_locator(screenshot) if screenshot else 'missing'}",
        f"redacted field table: {safe_locator(field_table) if field_table else 'missing'}",
        "",
        "## Field table",
        "",
        table,
        "",
        "## Blocking items",
        "",
    ]
    lines.extend(f"- {problem}" for problem in problems)
    if not problems:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Approval boundary",
            "",
            "Robert performs any submit, signature, approval, payment, purchase, or send. "
            "The preparation scripts cannot perform that action.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def prepare(
    form_data: dict[str, Any],
    answers_data: dict[str, Any],
    screenshot: str | None = None,
    field_table: str | None = None,
) -> dict[str, Any]:
    form, fields, definition_gaps = validate_definition(form_data)
    answers = answers_data.get("answers")
    if not isinstance(answers, dict):
        raise PreparationError("answers YAML needs an 'answers' mapping")
    unknown_answers = sorted(set(str(key) for key in answers) - {field["id"] for field in fields})
    if unknown_answers:
        definition_gaps.append("answers contain unknown fields: " + ", ".join(unknown_answers))
    if not request_provenance(answers_data):
        definition_gaps.append("answers provenance is missing")

    rows: list[dict[str, Any]] = []
    missing_required: list[str] = []
    missing_evidence: list[str] = []
    invalid_answers: list[str] = []
    blocked_secrets: list[str] = []
    for field in fields:
        field_id = field["id"]
        required = bool(field.get("required")) or field["control"] in CHOICE_CONTROLS
        present, value, evidence = answer_entry(answers, field_id)
        personal = is_personal(field)
        if not present and required:
            missing_required.append(field_id)
        if present and not evidence:
            missing_evidence.append(field_id)
        valid = not present or answer_valid(field, value)
        if present and not valid:
            invalid_answers.append(field_id)
        secret = present and looks_secret(value)
        if secret:
            blocked_secrets.append(field_id)
        if not present:
            display = "missing"
            status = "missing" if required else "not provided"
        elif secret:
            display = "[REDACTED: secret]"
            status = "blocked secret"
        elif personal:
            display = "[REDACTED: personal]"
            status = "ready, redacted" if valid and evidence else "needs evidence"
        else:
            display = text_value(value)
            status = (
                "ready"
                if valid and evidence
                else ("invalid" if not valid else "needs evidence")
            )
        rows.append(
            {
                "id": field_id,
                "label": field["label"],
                "selector": field["selector"],
                "control": field["control"],
                "required": required,
                "value": display,
                "evidence": ["[REDACTED: personal evidence]"]
                if personal and evidence
                else evidence,
                "status": status,
            }
        )

    approval_artifact_gaps: list[str] = []
    if not screenshot:
        approval_artifact_gaps.append("redacted screenshot path is missing")
    if not field_table:
        approval_artifact_gaps.append("redacted field table path is missing")
    problem_groups = {
        "missing required answer": missing_required,
        "missing answer evidence": missing_evidence,
        "invalid answer": invalid_answers,
        "secret-like value refused": blocked_secrets,
        "definition gap": definition_gaps,
        "approval artifact gap": approval_artifact_gaps,
    }
    problems = [f"{label}: {item}" for label, items in problem_groups.items() for item in items]
    approval_ready = not problems
    source, _ = source_summary(form.get("source"))
    table = render_table(rows)
    result: dict[str, Any] = {
        "form": {
            "id": form["id"],
            "title": form["title"],
            "workflow": form["workflow"],
            "source": source,
        },
        "steps": form.get("steps") if isinstance(form.get("steps"), list) else [],
        "signers": form.get("signers") if isinstance(form.get("signers"), list) else [],
        "evidence_requirements": form.get("evidence_requirements")
        if isinstance(form.get("evidence_requirements"), list)
        else [],
        "fields": rows,
        "missing_required": missing_required,
        "missing_evidence": missing_evidence,
        "invalid_answers": invalid_answers,
        "blocked_secrets": blocked_secrets,
        "definition_gaps": definition_gaps,
        "approval_artifact_gaps": approval_artifact_gaps,
        "approval_ready": approval_ready,
        "field_table_markdown": table,
    }
    result["approval_bead_body"] = render_bead(
        form,
        answers_data,
        source,
        table,
        screenshot,
        field_table,
        approval_ready,
        problems,
    )
    return result


def render_markdown(result: dict[str, Any]) -> str:
    form = result["form"]
    lines = [
        f"# Form preparation: {form['title']}",
        "",
        f"Workflow: `{form['workflow']}`",
        f"Source: {form['source']}",
        f"Approval ready: {'yes' if result['approval_ready'] else 'no'}",
        "",
        "## Workflow order",
        "",
    ]
    steps = result["steps"]
    lines.extend(f"{index}. {text_value(step)}" for index, step in enumerate(steps, 1))
    if not steps:
        lines.append("- missing")
    lines.extend(["", "## Required evidence", ""])
    requirements = result["evidence_requirements"]
    lines.extend(f"- {markdown_escape(item)}" for item in requirements)
    if not requirements:
        lines.append("- missing")
    lines.extend(["", "## Signers and approvers", ""])
    signers = result["signers"]
    lines.extend(f"- {markdown_escape(item)}" for item in signers)
    if not signers:
        lines.append("- missing")
    lines.extend(["", "## Field table", "", result["field_table_markdown"], ""])
    for key, heading in (
        ("missing_required", "Missing required answers"),
        ("missing_evidence", "Missing answer evidence"),
        ("invalid_answers", "Invalid answers"),
        ("blocked_secrets", "Blocked secret-like values"),
        ("definition_gaps", "Definition gaps"),
        ("approval_artifact_gaps", "Approval artifact gaps"),
    ):
        lines.extend([f"## {heading}", ""])
        lines.extend(f"- {item}" for item in result[key])
        if not result[key]:
            lines.append("- none")
        lines.append("")
    lines.extend(["## Approval bead body", "", result["approval_bead_body"].rstrip(), ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--form", required=True, type=Path, help="form definition YAML")
    parser.add_argument("--answers", required=True, type=Path, help="answers YAML")
    parser.add_argument("--screenshot", help="path to the redacted screenshot for approval")
    parser.add_argument("--field-table", help="path to the redacted field table for approval")
    parser.add_argument("--json", action="store_true", help="render the preparation as JSON")
    parser.add_argument("--out", type=Path, help="write the rendered result to this path")
    parser.add_argument("--apply", action="store_true", help="allow --out to be written")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        form_data = load_yaml(args.form, "form definition")
        # Refuse a credential-bearing definition before opening the answer file.
        validate_definition(form_data)
        answers_data = load_yaml(args.answers, "answers")
        result = prepare(
            form_data,
            answers_data,
            screenshot=args.screenshot,
            field_table=args.field_table,
        )
    except PreparationError as exc:
        print(f"form-prepare: {exc}", file=sys.stderr)
        return 1
    rendered = (
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.json
        else render_markdown(result)
    )
    if "\u2014" in rendered:
        print("form-prepare: em dash in output", file=sys.stderr)
        return 1
    if args.out and args.apply:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"form-prepare: wrote {args.out}", file=sys.stderr)
    else:
        print(rendered, end="")
        if args.out:
            print("form-prepare: dry run, rerun with --apply to write --out", file=sys.stderr)
    return 0 if result["approval_ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
