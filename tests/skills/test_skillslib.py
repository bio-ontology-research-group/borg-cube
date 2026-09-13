from __future__ import annotations

from pathlib import Path

import pytest
import skillslib
from skillslib import (
    ToolError,
    grounding_ids,
    load_manifest,
    parse_frontmatter,
    parse_sources_block,
    sources_block_is_first,
    update_manifest_fields,
    validate_manifest,
)


def test_parse_frontmatter_and_body() -> None:
    fm = parse_frontmatter("---\nname: x\nmetadata:\n  grounding: a, b\n---\n\n# Title\n")
    assert fm.data["name"] == "x"
    assert fm.end_line == 4
    assert fm.body.strip() == "# Title"
    assert grounding_ids(fm.data["metadata"]) == ["a", "b"]


def test_parse_frontmatter_absent() -> None:
    fm = parse_frontmatter("# no frontmatter\n")
    assert fm.data == {} and fm.end_line == -1


def test_parse_frontmatter_unclosed() -> None:
    with pytest.raises(ToolError):
        parse_frontmatter("---\nname: x\n")


def test_grounding_list_form() -> None:
    assert grounding_ids({"grounding": ["a", "b"]}) == ["a", "b"]
    with pytest.raises(ToolError):
        grounding_ids({"grounding": 3})


@pytest.mark.parametrize(
    "body",
    [
        "# T\n\nSources\n- alpha (CC-BY)\n- beta.2 (x)\n\n## Next\n",
        "## Sources\n- [alpha] licence\n* beta.2: note\n",
        "Sources:\n- alpha\n- beta.2\n",
    ],
)
def test_parse_sources_block(body: str) -> None:
    ids, idx = parse_sources_block(body)
    assert ids == ["alpha", "beta.2"]
    assert idx is not None
    assert sources_block_is_first(body)


def test_sources_block_not_first() -> None:
    body = "# T\n\nSome prose first.\n\nSources\n- alpha\n"
    assert not sources_block_is_first(body)
    assert not sources_block_is_first("# T\n\nno block\n")


def test_load_and_validate_manifest(skill_repo) -> None:
    sources = load_manifest(skill_repo.manifest)
    assert [s.id for s in sources][:2] == ["marino2014", "gu2007"]
    assert validate_manifest(sources) == []


def test_validate_manifest_reports_problems(tmp_path: Path) -> None:
    bad = tmp_path / "m.yaml"
    bad.write_text(
        "sources:\n- id: Bad_ID\n  type: zine\n  citation: c\n  license: l\n  oa: maybe\n"
        "  excerpt_ok: sure\n  topics: []\n  verified_by: guess\n  doi: 11.1/x\n",
        encoding="utf-8",
    )
    problems = validate_manifest(load_manifest(bad))
    joined = "\n".join(problems)
    for needle in (
        "id must match",
        "type",
        "verified_by",
        "excerpt_ok",
        "oa must",
        "topics",
        "doi",
    ):
        assert needle in joined


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    entry = "- id: a\n  type: web\n  citation: c\n  license: l\n  oa: web\n  excerpt_ok: true\n  topics: [t]\n"  # noqa: E501
    p.write_text("sources:\n" + entry + entry, encoding="utf-8")
    with pytest.raises(ToolError, match="duplicate"):
        load_manifest(p)


def test_update_manifest_fields_preserves_comments(skill_repo) -> None:
    update_manifest_fields(
        skill_repo.manifest, "gu2007", {"sha256": "abc", "fetched": "2026-09-02"}
    )
    text = skill_repo.manifest.read_text(encoding="utf-8")
    assert text.startswith("# test manifest")
    entry = [s for s in load_manifest(skill_repo.manifest) if s.id == "gu2007"][0]
    assert entry.sha256 == "abc" and entry.fetched == "2026-09-02"
    other = [s for s in load_manifest(skill_repo.manifest) if s.id == "marino2014"][0]
    assert other.sha256 is None


def test_update_manifest_fields_errors(skill_repo) -> None:
    with pytest.raises(ToolError, match="not found"):
        update_manifest_fields(skill_repo.manifest, "nope", {"sha256": "x"})
    with pytest.raises(ToolError, match="not present"):
        update_manifest_fields(skill_repo.manifest, "gu2007", {"bogus": "x"})


def test_discover_skills(skill_repo) -> None:
    assert [p.name for p in skillslib.discover_skills(skill_repo.skills)] == ["demo-skill"]
    assert skillslib.read_sync_manifest(skill_repo.skill) == ["doctoral-process"]
