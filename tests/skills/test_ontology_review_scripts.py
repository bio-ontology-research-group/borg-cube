"""Tests for the ontology-review offline OBO and RDF/XML checks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "ontology-review"
SCRIPTS = SKILL / "scripts"
OBO_CHECK_FILE = SCRIPTS / "obo_check.py"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"ontology_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


obo_check = load("obo_check")


METADATA = """\
license: CC-BY-4.0
version_iri: 2026-09-02
identifier_pattern: '^TEST:\\d{4}$'
imports: []
scope: README.md#scope
users: docs/users.md
collaboration: CONTRIBUTING.md
authority: docs/governance.md#contact
naming_conventions: docs/naming.md
maintenance: docs/release-policy.md
"""


VALID_OBO = """\
format-version: 1.4
ontology: test
data-version: 2026-09-02

[Term]
id: TEST:0001
name: test entity
def: "An entity used for a deterministic checker test." []

[Term]
id: TEST:0002
name: retired test entity
def: "A retired checker-test entity." []
is_obsolete: true
replaced_by: TEST:0001
"""


def metadata(tmp_path: Path) -> Path:
    path = tmp_path / "ontology-metadata.yaml"
    path.write_text(METADATA, encoding="utf-8")
    return path


def test_obo_check_accepts_complete_obo_and_reports_robot_status(tmp_path: Path, capsys) -> None:
    assert OBO_CHECK_FILE.is_file()
    ontology = tmp_path / "test.obo"
    ontology.write_text(VALID_OBO, encoding="utf-8")
    assert (
        obo_check.main(
            ["--ontology", str(ontology), "--metadata", str(metadata(tmp_path)), "--json"]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "OBO"
    assert result["summary"]["errors"] == 0
    assert any(item["id"].startswith("robot:") for item in result["findings"])


def test_obo_check_reports_term_level_errors(tmp_path: Path) -> None:
    ontology = tmp_path / "bad.obo"
    ontology.write_text(
        VALID_OBO.replace(
            "name: retired test entity\n"
            'def: "A retired checker-test entity." []\n'
            "is_obsolete: true\nreplaced_by: TEST:0001",
            "name: test entity\nis_obsolete: true",
        ),
        encoding="utf-8",
    )
    parsed = obo_check.parse_ontology(ontology)
    result = obo_check.check_ontology(parsed, obo_check.load_metadata(metadata(tmp_path)), ontology)
    ids = {item["id"] for item in result["findings"]}
    assert "label:test entity" in ids
    assert "term:TEST:0002:obsolete" in ids


def test_obo_check_parses_rdfxml_owl(tmp_path: Path, capsys) -> None:
    ontology = tmp_path / "test.owl"
    ontology.write_text(
        (
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            'xmlns:owl="http://www.w3.org/2002/07/owl#" '
            'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
            'xmlns:obo="http://purl.obolibrary.org/obo/">\n'
            '<owl:Ontology rdf:about="https://example.org/test.owl">'
            '<owl:versionIRI rdf:resource="2026-09-02"/></owl:Ontology>\n'
            '<owl:Class rdf:about="TEST:0001"><rdfs:label>test entity</rdfs:label>'
            "<obo:IAO_0000115>A test definition.</obo:IAO_0000115></owl:Class>\n"
            "</rdf:RDF>\n"
        ),
        encoding="utf-8",
    )
    assert (
        obo_check.main(
            ["--ontology", str(ontology), "--metadata", str(metadata(tmp_path)), "--json"]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "RDF/XML OWL" and result["summary"]["errors"] == 0
