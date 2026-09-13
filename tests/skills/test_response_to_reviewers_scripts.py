# ruff: noqa: E501
"""Tests for the response-to-reviewers scripts (split_reviews.py, response_check.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "response-to-reviewers"
SCRIPTS = SKILL / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"rtr_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


split_reviews = load("split_reviews")
response_check = load("response_check")

LETTER = """\
Dear Dr Hoehndorf,

Your manuscript BIOINF-2026-0142 has been reviewed. We invite a major revision.

Reviewer #1 (Remarks to the Author):

The manuscript presents an ontology-based method for phenotype prediction.
The idea is interesting but the evaluation is not convincing.

Major comments

1. The baseline comparison is missing. Please run the experiment against the
   published DL2Vec baseline on the same split.
2. It is unclear how the negative samples were drawn. Please explain.

Minor comments

3. Figure 3 has an unlabelled axis.
4. The authors should cite the related work of Smith et al. on axiom
   embeddings.

Reviewer 2

(1) The abstract overstates the result: the improvement is within noise.
(2) Typo on page 4, line 12.

Editor:

Please shorten the introduction.
"""

RESPONSE = """\
# Response to reviewers

## Reviewer 1

### R1.1

> The manuscript presents an ontology-based method for phenotype prediction. The idea is interesting but the evaluation is not convincing.

Thank you. We added the baseline comparison and a significance test in Section 4.2 (CL-1).

### R1.2

> The baseline comparison is missing. Please run the experiment against the published DL2Vec baseline on the same split.

Yes. We ran DL2Vec on the same split and added the result to Table 2 (CL-1), lines 210 to 224 of the revised manuscript.

### R1.3

> It is unclear how the negative samples were drawn. Please explain.

We clarified the sampling in the Methods (CL-2).

### R1.4

> Figure 3 has an unlabelled axis.

We corrected the axis label in Figure 3 (CL-3).

### R1.5

> The authors should cite the related work of Smith et al. on axiom embeddings.

We added the citation in the related work (CL-4).

## Reviewer 2

### R2.1

> The abstract overstates the result: the improvement is within noise.

No. We disagree, because the improvement is significant at p < 0.01 over ten seeds, as shown in Table 2. We revised the abstract to state the effect size (CL-5).

### R2.2

> Typo on page 4, line 12.

We corrected the typo in Section 2 (CL-6).

## Editor

### ED.1

> Please shorten the introduction.

We shortened the Introduction by one paragraph (CL-7).

## Change log

