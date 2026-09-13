from __future__ import annotations

import json
from pathlib import Path

import skills_lint
from skills_lint import LintContext, heading_is_title_case, lint_skill, main


def ctx_for(repo, **kw) -> LintContext:
    return LintContext(
        manifest_path=repo.manifest, distilled_dir=repo.distilled, tests_dir=repo.tests, **kw
    )


def errors(repo, **kw) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in lint_skill(repo.skill, ctx_for(repo, **kw)):
        if f.level == "error":
            out.setdefault(f.check, []).append(f.message)
    return out


def test_fixture_skill_is_clean(skill_repo) -> None:
    assert errors(skill_repo) == {}


def test_cli_exit_codes_and_json(skill_repo, capsys) -> None:
    args = [
        str(skill_repo.skill),
        "--manifest",
        str(skill_repo.manifest),
        "--distilled",
        str(skill_repo.distilled),
        "--tests-dir",
        str(skill_repo.tests),
        "--json",
    ]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["skills"] == ["demo-skill"]
    skill_repo.write_skill_md(
        skill_repo.skill_md().replace("# Demo skill", "# Demo skill \u2014 yes")
    )
    assert main(args) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["errors"] == 1 and data["findings"][0]["check"] == "style.em-dash"
    assert main([*args, "--report"]) == 0


def test_name_mismatch_and_bad_name(skill_repo) -> None:
    skill_repo.write_skill_md(skill_repo.skill_md().replace("name: demo-skill", "name: Demo_Skill"))
    errs = errors(skill_repo)
    assert any("!= directory" in m for m in errs["spec.name"])
    assert any("lowercase" in m for m in errs["spec.name"])


def test_unknown_key_and_long_description(skill_repo) -> None:
    text = skill_repo.skill_md().replace("license: CC-BY-4.0", "license: CC-BY-4.0\nauthor: me")
    text = text.replace("Demonstrates the fixture skill.", "x" * 1100)
    skill_repo.write_skill_md(text)
    errs = errors(skill_repo)
    assert "spec.keys" in errs and "spec.description" in errs


def test_size_limits(skill_repo) -> None:
    skill_repo.write_skill_md(skill_repo.skill_md() + "\n" + "filler line\n" * 600)
    errs = errors(skill_repo)
    assert any("lines" in m for m in errs["spec.size"])
    skill_repo.write_skill_md(skill_repo.skill_md() + "\n" + ("word " * 40 + "\n") * 120)
    assert any("tokens" in m for m in errors(skill_repo)["spec.size"])


def test_banned_phrases_and_title_case(skill_repo) -> None:
    text = (
        skill_repo.skill_md()
        + "\n## Key Points To Remember\n\nNote that this is bad. Honest take.\n"
    )
    text += (
        "\nInline `Note that` in code is fine.\n\n```\nImportantly, code blocks are skipped\n```\n"
    )
    skill_repo.write_skill_md(text)
    errs = errors(skill_repo)
    banned = " ".join(errs["style.banned-phrase"])
    assert "Note that" in banned and "Honest" in banned and "Importantly" not in banned
    assert len(errs["style.title-case"]) == 1


def test_heading_heuristic() -> None:
    allow = set(skills_lint.TITLE_CASE_ALLOW)
    assert not heading_is_title_case("Rules we adopt", allow)
    assert not heading_is_title_case("Deploying to Hermes and Claude Code", allow)
    assert not heading_is_title_case("Using SKILL.md and the CLI", allow)
    assert not heading_is_title_case("Step 2: Run the tests", allow)
    assert heading_is_title_case("Rules We Adopt", allow)
    assert not heading_is_title_case("Sources", allow)


def test_grounding_count_unknown_uncited(skill_repo) -> None:
    text = skill_repo.skill_md().replace(
        "grounding: gu2007, marino2014, turing-way", "grounding: gu2007, nope"
    )
    skill_repo.write_skill_md(text)
    errs = errors(skill_repo)
    assert "grounding.count" in errs
    assert any("'nope' not in manifest" in m for m in errs["grounding.unknown"])
    assert any("'nope' not cited" in m for m in errs["grounding.uncited"])


def test_grounding_threshold_for_advisor(skill_repo) -> None:
    skill_repo.write_skill_md(
        skill_repo.skill_md().replace("borg-role: infra", "borg-role: advisor")
    )
    assert any(">= 5" in m for m in errors(skill_repo)["grounding.count"])


