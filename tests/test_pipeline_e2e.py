from __future__ import annotations

from pathlib import Path

from cube.pipeline_rehearsal import run_rehearsal
from tests.helpers_engine import REPO_ROOT


def test_full_pipeline_rehearsal_runs_mail_workers_review_and_gate_loop(tmp_path: Path) -> None:
    result = run_rehearsal(REPO_ROOT, tmp_path / "rehearsal")

    assert result["status"]["status"] == "done"
    assert result["status"]["gate"]["n"] == 2
    assert result["status"]["gate"]["verdict"] == "approve"
    assert result["exit_code"] == 0
    assert [row["stage"] for row in result["dispatches"]] == [
        "collect",
        "team",
        "draft",
        "critique",
        "critique",
        "final",
        "survey",
        "draft",
        "recruit",
        "critique",
        "critique",
        "critique",
        "final",
        "experiments",
        "review",
        "experiments",
        "review",
        "gate",
        "experiments",
        "experiments",
        "review",
        "review",
        "gate",
    ]
    assert result["dispatches"][0]["command"][:4] == [
        "cube",
        "agent",
        "workday",
        "liaison",
    ]
    assert all(row["via"] == "marshal.tick" for row in result["dispatches"])
    assert {"programmer", "senior", "group-leader"} <= {row["role"] for row in result["dispatches"]}
    assert result["liaison_answer"]["links"]
    assert {repo["name"] for repo in result["liaison_answer"]["local_repos"]} == {
        "PhysioMap",
        "mOWL",
    }
    assert result["gate_verdicts"] == ["revise", "approve"]
    assert result["follow_ups"]
    assert result["ready_trace"][0]["ready_stages"] == ["collect"]
    assert result["ready_trace"][1]["ready_stages"] == ["team"]
    assert result["recruit_request"]
    recruited = next(
        row for row in result["status"]["team"] if row["member"] == "agent:protein-function"
    )
    assert recruited["role"] == "senior"
    round_two = result["status"]["discussion"][1]
    protein = next(
        row for row in round_two["critiques"] if row["member"] == "agent:protein-function"
    )
    assert protein["status"] == "closed"
    people = [
        row
        for discussion in result["status"]["discussion"]
        for row in discussion["critiques"]
        if row["member"].startswith("person:")  # the rehearsal's placeholder student
    ]
    assert len(people) == 2 and all(row["status"] == "open" for row in people)
    pipeline_dir = tmp_path / "rehearsal" / "runs" / "pipelines" / result["epic"]
    for round_number in (1, 2):
        discussion = pipeline_dir / "discussion" / f"plan-v{round_number}"
        assert (pipeline_dir / f"plan-v{round_number}-draft.yaml").is_file()
        assert (pipeline_dir / f"plan-v{round_number}.yaml").is_file()
        assert (discussion / "ontology.md").is_file()
        assert (discussion / "programmer.md").is_file()
        assert (discussion / "decisions.md").is_file()
    assert (pipeline_dir / "discussion" / "plan-v2" / "protein-function.md").is_file()
    assert any("requested recruitment of protein-function" in row for row in result["transitions"])
    assert result["transitions"][-1].startswith("gate -> done")