| id | what changed | where | prompted by |
| --- | --- | --- | --- |
| CL-1 | added the DL2Vec baseline | Section 4.2, Table 2 | R1.1, R1.2 |
| CL-2 | described negative sampling | Methods | R1.3 |
| CL-3 | labelled the y axis | Figure 3 | R1.4 |
| CL-4 | added Smith et al. | Related work | R1.5 |
| CL-5 | stated the effect size | Abstract | R2.1 |
| CL-6 | fixed the typo | Section 2 | R2.2 |
| CL-7 | shortened the introduction | Introduction | ED.1 |
"""


@pytest.fixture
def split() -> dict:
    return split_reviews.split_letter(LETTER, "decision.txt")


@pytest.fixture
def comments(split) -> dict:
    return response_check.comments_index(split)


# --------------------------------------------------------------------------- split_reviews


def test_reviewers_and_editor_are_found(split):
    assert [r["id"] for r in split["reviewers"]] == ["R1", "R2", "ED"]
    assert split["comments_total"] == 8
    assert split["preamble"].startswith("Dear Dr Hoehndorf")


def test_ids_are_sequential_per_reviewer(split):
    ids = [c["id"] for r in split["reviewers"] for c in r["comments"]]
    assert ids == ["R1.1", "R1.2", "R1.3", "R1.4", "R1.5", "R2.1", "R2.2", "ED.1"]


def test_text_is_verbatim(split):
    r1 = split["reviewers"][0]["comments"]
    assert r1[2]["text"] == "It is unclear how the negative samples were drawn. Please explain."
    assert "published DL2Vec baseline on the same split." in r1[1]["text"]


def test_kinds_are_detected(split):
    kinds = {c["id"]: c["kind"] for r in split["reviewers"] for c in r["comments"]}
    assert kinds["R1.2"] == "experiment request"
    assert kinds["R1.3"] == "clarification"
    assert kinds["R1.4"] == "minor"
    assert kinds["R1.5"] == "reference request"
    assert kinds["R2.1"] == "major"
    assert kinds["R2.2"] == "minor"


def test_section_headings_set_the_kind(split):
    sections = {c["id"]: c["section"] for r in split["reviewers"] for c in r["comments"]}
    assert sections["R1.2"] == "major"
    assert sections["R1.4"] == "minor"


def test_numbering_styles(split):
    styles = {c["id"]: c["style"] for r in split["reviewers"] for c in r["comments"]}
    assert styles["R1.2"] == "number"
    assert styles["R2.1"] == "paren-number"


def test_unnumbered_text_is_flagged_not_guessed(split):
    low = [f for f in split["flags"] if f["level"] == "low-confidence"]
    assert {f["reviewer"] for f in low} == {"R1", "ED"}
    ed = split["reviewers"][2]["comments"][0]
    assert ed["confidence"] == "low"
    assert ed["style"] == "paragraph"


def test_letter_without_headings_is_unattributed():
    data = split_reviews.split_letter("1. The method is unclear.\n2. Please cite Smith.\n")
    assert data["reviewers"] == []
    assert data["comments_total"] == 0
    assert [f["level"] for f in data["flags"]] == ["unattributed", "unattributed"]


def test_heading_without_comments_is_flagged():
    data = split_reviews.split_letter("Reviewer 1\n\n\nReviewer 2\n\n1. Fine work.\n")
    flags = [f for f in data["flags"] if f["level"] == "unattributed"]
    assert [f["reviewer"] for f in flags] == ["R1"]


def test_unrecognised_reviewer_heading_is_not_attributed_to_previous_reviewer():
    data = split_reviews.split_letter(
        "Reviewer 1\n\n1. First comment.\n\nReviewer two\n\n2. Unattributed comment.\n"
    )
    assert [comment["id"] for comment in data["reviewers"][0]["comments"]] == ["R1.1"]
    assert any(
        flag["level"] == "unattributed" and flag["lines"] == [5, 7] for flag in data["flags"]
    )


def test_roman_and_letter_reviewers():
    data = split_reviews.split_letter("Referee II\n\n1. A point.\n\nReviewer B\n\n1. Another.\n")
    assert [r["id"] for r in data["reviewers"]] == ["R2", "RB"]


def test_bullets_and_comment_labels():
    data = split_reviews.split_letter(
        "Reviewer 1\n\n- The evaluation is flawed.\n- Please define the metric.\n\n"
        "Reviewer 2\n\nComment 1: Typo in Table 1.\n"
    )
    r1 = data["reviewers"][0]["comments"]
    assert [c["style"] for c in r1] == ["bullet", "bullet"]
    assert data["reviewers"][1]["comments"][0]["style"] == "comment-label"


def test_cli_writes_yaml_and_strict_exit(tmp_path: Path):
    letter = tmp_path / "decision.txt"
    letter.write_text(LETTER, encoding="utf-8")
    out = tmp_path / "comments.yaml"
    assert split_reviews.main(["--letter", str(letter), "--out", str(out)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["comments_total"] == 8
    assert split_reviews.main(["--letter", str(letter), "--out", str(out), "--strict"]) == 1


def test_cli_json(tmp_path: Path, capsys):
    letter = tmp_path / "decision.md"
    letter.write_text("Reviewer 1\n\n1. Please clarify the metric.\n", encoding="utf-8")
    assert split_reviews.main(["--letter", str(letter), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["reviewers"][0]["comments"][0]["kind"] == "clarification"


def test_split_reviews_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "split_reviews.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "decision letter" in proc.stdout


# --------------------------------------------------------------------------- response_check


def checks(comments, response: str, log: str = "") -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for finding in response_check.check_response(comments, response, log or response):
        out.setdefault(finding.check, []).append(finding.comment_id or "")
    return out


def test_complete_response_has_no_findings(comments):
    assert response_check.check_response(comments, RESPONSE, RESPONSE) == []


def test_missing_response_is_an_error(comments):
    trimmed = RESPONSE.split("### R2.2")[0] + RESPONSE.split("## Change log")[1]
    found = checks(comments, trimmed, RESPONSE)
    assert set(found["missing-response"]) == {"R2.2", "ED.1"}


def test_quote_must_be_verbatim(comments):
    altered = RESPONSE.replace("Figure 3 has an unlabelled axis.", "Figure 3 is bad.")
    found = checks(comments, altered, RESPONSE)
    assert found["quote-mismatch"] == ["R1.4"]


def test_quote_capitalization_must_be_verbatim(comments):
    altered = RESPONSE.replace(
        "The abstract overstates the result: the improvement is within noise.",
        "the abstract overstates the result: the improvement is within noise.",
    )
    found = checks(comments, altered, RESPONSE)
    assert found["quote-mismatch"] == ["R2.1"]


def test_reflowed_quote_is_accepted(comments):
    reflowed = RESPONSE.replace(
        "> The authors should cite the related work of Smith et al. on axiom embeddings.",
        "> The authors should cite the related work of Smith et al.\n> on axiom embeddings.",
    )
    assert "quote-mismatch" not in checks(comments, reflowed, RESPONSE)


def test_elided_quote_is_accepted(comments):
    elided = RESPONSE.replace(
        "> The baseline comparison is missing. Please run the experiment against the published DL2Vec baseline on the same split.",
        "> The baseline comparison is missing. [...] the same split.",
    )
    assert "quote-mismatch" not in checks(comments, elided, RESPONSE)


def test_addressed_in_the_manuscript_is_rejected(comments):
    weak = RESPONSE.replace(
        "We clarified the sampling in the Methods (CL-2).",
        "This point is addressed in the manuscript.",
    )
    found = checks(comments, weak, RESPONSE)
    assert found["no-change-statement"] == ["R1.3"]


def test_change_without_location_is_rejected(comments):
    vague = RESPONSE.replace(
        "We corrected the axis label in Figure 3 (CL-3).",
        "We corrected the axis label (CL-3).",
    )
    found = checks(comments, vague, RESPONSE)
    assert found["no-location"] == ["R1.4"]


def test_line_numbers_need_a_version(comments):
    bare = RESPONSE.replace("lines 210 to 224 of the revised manuscript", "lines 210 to 224")
    found = checks(comments, bare, RESPONSE)
    assert found["line-basis"] == ["R1.2"]


def test_promise_without_a_change_log_entry(comments):
    unlogged = RESPONSE.replace(
        "We added the citation in the related work (CL-4).",
        "We added the citation in the related work.",
    )
    found = checks(comments, unlogged, RESPONSE)
    assert found["promise-not-logged"] == ["R1.5"]


def test_unknown_change_id(comments):
    wrong = RESPONSE.replace("(CL-2)", "(CL-99)")
    found = checks(comments, wrong, RESPONSE)
    assert found["unknown-change-id"] == ["R1.3"]


def test_log_entry_with_unknown_comment_id(comments):
    log = RESPONSE.replace("| R2.1 |", "| R9.9 |")
    found = checks(comments, RESPONSE, log)
    assert found["log-unknown-comment"] == ["R9.9"]


def test_unreferenced_log_entry_is_a_warning(comments):
    log = RESPONSE + "\n| CL-8 | reformatted the tables | all tables | |\n"
    findings = response_check.check_response(comments, RESPONSE, log)
    assert [(f.level, f.check) for f in findings] == [("warning", "log-unreferenced")]


def test_dismissive_tone_is_an_error(comments):
    rude = RESPONSE.replace(
        "We clarified the sampling in the Methods (CL-2).",
        "The reviewer clearly misunderstands the method. We clarified the sampling in the Methods (CL-2).",
    )
    found = checks(comments, rude, RESPONSE)
    assert found["dismissive-tone"] == ["R1.3"]


def test_disagreement_needs_evidence(comments):
    bare = RESPONSE.replace(
        "No. We disagree, because the improvement is significant at p < 0.01 over ten seeds, as shown in Table 2. We revised the abstract to state the effect size (CL-5).",
        "We disagree. We revised the abstract to state the effect size (CL-5).",
    )
    found = checks(comments, bare, RESPONSE)
    assert found["no-reason"] == ["R2.1"]


def test_disagreement_with_evidence_passes(comments):
    assert "no-reason" not in checks(comments, RESPONSE, RESPONSE)


def test_block_for_an_unknown_id(comments):
    extra = RESPONSE.replace(
        "## Change log",
        "### R7.1\n\n> Something.\n\nWe added a table in Section 5 (CL-1).\n\n## Change log",
    )
    found = checks(comments, extra, RESPONSE)
    assert found["unknown-block"] == ["R7.1"]


def test_yaml_change_log_is_parsed(comments):
    log = yaml.safe_dump(
        {
            "changes": [
                {"id": f"CL-{n}", "what": "x", "where": "Section 1", "prompted_by": []}
                for n in range(1, 8)
            ]
        }
    )
    assert response_check.check_response(comments, RESPONSE, log) == []


def test_list_change_log_is_parsed(comments):
    log = "\n".join(f"- CL-{n}: changed something in Section 1" for n in range(1, 8))
    assert response_check.check_response(comments, RESPONSE, log) == []


def test_cli_exit_codes_and_json(tmp_path: Path, capsys, split):
    comments_file = tmp_path / "comments.yaml"
    comments_file.write_text(yaml.safe_dump(split, sort_keys=False), encoding="utf-8")
    good = tmp_path / "response.md"
    good.write_text(RESPONSE, encoding="utf-8")
    argv = ["--comments", str(comments_file), "--response", str(good)]
    assert response_check.main(argv) == 0
    assert "does not submit anything" in capsys.readouterr().out

    assert response_check.main([*argv, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["comments"] == 8

    bad = tmp_path / "bad.md"
    bad.write_text(RESPONSE.replace("### R2.2", "### R2.9"), encoding="utf-8")
    assert response_check.main(["--comments", str(comments_file), "--response", str(bad)]) == 1
    capsys.readouterr()


def test_cli_strict_turns_warnings_into_errors(tmp_path: Path, capsys, split):
    comments_file = tmp_path / "comments.json"
    comments_file.write_text(json.dumps(split), encoding="utf-8")
    response = tmp_path / "response.md"
    response.write_text(RESPONSE, encoding="utf-8")
    log = tmp_path / "log.md"
    log.write_text(
        RESPONSE.split("## Change log")[1] + "\n| CL-8 | reformatted the tables | all tables | |\n",
        encoding="utf-8",
    )
    argv = ["--comments", str(comments_file), "--response", str(response), "--change-log", str(log)]
    assert response_check.main(argv) == 0
    capsys.readouterr()
    assert response_check.main([*argv, "--strict"]) == 1
    capsys.readouterr()


def test_missing_arguments_exit_two(capsys):
    assert response_check.main([]) == 2
    assert split_reviews.main([]) == 2
    capsys.readouterr()


def test_bad_comments_file_exits_two(tmp_path: Path, capsys):
    bad = tmp_path / "c.yaml"
    bad.write_text("hello: world\n", encoding="utf-8")
    response = tmp_path / "r.md"
    response.write_text(RESPONSE, encoding="utf-8")
    assert response_check.main(["--comments", str(bad), "--response", str(response)]) == 2
    capsys.readouterr()


def test_response_check_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "response_check.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "change log" in proc.stdout