def test_hermes_category_and_role(skill_repo) -> None:
    text = (
        skill_repo.skill_md()
        .replace("category: infra", "category: misc")
        .replace("borg-role: infra", "borg-role: boss")
    )
    skill_repo.write_skill_md(text)
    errs = errors(skill_repo)
    assert "hermes.category" in errs and "hermes.borg-role" in errs
    skill_repo.write_skill_md(skill_repo.skill_md().replace("    category: misc\n", ""))
    assert any("missing" in m for m in errors(skill_repo)["hermes.category"])


def test_reference_without_sources_block(skill_repo) -> None:
    ref = skill_repo.skill / "references" / "reproducible.md"
    ref.write_text(
        "# Reproducible practice\n\nProse first.\n\nSources\n- turing-way\n", encoding="utf-8"
    )
    assert "references.sources-block" in errors(skill_repo)
    ref.write_text("# Reproducible practice\n\nSources\n- ghost-id\n", encoding="utf-8")
    errs = errors(skill_repo)
    assert "references.unknown-id" in errs and "grounding.uncited" in errs


def test_reference_unlisted_in_skill_md(skill_repo) -> None:
    (skill_repo.skill / "references" / "extra.md").write_text(
        "Sources\n- gu2007\n", encoding="utf-8"
    )
    assert any("extra.md" in m for m in errors(skill_repo)["references.unlisted"])


def test_drift_detected(skill_repo) -> None:
    ref = skill_repo.skill / "references" / "doctoral-process.md"
    ref.write_text(ref.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
    assert any("differs" in m for m in errors(skill_repo)["references.drift"])
    ref.unlink()
    assert any("not synced" in m for m in errors(skill_repo)["references.drift"])
    (skill_repo.distilled / "doctoral-process.md").unlink()
    assert any("missing" in m for m in errors(skill_repo)["references.drift"])


def test_unreviewed_distilled_is_warning(skill_repo) -> None:
    for path in (
        skill_repo.distilled / "doctoral-process.md",
        skill_repo.skill / "references" / "doctoral-process.md",
    ):
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "reviewed_by: Robert Hoehndorf", "reviewed_by: null"
            ),
            encoding="utf-8",
        )
    findings = lint_skill(skill_repo.skill, ctx_for(skill_repo))
    assert [f.check for f in findings if f.level == "warning"] == ["references.unreviewed"]
    assert not [f for f in findings if f.level == "error"]


def test_scripts_checks(skill_repo) -> None:
    script = skill_repo.skill / "scripts" / "hello.py"
    script.write_text(
        script.read_text(encoding="utf-8").replace("import sys\n", "import sys\nimport requests\n"),
        encoding="utf-8",
    )
    assert any("requests" in m for m in errors(skill_repo, run_scripts=False)["scripts.imports"])
    (skill_repo.tests / "test_hello.py").unlink()
    assert "scripts.untested" in errors(skill_repo, run_scripts=False)
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    assert any("exited 3" in m for m in errors(skill_repo)["scripts.help"])


def test_spec_only_skips_house_checks(skill_repo) -> None:
    text = skill_repo.skill_md().replace(
        "grounding: gu2007, marino2014, turing-way", "grounding: nope"
    )
    skill_repo.write_skill_md(text)
    assert errors(skill_repo, spec_only=True) == {}


def test_missing_skill_md(tmp_path: Path, skill_repo) -> None:
    empty = tmp_path / "skills" / "empty-skill"
    empty.mkdir()
    findings = lint_skill(empty, ctx_for(skill_repo))
    assert [f.check for f in findings] == ["spec.skill-md"]


def test_seeded_index_warning(skill_repo, capsys) -> None:
    seeded = skill_repo.skills / "seeded"
    seeded.mkdir()
    (seeded / "index.yaml").write_text(
        "skills:\n- name: gone\n  path: /nonexistent/skill\n", encoding="utf-8"
    )
    rc = main(
        [
            "--skills-dir",
            str(skill_repo.skills),
            "--manifest",
            str(skill_repo.manifest),
            "--distilled",
            str(skill_repo.distilled),
            "--tests-dir",
            str(skill_repo.tests),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "seeded.missing" in out
