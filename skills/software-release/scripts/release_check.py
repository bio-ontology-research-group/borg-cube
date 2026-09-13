#!/usr/bin/env python3
"""Inspect a repository for a citable, versioned software release.

The checker is deliberately read-only. It reports deterministic evidence and
does not build, upload, tag, archive, or edit the target repository.
"""

from __future__ import annotations

import argparse
import configparser
import datetime as dt
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[0-9A-Za-z-][0-9A-Za-z-]*)(?:\."
    r"(?:0|[1-9]\d*|\d*[0-9A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHANGE_TYPES = {"added", "changed", "deprecated", "removed", "fixed", "security"}
CHANGELOG_NAMES = (
    "CHANGELOG.md",
    "CHANGELOG",
    "HISTORY.md",
    "NEWS.md",
    "RELEASES.md",
)
CI_PATHS = (
    ".github/workflows",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    ".travis.yml",
    ".buildkite",
)
KNOWN_CFF_TYPES = {
    "cff-version": str,
    "message": str,
    "title": str,
    "version": str,
    "date-released": (str, dt.date),
    "authors": list,
    "identifiers": list,
    "keywords": list,
    "references": list,
    "repository-code": str,
    "repository-artifact": str,
    "url": str,
    "abstract": str,
    "license": str,
    "preferred-citation": dict,
}


def _finding(
    finding_id: str,
    severity: str,
    message: str,
    fix: str,
    location: str,
    evidence: str | None = None,
    sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": finding_id,
        "severity": severity,
        "message": message,
        "fix": fix,
        "location": location,
    }
    if evidence:
        result["evidence"] = evidence
    if sources:
        result["sources"] = list(sources)
    return result


def _add(
    findings: list[dict[str, Any]],
    finding_id: str,
    severity: str,
    message: str,
    fix: str,
    location: str,
    evidence: str | None = None,
    sources: tuple[str, ...] = (),
) -> None:
    findings.append(_finding(finding_id, severity, message, fix, location, evidence, sources))


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _line_number(text: str, fragment: str) -> int | None:
    for number, line in enumerate(text.splitlines(), 1):
        if fragment in line:
            return number
    return None


def _location(path: Path, text: str | None = None, fragment: str | None = None) -> str:
    if text is not None and fragment:
        line = _line_number(text, fragment)
        if line is not None:
            return f"{path}:{line}"
    return str(path)


def _version(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata(repo: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Read common packaging metadata without importing or executing project code."""
    versions: list[dict[str, str]] = []
    dependencies: list[dict[str, str]] = []
    files: list[Path] = []
    project_name: str | None = None
    description: str | None = None
    urls: dict[str, str] = {}
    license_value: str | None = None

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        files.append(pyproject)
        text = _read_text(pyproject)
        try:
            data = tomllib.loads(text or "")
        except tomllib.TOMLDecodeError as exc:
            _add(
                findings,
                "metadata:pyproject-invalid",
                "error",
                f"pyproject.toml cannot be parsed: {exc}",
                "Repair the TOML before releasing.",
                str(pyproject),
                sources=("python-packaging-guide",),
            )
            data = {}
        project = data.get("project") if isinstance(data, dict) else None
        if isinstance(project, dict):
            project_name = _version(project.get("name")) or project_name
            description = _version(project.get("description")) or description
            license_data = project.get("license")
            if isinstance(license_data, dict):
                license_value = _version(license_data.get("text")) or _version(
                    license_data.get("file")
                )
            elif isinstance(license_data, str):
                license_value = license_data
            if isinstance(project.get("urls"), dict):
                urls.update({str(k): str(v) for k, v in project["urls"].items()})
            if "version" in project:
                value = _version(project.get("version"))
                if value:
                    versions.append({"source": "pyproject.toml [project]", "version": value})
            elif "version" in project.get("dynamic", []):
                _add(
                    findings,
                    "version:dynamic",
                    "error",
                    "pyproject.toml declares a dynamic version that this read-only checker "
                    "cannot resolve",
                    "Expose a direct version or pass --version and verify the backend separately.",
                    str(pyproject),
                    sources=("python-packaging-guide",),
                )
            for key in ("dependencies",):
                values = project.get(key, [])
                if isinstance(values, list):
                    dependencies.extend(
                        {"spec": str(value), "location": str(pyproject)}
                        for value in values
                        if isinstance(value, str) and value.strip()
                    )
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                for values in optional.values():
                    if isinstance(values, list):
                        dependencies.extend(
                            {"spec": str(value), "location": str(pyproject)}
                            for value in values
                            if isinstance(value, str) and value.strip()
                        )
        poetry = data.get("tool", {}).get("poetry") if isinstance(data, dict) else None
        if isinstance(poetry, dict):
            value = _version(poetry.get("version"))
            if value:
                versions.append({"source": "pyproject.toml [tool.poetry]", "version": value})
            project_name = _version(poetry.get("name")) or project_name
            description = _version(poetry.get("description")) or description
            deps = poetry.get("dependencies", {})
            if isinstance(deps, dict):
                for name, spec in deps.items():
                    if name.lower() != "python":
                        dependencies.append(
                            {"spec": f"{name} {spec}", "location": str(pyproject)}
                        )

    setup_cfg = repo / "setup.cfg"
    if setup_cfg.exists():
        files.append(setup_cfg)
        text = _read_text(setup_cfg) or ""
        parser = configparser.RawConfigParser()
        try:
            parser.read_string(text)
        except configparser.Error as exc:
            _add(
                findings,
                "metadata:setup-cfg-invalid",
                "error",
                f"setup.cfg cannot be parsed: {exc}",
                "Repair setup.cfg before releasing.",
                str(setup_cfg),
                sources=("python-packaging-guide",),
            )
        if parser.has_section("metadata"):
            value = _version(parser.get("metadata", "version", fallback=""))
            if value:
                versions.append({"source": "setup.cfg [metadata]", "version": value})
            project_name = _version(parser.get("metadata", "name", fallback="")) or project_name
        if parser.has_section("options"):
            raw = parser.get("options", "install_requires", fallback="")
            dependencies.extend(
                {"spec": line.strip(), "location": str(setup_cfg)}
                for line in raw.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )

    setup_py = repo / "setup.py"
    if setup_py.exists():
        files.append(setup_py)
        text = _read_text(setup_py) or ""
        match = re.search(r"\bversion\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            versions.append({"source": "setup.py", "version": match.group(1)})
        name_match = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", text)
        if name_match:
            project_name = project_name or name_match.group(1)
        req_match = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if req_match:
            dependencies.extend(
                {"spec": value, "location": str(setup_py)}
                for value in re.findall(r"['\"]([^'\"]+)['\"]", req_match.group(1))
            )

    package_json = repo / "package.json"
    if package_json.exists():
        files.append(package_json)
        text = _read_text(package_json)
        try:
            package = json.loads(text or "")
        except json.JSONDecodeError as exc:
            _add(
                findings,
                "metadata:package-json-invalid",
                "error",
                f"package.json cannot be parsed: {exc}",
                "Repair package.json before releasing.",
                str(package_json),
            )
            package = {}
        if isinstance(package, dict):
            value = _version(package.get("version"))
            if value:
                versions.append({"source": "package.json", "version": value})
            project_name = project_name or _version(package.get("name"))
            description = description or _version(package.get("description"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                values = package.get(section, {})
                if isinstance(values, dict):
                    dependencies.extend(
                        {"spec": f"{name} {spec}", "location": str(package_json)}
                        for name, spec in values.items()
                    )

    cargo = repo / "Cargo.toml"
    if cargo.exists():
        files.append(cargo)
        text = _read_text(cargo)
        try:
            data = tomllib.loads(text or "")
        except tomllib.TOMLDecodeError as exc:
            _add(
                findings,
                "metadata:cargo-invalid",
                "error",
                f"Cargo.toml cannot be parsed: {exc}",
                "Repair Cargo.toml before releasing.",
                str(cargo),
            )
            data = {}
        package = data.get("package") if isinstance(data, dict) else None
        if isinstance(package, dict):
            value = _version(package.get("version"))
            if value:
                versions.append({"source": "Cargo.toml [package]", "version": value})
            project_name = project_name or _version(package.get("name"))
        deps = data.get("dependencies") if isinstance(data, dict) else None
        if isinstance(deps, dict):
            for name, spec in deps.items():
                value = spec.get("version") if isinstance(spec, dict) else spec
                dependencies.append({"spec": f"{name} {value}", "location": str(cargo)})

    for path in sorted(repo.glob("requirements*.txt")):
        files.append(path)
        text = _read_text(path) or ""
        for line_number, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith(("-r", "--", "-c")):
                continue
            if line.startswith("-e "):
                continue
            dependencies.append({"spec": line, "location": f"{path}:{line_number}"})

    for environment in sorted(repo.glob("environment*.y*ml")):
        files.append(environment)
        try:
            data = yaml.safe_load(_read_text(environment) or "") or {}
        except yaml.YAMLError as exc:
            _add(
                findings,
                "metadata:environment-invalid",
                "error",
                f"{environment.name} cannot be parsed: {exc}",
                "Repair the environment file before releasing.",
                str(environment),
            )
            data = {}
        values = data.get("dependencies", []) if isinstance(data, dict) else []
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.lower() != "python":
                    dependencies.append({"spec": value, "location": str(environment)})
                elif isinstance(value, dict):
                    pip_values = value.get("pip", [])
                    if isinstance(pip_values, list):
                        dependencies.extend(
                            {"spec": item, "location": str(environment)}
                            for item in pip_values
                            if isinstance(item, str)
                        )

    return {
        "versions": versions,
        "dependencies": dependencies,
        "files": files,
        "project_name": project_name,
        "description": description,
        "urls": urls,
        "license": license_value,
    }


def _bounded(spec: str) -> bool:
    clean = spec.strip()
    if not clean or clean.startswith(("git+", "http://", "https://", "file:", ".", "/")):
        return False
    clean = clean.split(";", 1)[0].strip()
    match = re.match(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?\s*(.*)$", clean)
    if not match:
        return False
    operators = match.group(1)
    if not operators:
        return False
    if "==" in operators or "~=" in operators or "^" in operators or "~" in operators:
        return True
    return "<" in operators


def _git_tags(repo: Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "tag", "--list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _git_revision(repo: Path, ref: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _git_log_dates(repo: Path) -> list[dt.date] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "log", "--format=%aI"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    dates: list[dt.date] = []
    for value in proc.stdout.splitlines():
        try:
            dates.append(dt.datetime.fromisoformat(value.strip()).date())
        except ValueError:
            continue
    return dates


def _find_changelog(repo: Path) -> Path | None:
    for name in CHANGELOG_NAMES:
        path = repo / name
        if path.is_file():
            return path
    return None


def _check_version_and_tag(
    repo: Path,
    expected: str | None,
    metadata: dict[str, Any],
    findings: list[dict[str, Any]],
    passed: list[str],
) -> None:
    versions = metadata["versions"]
    values = {item["version"] for item in versions}
    for item in versions:
        if not SEMVER_RE.fullmatch(item["version"]):
            _add(
                findings,
                f"version:invalid:{item['source']}",
                "error",
                f"{item['source']} uses {item['version']!r}, which is not SemVer 2.0.0",
                "Choose a MAJOR.MINOR.PATCH release value or document a human-reviewed mapping.",
                item["source"],
                sources=("semver2",),
            )
    if len(values) > 1:
        _add(
            findings,
            "version:metadata-mismatch",
            "error",
            f"packaging metadata contains conflicting versions: {sorted(values)}",
            "Make every packaging manifest use the intended release version.",
            "packaging metadata",
            sources=("semver2", "python-packaging-guide"),
        )
    if not versions and expected:
        _add(
            findings,
            "version:packaging-missing",
            "error",
            "no direct version was found in a supported packaging manifest",
            "Add a direct version to the packaging metadata so the distribution can be "
            "checked against the release.",
            str(repo),
            sources=("semver2", "python-packaging-guide"),
        )
    if expected and any(item["version"] != expected for item in versions):
        _add(
            findings,
            "version:requested-mismatch",
            "error",
            f"packaging metadata does not agree with requested version {expected}",
            "Update the packaging metadata or pass the version that is actually being released.",
            "packaging metadata",
            sources=("semver2",),
        )
    if not expected:
        _add(
            findings,
            "version:undetermined",
            "error",
            "no release version was supplied or found in known packaging metadata",
            "Pass --version or expose a direct version in packaging metadata; do not invent one.",
            str(repo),
            sources=("semver2", "python-packaging-guide"),
        )
        return
    if not SEMVER_RE.fullmatch(expected):
        _add(
            findings,
            "version:requested-invalid",
            "error",
            f"requested version {expected!r} is not SemVer 2.0.0",
            "Pass an unprefixed MAJOR.MINOR.PATCH value with an optional valid pre-release "
            "or build label.",
            "--version",
            sources=("semver2",),
        )
    tags = _git_tags(repo)
    if tags is None:
        _add(
            findings,
            "tag:unavailable",
            "error",
            "the repository has no readable Git tag list",
            "Run the check against a Git checkout containing the immutable release tag.",
            "git -C <repo> tag --list",
            sources=("semver2", "brack2022"),
        )
    elif expected in tags or f"v{expected}" in tags:
        matching = expected if expected in tags else f"v{expected}"
        head = _git_revision(repo, "HEAD")
        tagged = _git_revision(repo, matching)
        if head is not None and tagged is not None and head != tagged:
            _add(
                findings,
                "tag:target-mismatch",
                "error",
                f"release tag {matching!r} points to {tagged[:12]}, not inspected HEAD {head[:12]}",
                "Inspect the checkout at the immutable release tag before declaring it ready.",
                f"git -C <repo> rev-parse --verify {matching}^{{commit}}",
                evidence=f"tag={tagged}; HEAD={head}",
                sources=("semver2", "brack2022"),
            )
        else:
            passed.append(f"release tag present: {matching}")
    else:
        _add(
            findings,
            "tag:missing",
            "error",
            f"no Git tag named {expected!r} or {('v' + expected)!r} was found",
            "Create the reviewed immutable release tag after all release files pass.",
            "git -C <repo> tag --list",
            sources=("semver2", "brack2022"),
        )


def _check_changelog(
    repo: Path, expected: str | None, findings: list[dict[str, Any]], passed: list[str]
) -> None:
    path = _find_changelog(repo)
    if path is None:
        _add(
            findings,
            "changelog:missing",
            "error",
            "no supported changelog file is present",
            "Add CHANGELOG.md with an Unreleased section and dated release entries.",
            str(repo),
            sources=("keep-a-changelog",),
        )
        return
    text = _read_text(path) or ""
    if not re.search(r"^##\s+\[?Unreleased\]?\s*$", text, re.IGNORECASE | re.MULTILINE):
        _add(
            findings,
            "changelog:unreleased",
            "warning",
            "the changelog has no Unreleased section at the top",
            "Add an Unreleased section before the next release entry.",
            str(path),
            sources=("keep-a-changelog",),
        )
    if not expected:
        return
    heading = re.compile(
        rf"^##\s+\[?{re.escape(expected)}\]?\s+-\s+(\d{{4}}-\d{{2}}-\d{{2}})(?:\s+\[YANKED\])?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = heading.search(text)
    if not match:
        _add(
            findings,
            "changelog:version-missing",
            "error",
            f"the changelog has no dated Keep a Changelog entry for {expected}",
            f"Add '## [{expected}] - YYYY-MM-DD' with at least one standard change category.",
            str(path),
            sources=("keep-a-changelog",),
        )
        return
    next_heading = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    entry = (
        text[match.end() : match.end() + next_heading.start()]
        if next_heading
        else text[match.end() :]
    )
    categories = {
        item.group(1).strip().lower()
        for item in re.finditer(r"^###\s+(.+?)\s*$", entry, re.MULTILINE)
        if item.group(1).strip().lower() in CHANGE_TYPES
    }
    if not categories:
        _add(
            findings,
            "changelog:category-missing",
            "error",
            f"the {expected} changelog entry has no standard change category",
            "Group at least one notable change under Added, Changed, Deprecated, Removed, "
            "Fixed, or Security.",
            _location(path, text, f"[{expected}]"),
            sources=("keep-a-changelog",),
        )
    else:
        passed.append(f"Keep a Changelog entry present: {expected}")


def _validate_cff(
    repo: Path, expected: str | None, findings: list[dict[str, Any]], passed: list[str]
) -> dict[str, Any] | None:
    path = repo / "CITATION.cff"
    if not path.is_file():
        _add(
            findings,
            "cff:missing",
            "error",
            "CITATION.cff is missing from the repository root",
            "Generate a CFF from an explicit authors file, then review it before applying it.",
            str(path),
            sources=("citation-file-format", "smith2016-software-citation"),
        )
        return None
    text = _read_text(path) or ""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _add(
            findings,
            "cff:invalid-yaml",
            "error",
            f"CITATION.cff is not valid YAML: {exc}",
            "Repair the YAML or regenerate the file from an explicit authors file.",
            str(path),
            sources=("citation-file-format",),
        )
        return None
    if not isinstance(data, dict):
        _add(
            findings,
            "cff:root-type",
            "error",
            "CITATION.cff must contain a YAML mapping at its root",
            "Write CFF fields as a top-level YAML mapping.",
            str(path),
            sources=("citation-file-format",),
        )
        return None
    for key, expected_type in KNOWN_CFF_TYPES.items():
        if key in data and not isinstance(data[key], expected_type):
            _add(
                findings,
                f"cff:type:{key}",
                "error",
                f"CITATION.cff field {key!r} has the wrong type",
                f"Set {key} to a value with the CFF type supported by this checker.",
                _location(path, text, f"{key}:"),
                sources=("citation-file-format",),
            )
    required = ("cff-version", "message", "title", "authors", "version", "date-released")
    for key in required:
        if key not in data or data[key] in (None, "", []):
            _add(
                findings,
                f"cff:missing:{key}",
                "error",
                f"CITATION.cff is missing known required field {key!r}",
                f"Add a non-empty {key} field; supply release facts explicitly.",
                str(path),
                sources=("citation-file-format",),
            )
    cff_version = data.get("cff-version")
    if isinstance(cff_version, str) and not re.fullmatch(r"\d+\.\d+\.\d+", cff_version):
        _add(
            findings,
            "cff:version-invalid",
            "error",
            f"CITATION.cff has unsupported cff-version {cff_version!r}",
            "Use a dotted CFF specification version such as 1.2.0.",
            _location(path, text, "cff-version:"),
            sources=("citation-file-format",),
        )
    authors = data.get("authors")
    if isinstance(authors, list):
        for index, author in enumerate(authors):
            if not isinstance(author, dict):
                _add(
                    findings,
                    f"cff:author:{index}:type",
                    "error",
                    f"CITATION.cff author {index + 1} is not a mapping",
                    "Represent each author with family-names or name and optional given-names "
                    "or ORCID.",
                    str(path),
                    sources=("citation-file-format",),
                )
                continue
            if not _version(author.get("family-names")) and not _version(author.get("name")):
                _add(
                    findings,
                    f"cff:author:{index}:name",
                    "error",
                    f"CITATION.cff author {index + 1} has neither family-names nor name",
                    "Supply the author's family-names or literal name in the authors file.",
                    str(path),
                    sources=("citation-file-format",),
                )
            for key in ("given-names", "family-names", "name"):
                if key in author and not isinstance(author[key], str):
                    _add(
                        findings,
                        f"cff:author:{index}:{key}",
                        "error",
                        f"CITATION.cff author {index + 1} field {key!r} is not a string",
                        f"Set author {index + 1} field {key} to text in the authors file.",
                        str(path),
                        sources=("citation-file-format",),
                    )
            orcid = author.get("orcid")
            if orcid is not None and (
                not isinstance(orcid, str)
                or not re.fullmatch(r"https://orcid\.org/\d{4}-\d{4}-\d{4}-[\dX]{4}", orcid)
            ):
                _add(
                    findings,
                    f"cff:author:{index}:orcid",
                    "error",
                    f"CITATION.cff author {index + 1} has an invalid ORCID URL",
                    "Use the complete https://orcid.org/0000-0000-0000-0000 form or remove an "
                    "unverified ORCID.",
                    str(path),
                    sources=("citation-file-format",),
                )
    identifiers = data.get("identifiers", [])
    if isinstance(identifiers, list):
        for index, identifier in enumerate(identifiers):
            if (
                not isinstance(identifier, dict)
                or not _version(identifier.get("type"))
                or not _version(identifier.get("value"))
            ):
                _add(
                    findings,
                    f"cff:identifier:{index}",
                    "error",
                    f"CITATION.cff identifier {index + 1} lacks a type or value",
                    "Provide non-empty type and value fields for each identifier.",
                    str(path),
                    sources=("citation-file-format",),
                )
    date_value = data.get("date-released")
    if date_value is not None:
        date_text = date_value.isoformat() if isinstance(date_value, dt.date) else date_value
        if not isinstance(date_text, str) or not ISO_DATE_RE.fullmatch(date_text):
            _add(
                findings,
                "cff:date-invalid",
                "error",
                "CITATION.cff date-released is not an ISO date",
                "Use date-released: YYYY-MM-DD for the actual release date.",
                _location(path, text, "date-released:"),
                sources=("citation-file-format", "keep-a-changelog"),
            )
    cff_release = _version(data.get("version"))
    if expected and cff_release and cff_release != expected:
        _add(
            findings,
            "version:cff-mismatch",
            "error",
            f"CITATION.cff version {cff_release!r} does not match release {expected!r}",
            "Update CFF version to the exact release value and regenerate or review the file.",
            _location(path, text, "version:"),
            sources=("citation-file-format", "semver2"),
        )
    known_keys = set(KNOWN_CFF_TYPES) | {
        "type",
        "license-url",
        "contact",
        "commit",
        "doi",
        "repository-artifact",
    }
    for key in sorted(set(data) - known_keys):
        _add(
            findings,
            f"cff:unknown:{key}",
            "info",
            f"CITATION.cff contains field {key!r} outside this checker's known schema",
            "Validate this field with a current CFF schema tool during human review.",
            str(path),
            sources=("citation-file-format",),
        )
    if not any(f["id"].startswith("cff:") and f["severity"] == "error" for f in findings):
        passed.append("CITATION.cff parses and known fields validate")
    return data


def _check_doi_record(
    repo: Path,
    cff: dict[str, Any] | None,
    expected: str | None,
    findings: list[dict[str, Any]],
    passed: list[str],
) -> None:
    cff_doi: str | None = None
    if isinstance(cff, dict) and isinstance(cff.get("identifiers"), list):
        for identifier in cff["identifiers"]:
            if isinstance(identifier, dict) and str(identifier.get("type", "")).lower() == "doi":
                value = _version(identifier.get("value"))
                if value and DOI_RE.search(value):
                    cff_doi = value
                    break
    zenodo_files = [repo / name for name in (".zenodo.json", "zenodo.json", ".zenodo.yml")]
    for path in zenodo_files:
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None or not text.strip():
            continue
        try:
            data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            _add(
                findings,
                "doi:zenodo-invalid",
                "error",
                f"{path.name} cannot be parsed as metadata: {exc}",
                "Repair or remove the Zenodo metadata file before releasing.",
                str(path),
                sources=("citation-file-format", "smith2016-software-citation"),
            )
            continue
        if not isinstance(data, dict):
            _add(
                findings,
                "doi:zenodo-invalid",
                "error",
                f"{path.name} must contain a metadata mapping",
                "Write Zenodo metadata as a JSON or YAML mapping.",
                str(path),
                sources=("citation-file-format",),
            )
            continue
        doi = _version(data.get("doi")) or _version(data.get("conceptdoi"))
        version = _version(data.get("version"))
        valid = True
        if not doi or not DOI_RE.search(doi):
            valid = False
            _add(
                findings,
                "doi:zenodo-doi-missing",
                "error",
                f"{path.name} has no valid DOI",
                "Add the DOI assigned to the exact archived release.",
                str(path),
                sources=("citation-file-format", "smith2016-software-citation"),
            )
        if not version:
            valid = False
            _add(
                findings,
                "doi:zenodo-version-missing",
                "error",
                f"{path.name} has no release version",
                "Record the exact release version in the archive metadata.",
                str(path),
                sources=("citation-file-format", "semver2"),
            )
        elif expected and version != expected:
            valid = False
            _add(
                findings,
                "doi:zenodo-version-mismatch",
                "error",
                f"{path.name} records version {version!r}, not release {expected!r}",
                "Update the archive metadata to the exact release version.",
                str(path),
                sources=("citation-file-format", "semver2"),
            )
        if valid:
            passed.append(f"Zenodo metadata record present for {version}: {path.name}")
            return
    if cff_doi:
        passed.append(f"software DOI identifier present in CITATION.cff: {cff_doi}")
        return
    for path in sorted(repo.glob("README*")):
        text = _read_text(path) or ""
        if DOI_RE.search(text) and re.search(r"doi\.org|zenodo", text, re.IGNORECASE):
            passed.append(f"DOI or Zenodo record linked from {path.name}")
            return
    _add(
        findings,
        "doi:missing",
        "error",
        "no Zenodo metadata or software DOI record was found",
        "Archive the exact release in Zenodo or another DOI service and link its software "
        "record from the README or CFF.",
        "repository metadata",
        sources=("citation-file-format", "smith2016-software-citation", "fair4rs2022"),
    )


def _check_license(repo: Path, findings: list[dict[str, Any]], passed: list[str]) -> None:
    candidates = [repo / name for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING")]
    for path in candidates:
        text = _read_text(path)
        if text and text.strip():
            passed.append(f"license file present: {path.name}")
            return
    _add(
        findings,
        "license:missing",
        "error",
        "no non-empty root LICENSE or COPYING file is present",
        "Add the full text of the intended license in LICENSE or COPYING.",
        str(repo),
        sources=("joss-review-criteria", "joss-review-checklist", "brack2022"),
    )


def _check_dependencies(
    metadata: dict[str, Any], findings: list[dict[str, Any]], passed: list[str]
) -> None:
    dependencies = metadata["dependencies"]
    if not dependencies:
        passed.append("no third-party dependency declarations found")
        return
    unbounded = [item for item in dependencies if not _bounded(item["spec"])]
    for index, item in enumerate(unbounded):
        _add(
            findings,
            f"dependency:unbounded:{index}",
            "error",
            f"dependency declaration {item['spec']!r} is not pinned or bounded",
            "Add an exact pin, a compatible constraint, or a range with an upper bound.",
            item["location"],
            sources=("brack2022", "python-packaging-guide", "fair4rs2022"),
        )
    if not unbounded:
        passed.append(f"all {len(dependencies)} dependency declarations are pinned or bounded")


def _check_tests_ci(repo: Path, findings: list[dict[str, Any]], passed: list[str]) -> None:
    ignored = {".git", ".venv", "venv", "node_modules", "dist", "build"}
    test_files: list[Path] = []
    for path in repo.rglob("*"):
        if not path.is_file() or ignored.intersection(path.parts):
            continue
        if "tests" in path.parts or "test" in path.parts or "spec" in path.parts:
            if path.name.startswith("test_") or re.search(
                r"_test\.|\.test\.|\.spec\.", path.name
            ):
                test_files.append(path)
    if test_files:
        passed.append(f"test files present: {len(test_files)}")
    else:
        _add(
            findings,
            "tests:missing",
            "error",
            "no recognizable automated test file is present in a test directory",
            "Add tests for core behavior and keep their inputs and expected outputs with the "
            "source.",
            str(repo),
            sources=("brack2022", "joss-review-criteria", "joss-review-checklist"),
        )
    ci_files: list[Path] = []
    for relative in CI_PATHS:
        path = repo / relative
        if path.is_file():
            ci_files.append(path)
        elif path.is_dir():
            ci_files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
    if ci_files:
        passed.append(
            f"CI configuration present: {', '.join(str(p.relative_to(repo)) for p in ci_files)}"
        )
    else:
        _add(
            findings,
            "ci:missing",
            "error",
            "no supported continuous integration configuration is present",
            "Add CI that installs the project and runs the automated test suite on changes.",
            str(repo),
            sources=("brack2022", "joss-review-criteria", "joss-review-checklist"),
        )


def _paper_path(repo: Path) -> Path | None:
    for path in (repo / "paper.md", repo / "paper" / "paper.md"):
        if path.is_file():
            return path
    return None


def _check_joss(repo: Path, findings: list[dict[str, Any]], passed: list[str]) -> None:
    paper = _paper_path(repo)
    if paper is None:
        _add(
            findings,
            "joss:paper-missing",
            "error",
            "JOSS mode was requested but no paper.md or paper/paper.md exists",
            "Add the JOSS paper skeleton and fill it with evidence before submission.",
            str(repo),
            sources=("joss-review-criteria", "joss-docs"),
        )
        return
    text = _read_text(paper) or ""
    heading_matches = list(re.finditer(r"^#+\s+(.+?)\s*$", text, re.MULTILINE))
    headings = {
        re.sub(r"[^a-z0-9 ]+", "", match.group(1).lower()).strip()
        for match in heading_matches
    }
    section_bodies: dict[str, str] = {}
    for index, match in enumerate(heading_matches):
        next_match = heading_matches[index + 1] if index + 1 < len(heading_matches) else None
        section_name = re.sub(r"[^a-z0-9 ]+", "", match.group(1).lower()).strip()
        section_bodies[section_name] = text[
            match.end() : next_match.start() if next_match else None
        ].strip()
    required = {
        "summary": "Summary",
        "statement of need": "Statement of need",
        "state of the field": "State of the field",
        "software design": "Software design",
        "research impact statement": "Research impact statement",
        "ai usage disclosure": "AI usage disclosure",
    }
    missing = [label for key, label in required.items() if key not in headings]
    for label in missing:
        _add(
            findings,
            f"joss:section:{label.lower().replace(' ', '-')}",
            "error",
            f"JOSS paper is missing required section {label!r}",
            f"Add a substantive '{label}' section with repository-grounded evidence.",
            str(paper),
            sources=("joss-review-criteria", "joss-review-checklist"),
        )
    for key, label in required.items():
        if key in headings and not section_bodies.get(key):
            _add(
                findings,
                f"joss:section-empty:{key.replace(' ', '-')}",
                "error",
                f"JOSS paper section {label!r} has no content",
                f"Add substantive, repository-grounded content to the '{label}' section.",
                str(paper),
                sources=("joss-review-criteria", "joss-review-checklist"),
            )
    if not missing and not any(
        item["id"].startswith("joss:section-empty:") for item in findings
    ):
        passed.append("JOSS paper has all required section headings")
    paper_dir = paper.parent
    if not list(paper_dir.glob("*.bib")) and "references" not in headings:
        _add(
            findings,
            "joss:bibliography",
            "warning",
            "JOSS paper has no nearby bibliography file or References heading",
            "Add complete references for the software archive, compared tools, data, and methods.",
            str(paper),
            sources=("joss-review-criteria", "joss-review-checklist"),
        )
    if not (repo / "CONTRIBUTING.md").is_file() and not re.search(
        r"^#+\s+(contribut|support|community)",
        _read_text(repo / "README.md") or "",
        re.IGNORECASE | re.MULTILINE,
    ):
        _add(
            findings,
            "joss:community-guidance",
            "warning",
            "no CONTRIBUTING.md or recognizable README community guidance was found",
            "Document how to contribute, report problems, seek support, and make decisions.",
            str(repo),
            sources=("joss-review-criteria", "joss-review-checklist"),
        )
    dates = _git_log_dates(repo)
    if dates and (max(dates) - min(dates)).days < 180:
        _add(
            findings,
            "joss:development-span",
            "warning",
            "Git history spans less than six months",
            "Document sustained public development and community use before seeking JOSS review.",
            "git -C <repo> log --format=%aI",
            sources=("joss-review-criteria", "joss-review-checklist"),
        )
    elif dates:
        passed.append("Git history spans at least six months")
    else:
        _add(
            findings,
            "joss:development-history",
            "warning",
            "Git history could not be inspected for JOSS development-span evidence",
            "Run the check on a Git checkout and review public development history manually.",
            "git -C <repo> log --format=%aI",
            sources=("joss-review-criteria",),
        )


def check_repository(
    repo: Path | str, expected_version: str | None = None, joss: bool = False
) -> dict[str, Any]:
    """Return release findings for ``repo`` without changing it."""
    target = Path(repo).expanduser()
    findings: list[dict[str, Any]] = []
    passed: list[str] = []
    if not target.is_dir():
        _add(
            findings,
            "repository:missing",
            "error",
            f"repository path does not exist or is not a directory: {target}",
            "Pass an existing repository checkout.",
            str(target),
        )
        return {
            "repository": str(target),
            "version": expected_version,
            "findings": findings,
            "passed": passed,
        }
    metadata = _metadata(target, findings)
    versions = metadata["versions"]
    expected = _version(expected_version)
    if expected is None and len({item["version"] for item in versions}) == 1:
        expected = versions[0]["version"]
    _check_version_and_tag(target, expected, metadata, findings, passed)
    _check_changelog(target, expected, findings, passed)
    cff = _validate_cff(target, expected, findings, passed)
    _check_doi_record(target, cff, expected, findings, passed)
    _check_license(target, findings, passed)
    _check_dependencies(metadata, findings, passed)
    _check_tests_ci(target, findings, passed)
    if joss:
        _check_joss(target, findings, passed)
    errors = sum(f["severity"] == "error" for f in findings)
    warnings = sum(f["severity"] == "warning" for f in findings)
    info = sum(f["severity"] == "info" for f in findings)
    return {
        "repository": str(target),
        "version": expected,
        "joss": joss,
        "findings": findings,
        "passed": passed,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "passed": len(passed),
        },
    }


inspect_repository = check_repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."), help="repository to inspect")
    parser.add_argument(
        "--version",
        "--new-version",
        dest="version",
        help="expected release version; otherwise infer one direct packaging version",
    )
    parser.add_argument(
        "--joss", "--joss-ready", dest="joss", action="store_true", help="run the JOSS paper checks"
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser


def _render(result: dict[str, Any]) -> str:
    lines = [
        f"software release check: {result['repository']}",
        f"version: {result.get('version') or 'undetermined'}",
    ]
    for item in result["findings"]:
        lines.append(f"{item['severity'].upper()} {item['id']} [{item['location']}]")
        lines.append(f"  {item['message']}")
        lines.append(f"  fix: {item['fix']}")
    summary = result.get("summary", {})
    lines.append(
        "summary: "
        f"{summary.get('errors', 0)} error(s), {summary.get('warnings', 0)} warning(s), "
        f"{summary.get('info', 0)} info, {summary.get('passed', 0)} passed"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = check_repository(args.repo, args.version, args.joss)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_render(result))
    return 1 if result.get("summary", {}).get("errors", 1) else 0


if __name__ == "__main__":
    sys.exit(main())
