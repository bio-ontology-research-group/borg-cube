#!/usr/bin/env python3
"""Run deterministic offline checks for an OBO or RDF/XML OWL ontology.

This checker reports declared evidence and structural defects. It does not
assert legal openness, IRI resolvability, governance practice, or logical
consistency without the corresponding external evidence or ROBOT output.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as et
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


OPEN_LICENSES = {"apache-2.0", "bsd-2-clause", "bsd-3-clause", "cc0-1.0", "cc-by-4.0", "gpl-3.0", "mit"}
GOVERNANCE_FIELDS = {
    "scope": ("Scope", "Link a scope statement or README section."),
    "users": ("Documented Plurality of Users", "Link evidence of multiple independent users or organizations."),
    "collaboration": ("Commitment To Collaboration", "Link a contributor or collaboration process."),
    "authority": ("Locus of Authority", "Link the named responsible contact or governance record."),
    "naming_conventions": ("Naming Conventions", "Link the naming policy."),
    "maintenance": ("Maintenance", "Link a release, issue, or maintenance policy."),
}


class InputError(ValueError):
    """An input cannot be checked with a deterministic parser."""


def local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def value_attr(element: et.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if local_name(key) == name:
            return value
    return None


def clean_value(value: str) -> str:
    return " ".join(value.split())


def parse_obo(path: Path) -> dict[str, Any]:
    """Read the header and [Term] stanzas needed for local checks."""
    text = path.read_text(encoding="utf-8")
    header: dict[str, list[str]] = {}
    terms: list[dict[str, Any]] = []
    current: dict[str, list[str]] | None = None
    in_header = True
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line == "[Term]":
            in_header = False
            if current is not None:
                terms.append(current)
            current = {}
            continue
        if line.startswith("["):
            if current is not None:
                terms.append(current)
            current = None
            in_header = False
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        target = header if in_header else current
        if target is not None:
            target.setdefault(key.strip(), []).append(value.strip())
    if current is not None:
        terms.append(current)
    normalized = []
    for term in terms:
        identifier = term.get("id", [""])[0]
        label = term.get("name", [""])[0]
        definition = term.get("def", [""])[0]
        obsolete = term.get("is_obsolete", ["false"])[0].casefold() == "true"
        replacement = term.get("replaced_by", []) + term.get("consider", [])
        normalized.append(
            {
                "id": identifier,
                "label": label,
                "definition": definition,
                "obsolete": obsolete,
                "replacement": replacement,
            }
        )
    version = (header.get("data-version") or header.get("version") or [None])[0]
    return {
        "format": "OBO",
        "terms": normalized,
        "imports": header.get("import", []),
        "version": version,
        "ontology_iri": (header.get("ontology") or [None])[0],
    }


def parse_rdfxml(path: Path) -> dict[str, Any]:
    """Read a RDF/XML OWL document with the standard library XML parser."""
    try:
        root = et.parse(path).getroot()
    except (et.ParseError, OSError) as exc:
        raise InputError(f"RDF/XML parser could not read {path.name}: {exc}") from exc
    terms: list[dict[str, Any]] = []
    imports: list[str] = []
    version: str | None = None
    ontology_iri: str | None = None
    for element in root.iter():
        name = local_name(element.tag)
        if name == "Ontology":
            ontology_iri = value_attr(element, "about") or ontology_iri
            version = value_attr(element, "versionIRI") or version
            for child in element:
                child_name = local_name(child.tag)
                if child_name == "versionIRI":
                    version = value_attr(child, "resource") or clean_value(child.text or "") or version
                elif child_name == "imports":
                    imported = value_attr(child, "resource") or (child.text or "").strip()
                    if imported:
                        imports.append(imported)
        if name != "Class":
            continue
        identifier = value_attr(element, "about") or value_attr(element, "ID") or ""
        label = ""
        definition = ""
        obsolete = False
        replacement: list[str] = []
        for child in element:
            child_name = local_name(child.tag)
            text = clean_value(child.text or "")
            if child_name == "label" and text:
                label = text
            elif child_name in {"IAO_0000115", "definition"} and text:
                definition = text
            elif child_name == "deprecated" and text.casefold() == "true":
                obsolete = True
            elif child_name in {"IAO_0100001", "consider"}:
                target = value_attr(child, "resource") or text
                if target:
                    replacement.append(target)
        terms.append({"id": identifier, "label": label, "definition": definition, "obsolete": obsolete, "replacement": replacement})
    if not terms:
        raise InputError("RDF/XML contains no owl:Class elements; Turtle, Functional Syntax, and Manchester Syntax are not supported offline")
    return {"format": "RDF/XML OWL", "terms": terms, "imports": imports, "version": version, "ontology_iri": ontology_iri}


def parse_ontology(path: Path) -> dict[str, Any]:
    suffix = path.suffix.casefold()
    if suffix == ".obo":
        return parse_obo(path)
    if suffix in {".owl", ".rdf", ".xml"}:
        return parse_rdfxml(path)
    raise InputError("unsupported suffix; supply an .obo, RDF/XML .owl, .rdf, or .xml file")


def load_metadata(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read metadata: {exc}") from exc
    except yaml.YAMLError as exc:
        raise InputError(f"invalid metadata YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("metadata must be a YAML mapping")
    imports = data.get("imports", [])
    if not isinstance(imports, list) or not all(isinstance(value, str) for value in imports):
        raise InputError("metadata imports must be a list of strings")
    pattern = data.get("identifier_pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise InputError("identifier_pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise InputError(f"invalid identifier_pattern: {exc}") from exc
    return data


def finding(identifier: str, severity: str, level: str, message: str, fix: str) -> dict[str, str]:
    return {"id": identifier, "severity": severity, "level": level, "message": message, "fix": fix}


def _open_license(value: str) -> bool:
    normalized = value.casefold().replace(" ", "-")
    return normalized in OPEN_LICENSES or normalized.startswith("cc-by-") or normalized.startswith("cc0-")


def check_ontology(ontology: dict[str, Any], metadata: dict[str, Any], source: Path) -> dict[str, Any]:
    """Check structural and declared repository evidence without network access."""
    findings: list[dict[str, str]] = []
    passed: list[str] = [f"Common Format: parsed {ontology['format']} from {source.name}"]
    license_value = metadata.get("license")
    if not isinstance(license_value, str) or not license_value.strip():
        findings.append(finding("license:missing", "error", "file", "Open: no declared license in metadata", "Add the release license identifier and repository evidence."))
    elif _open_license(license_value):
        passed.append(f"Open: declared license {license_value}")
    else:
        findings.append(finding("license:unverified", "warning", "file", f"Open: declared license is not recognized as open by this offline checker: {license_value}", "Confirm the license is open and record a standard identifier."))
    actual_version = ontology.get("version")
    expected_version = metadata.get("version_iri") or metadata.get("version")
    if not actual_version:
        findings.append(finding("version:missing", "error", "file", "Versioning: no version marker found in the ontology", "Add owl:versionIRI to RDF/XML or data-version to OBO, then release it through the documented process."))
    elif isinstance(expected_version, str) and expected_version and actual_version != expected_version:
        findings.append(finding("version:mismatch", "warning", "file", f"Versioning: ontology value {actual_version!r} differs from metadata {expected_version!r}", "Confirm the intended release version and update the ontology or metadata."))
    else:
        passed.append(f"Versioning: ontology marker {actual_version}")
    pattern = metadata.get("identifier_pattern")
    if not isinstance(pattern, str) or not pattern:
        findings.append(finding("identifier-pattern:missing", "error", "file", "URI/Identifier Space: metadata has no identifier_pattern", "Declare a regular expression for this ontology's stable identifiers."))
        compiled = None
    else:
        compiled = re.compile(pattern)
        passed.append("URI/Identifier Space: identifier pattern declared")
    terms = ontology["terms"]
    active = [term for term in terms if not term["obsolete"]]
    for term in terms:
        identifier = term["id"] or "<missing-id>"
        if not term["id"]:
            findings.append(finding("term:id-missing", "error", "term", "URI/Identifier Space: term has no identifier", "Assign a stable ontology identifier."))
        elif compiled and not compiled.fullmatch(term["id"]):
            findings.append(finding(f"term:{identifier}:identifier", "error", "term", f"URI/Identifier Space: identifier does not match {pattern!r}", "Use the declared identifier policy or correct the metadata pattern."))
        if not term["label"]:
            findings.append(finding(f"term:{identifier}:label", "error", "term", "Naming Conventions: term has no primary label", "Add one unique primary label."))
        if not term["obsolete"] and not term["definition"]:
            findings.append(finding(f"term:{identifier}:definition", "error", "term", "Textual Definitions: active term has no textual definition", "Add a textual definition with appropriate provenance."))
        if term["obsolete"] and not term["replacement"]:
            findings.append(finding(f"term:{identifier}:obsolete", "warning", "term", "obsolete term has no replacement or consideration", "Add replaced_by or consider when a safe successor exists, or document why none exists."))
    labels = Counter(term["label"].casefold() for term in terms if term["label"])
    for label, count in labels.items():
        if count > 1:
            matching = [term["id"] for term in terms if term["label"].casefold() == label]
            findings.append(finding(f"label:{label}", "error", "term", f"Naming Conventions: duplicate primary label used by {', '.join(matching)}", "Choose unique primary labels and retain suitable synonyms."))
    if terms and all(term["label"] for term in terms) and all(term["definition"] for term in active) and all(count == 1 for count in labels.values()):
        passed.append("Textual Definitions and Naming Conventions: all active terms have definitions and labels are unique")
    expected_imports = metadata.get("imports", [])
    actual_imports = ontology["imports"]
    missing_imports = sorted(set(expected_imports) - set(actual_imports))
    unexpected_imports = sorted(set(actual_imports) - set(expected_imports))
    if missing_imports:
        findings.append(finding("imports:missing", "error", "file", f"declared imports absent from ontology: {', '.join(missing_imports)}", "Add the imports or correct the repository metadata."))
    if unexpected_imports:
        findings.append(finding("imports:undeclared", "warning", "file", f"ontology imports not listed in metadata: {', '.join(unexpected_imports)}", "Record each intentional import in metadata and review its release policy."))
    if not missing_imports and not unexpected_imports:
        passed.append(f"imports: metadata and ontology agree on {len(actual_imports)} import(s)")
    for key, (principle, fix) in GOVERNANCE_FIELDS.items():
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            findings.append(finding(f"governance:{key}", "warning", "file", f"{principle}: no repository evidence declared", fix))
        else:
            passed.append(f"{principle}: evidence declared")
    findings.sort(key=lambda item: (item["severity"], item["level"], item["id"]))
    summary = Counter(item["severity"] for item in findings)
    return {
        "file": str(source),
        "format": ontology["format"],
        "ontology_iri": ontology.get("ontology_iri"),
        "term_count": len(terms),
        "active_term_count": len(active),
        "findings": findings,
        "passed": passed,
        "summary": {"errors": summary["error"], "warnings": summary["warning"], "info": summary["info"]},
    }


def robot_probe(path: Path, run_robot: bool) -> list[dict[str, str]]:
    """Clearly report ROBOT availability, and optionally run report and reason."""
    robot = shutil.which("robot")
    if not robot:
        return [finding("robot:unavailable", "info", "file", "ROBOT is not installed; ROBOT report and reasoning were not run", "Install ROBOT, then run robot reason and robot report on the release artifact.")]
    if not run_robot:
        return [finding("robot:not-run", "info", "file", "ROBOT is installed but was not run; use --robot to run ephemeral reasoning and report checks", "Run with --robot or preserve explicit ROBOT artifacts under runs/.")]
    with tempfile.TemporaryDirectory(prefix="obo-check-") as directory:
        work = Path(directory)
        reasoned = work / "reasoned.owl"
        report = work / "robot-report.json"
        reason = subprocess.run([robot, "reason", "--input", str(path), "--output", str(reasoned)], capture_output=True, text=True, check=False)
        if reason.returncode != 0:
            detail = (reason.stderr or reason.stdout).strip().splitlines()[-1:] or ["no diagnostic output"]
            return [finding("robot:reason-failed", "error", "file", f"ROBOT reason failed: {detail[0]}", "Inspect the ontology, imports, and reasoner configuration; preserve the command output in the review report.")]
        report_run = subprocess.run([robot, "report", "--input", str(reasoned), "--format", "json", "--output", str(report), "--fail-on", "none"], capture_output=True, text=True, check=False)
        if report_run.returncode != 0:
            detail = (report_run.stderr or report_run.stdout).strip().splitlines()[-1:] or ["no diagnostic output"]
            return [finding("robot:report-failed", "error", "file", f"ROBOT report failed: {detail[0]}", "Inspect the ROBOT configuration and preserve a report artifact under runs/ for review.")]
        return [finding("robot:completed", "info", "file", "ROBOT reason and report completed in a temporary directory; no persistent report was written", "Run the documented ROBOT commands with outputs under runs/ to retain review evidence.")]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", type=Path, required=True, help="OBO or RDF/XML OWL ontology")
    parser.add_argument("--metadata", type=Path, required=True, help="repository evidence YAML")
    parser.add_argument("--robot", action="store_true", help="run ephemeral ROBOT reason and report checks when ROBOT is installed")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ontology = parse_ontology(args.ontology)
        metadata = load_metadata(args.metadata)
        result = check_ontology(ontology, metadata, args.ontology)
    except (InputError, OSError, UnicodeError) as exc:
        print(f"obo-check: {exc}", file=sys.stderr)
        return 2
    robot_findings = robot_probe(args.ontology, args.robot)
    result["findings"].extend(robot_findings)
    result["summary"]["info"] += sum(item["severity"] == "info" for item in robot_findings)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["findings"]:
            print(f"{item['severity'].upper():7} {item['level']:4} {item['id']}: {item['message']}")
        summary = result["summary"]
        print(f"obo-check: {summary['errors']} error(s), {summary['warnings']} warning(s), {summary['info']} info item(s)")
    return 1 if result["summary"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
