#!/usr/bin/env python3
"""Render a CITATION.cff from repository metadata and an explicit authors file."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")


class CFFError(ValueError):
    """Raised when required release metadata is absent or ambiguous."""


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CFFError(f"cannot read {path}: {exc}") from exc


def _value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _project_metadata(repo: Path) -> dict[str, Any]:
    """Read direct metadata from common files without executing setup code."""
    result: dict[str, Any] = {
        "name": None,
        "description": None,
        "version": None,
        "urls": {},
        "license": None,
    }
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(_text(pyproject))
        except tomllib.TOMLDecodeError as exc:
            raise CFFError(f"pyproject.toml cannot be parsed: {exc}") from exc
        project = data.get("project") if isinstance(data, dict) else None
        if isinstance(project, dict):
            result["name"] = _value(project.get("name")) or result["name"]
            result["description"] = _value(project.get("description")) or result["description"]
            result["version"] = _value(project.get("version")) or result["version"]
            if isinstance(project.get("urls"), dict):
                result["urls"].update({str(k): str(v) for k, v in project["urls"].items()})
            license_data = project.get("license")
            if isinstance(license_data, dict):
                result["license"] = _value(license_data.get("text")) or _value(
                    license_data.get("file")
                )
            else:
                result["license"] = _value(license_data)
        poetry = data.get("tool", {}).get("poetry") if isinstance(data, dict) else None
        if isinstance(poetry, dict):
            result["name"] = _value(poetry.get("name")) or result["name"]
            result["description"] = _value(poetry.get("description")) or result["description"]
            result["version"] = _value(poetry.get("version")) or result["version"]
    setup_cfg = repo / "setup.cfg"
    if setup_cfg.exists():
        text = _text(setup_cfg)
        section = re.search(r"(?ms)^\[metadata\]\s*(.*?)(?=^\[|\Z)", text)
        if section:
            block = section.group(1)
            for key in ("name", "version", "description", "license"):
                match = re.search(rf"^{key}\s*=\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
                if match:
                    result[key] = _value(match.group(1)) or result[key]
    setup_py = repo / "setup.py"
    if setup_py.exists():
        text = _text(setup_py)
        for key in ("name", "version", "description"):
            match = re.search(rf"\b{key}\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                result[key] = result[key] or match.group(1)
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            package = json.loads(_text(package_json))
        except json.JSONDecodeError as exc:
            raise CFFError(f"package.json cannot be parsed: {exc}") from exc
        if isinstance(package, dict):
            result["name"] = result["name"] or _value(package.get("name"))
            result["description"] = result["description"] or _value(package.get("description"))
            result["version"] = result["version"] or _value(package.get("version"))
    existing = repo / "CITATION.cff"
    if existing.exists():
        try:
            current = yaml.safe_load(_text(existing))
        except yaml.YAMLError as exc:
            raise CFFError(f"existing CITATION.cff cannot be parsed: {exc}") from exc
        if isinstance(current, dict):
            result["name"] = result["name"] or _value(current.get("title"))
            result["version"] = result["version"] or _value(current.get("version"))
            result["description"] = result["description"] or _value(current.get("abstract"))
    missing = [key for key in ("name", "version") if not result[key]]
    if missing:
        raise CFFError(
            "repository metadata is missing "
            + " and ".join(missing)
            + "; pass explicit metadata or add it to the packaging manifest"
        )
    return result


def _authors(path: Path) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(_text(path))
    except yaml.YAMLError as exc:
        raise CFFError(f"authors file is not valid YAML: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("authors"), list):
        data = data["authors"]
    if not isinstance(data, list) or not data:
        raise CFFError("authors file must be a non-empty YAML list or an authors: list")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise CFFError(f"author {index} must be a YAML mapping")
        author = {str(key): value for key, value in item.items()}
        if not _value(author.get("family-names")) and not _value(author.get("name")):
            raise CFFError(f"author {index} needs family-names or name")
        for key in ("given-names", "family-names", "name", "orcid", "email", "affiliation"):
            if key in author and not isinstance(author[key], str):
                raise CFFError(f"author {index} field {key} must be a string")
        result.append(author)
    return result


def _existing_cff(repo: Path) -> dict[str, Any]:
    path = repo / "CITATION.cff"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(_text(path))
    except yaml.YAMLError as exc:
        raise CFFError(f"existing CITATION.cff cannot be parsed: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise CFFError("existing CITATION.cff root must be a YAML mapping")
    return data


def generate(
    repo: Path | str,
    authors_file: Path | str,
    version: str | None = None,
    doi: str | None = None,
    date_released: str | None = None,
    output: Path | str | None = None,
) -> tuple[Path, str]:
    """Return the destination path and rendered CFF without writing it."""
    target = Path(repo).expanduser()
    if not target.is_dir():
        raise CFFError(f"repository is not a directory: {target}")
    metadata = _project_metadata(target)
    authors = _authors(Path(authors_file).expanduser())
    current = _existing_cff(target)
    release = _value(version) or _value(metadata.get("version"))
    if not release:
        raise CFFError("release version is missing; pass --version")
    if not SEMVER_RE.fullmatch(release):
        raise CFFError(f"release version {release!r} is not SemVer 2.0.0")
    if version and metadata.get("version") and metadata["version"] != release:
        raise CFFError(
            f"--version {release!r} conflicts with packaging metadata {metadata['version']!r}"
        )
    output_data: dict[str, Any] = dict(current)
    output_data["cff-version"] = _value(current.get("cff-version")) or "1.2.0"
    output_data["message"] = _value(current.get("message")) or (
        "If you use this software, please cite it as below."
    )
    output_data["title"] = metadata["name"]
    output_data["version"] = release
    output_data["authors"] = authors
    if date_released:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_released):
            raise CFFError("--date-released must use YYYY-MM-DD")
        output_data["date-released"] = date_released
    elif "date-released" not in output_data:
        output_data.pop("date-released", None)
    if metadata.get("description"):
        output_data["abstract"] = metadata["description"]
    if metadata.get("license"):
        output_data["license"] = metadata["license"]
    if metadata.get("urls", {}).get("Repository"):
        output_data["repository-code"] = metadata["urls"]["Repository"]
    elif metadata.get("urls", {}).get("Source"):
        output_data["repository-code"] = metadata["urls"]["Source"]
    if doi:
        if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
            raise CFFError("--doi must be a DOI value such as 10.5281/zenodo.1234")
        identifiers = output_data.get("identifiers")
        if not isinstance(identifiers, list):
            identifiers = []
        identifiers = [
            item
            for item in identifiers
            if not (isinstance(item, dict) and item.get("type") == "doi")
        ]
        identifiers.append({"type": "doi", "value": doi})
        output_data["identifiers"] = identifiers
    rendered = yaml.safe_dump(
        output_data, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    destination = Path(output).expanduser() if output else target / "CITATION.cff"
    return destination, rendered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path("."), help="repository containing package metadata"
    )
    parser.add_argument("--authors", type=Path, required=True, help="YAML authors file")
    parser.add_argument("--version", help="release version, required when metadata is dynamic")
    parser.add_argument("--doi", help="version-specific software DOI to add")
    parser.add_argument("--date-released", help="release date in YYYY-MM-DD form")
    parser.add_argument(
        "--output",
        "--out",
        type=Path,
        help="CFF path; defaults to CITATION.cff in the repository",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the rendered CFF to the repository root"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        destination, rendered = generate(
            args.repo, args.authors, args.version, args.doi, args.date_released, args.output
        )
        if args.apply:
            repo = Path(args.repo).expanduser().resolve()
            output = destination.resolve()
            try:
                output.relative_to(repo)
            except ValueError as exc:
                raise CFFError("refusing to write a CFF outside the target repository") from exc
            output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (CFFError, OSError) as exc:
        print(f"cff-gen: {exc}", file=sys.stderr)
        return 1
    if args.apply:
        print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
