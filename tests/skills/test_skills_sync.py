from __future__ import annotations

import skills_sync
from skills_sync import main, set_grounding
from skillslib import grounding_ids, parse_frontmatter


def args_for(repo, *extra: str) -> list[str]:
    return ["--skills-dir", str(repo.skills), "--distilled", str(repo.distilled), *extra]


def test_check_clean_when_in_sync(skill_repo) -> None:
    assert main(args_for(skill_repo, "--check")) == 0


def test_check_fails_on_drift_and_sync_repairs(skill_repo, capsys) -> None:
    src = skill_repo.distilled / "doctoral-process.md"
    src.write_text(
        src.read_text(encoding="utf-8") + "\n- New claim [lovitts2001].\n", encoding="utf-8"
    )
    src.write_text(
        src.read_text(encoding="utf-8").replace(
            "- gu2007 (CC-BY-4.0)\n", "- gu2007 (CC-BY-4.0)\n- lovitts2001 (book)\n"
        ),
        encoding="utf-8",
    )
    assert main(args_for(skill_repo, "--check")) == 1
    out = capsys.readouterr().out
    assert "copy" in out and "grounding" in out
    assert main(args_for(skill_repo, "--dry-run")) == 0
    assert (
        skill_repo.skill / "references" / "doctoral-process.md"
    ).read_bytes() != src.read_bytes()
    assert main(args_for(skill_repo)) == 0
    assert (
        skill_repo.skill / "references" / "doctoral-process.md"
    ).read_bytes() == src.read_bytes()
    fm = parse_frontmatter(skill_repo.skill_md())
    assert grounding_ids(fm.data["metadata"]) == [
        "gu2007",
        "lovitts2001",
        "marino2014",
        "turing-way",
    ]
    assert "# keep this comment" in skill_repo.skill_md()
    assert main(args_for(skill_repo, "--check")) == 0


def test_missing_distilled_is_error(skill_repo, capsys) -> None:
    (skill_repo.skill / "references" / "manifest.txt").write_text("ghost-topic\n", encoding="utf-8")
    assert main(args_for(skill_repo)) == 1
    assert "does not exist" in capsys.readouterr().out


def test_unknown_skill_filter(skill_repo) -> None:
    assert main(args_for(skill_repo, "--skill", "nope")) == 1
    assert main(args_for(skill_repo, "--skill", "demo-skill", "--check")) == 0


def test_set_grounding_variants() -> None:
    inline = "---\nname: a\nmetadata:\n  borg-role: infra\n  grounding: x\n  hermes:\n    category: infra\n---\nbody\n"  # noqa: E501
    out = set_grounding(inline, ["a", "b"])
    assert "  grounding: a, b\n" in out and "hermes:" in out and out.endswith("body\n")
    block = "---\nname: a\nmetadata:\n  grounding:\n    - x\n    - y\n  hermes:\n    category: infra\n---\n"  # noqa: E501
    out = set_grounding(block, ["a"])
    assert "  grounding: a\n" in out and "- x" not in out and "hermes:" in out
    no_grounding = "---\nname: a\nmetadata:\n  borg-role: infra\n---\n"
    assert "  grounding: a\n" in set_grounding(no_grounding, ["a"])
    no_metadata = "---\nname: a\n---\n"
    out = set_grounding(no_metadata, ["a"])
    assert parse_frontmatter(out).data["metadata"]["grounding"] == "a"


def test_union_reference_ids(skill_repo) -> None:
    assert skills_sync.union_reference_ids(skill_repo.skill) == [
        "gu2007",
        "marino2014",
        "turing-way",
    ]
