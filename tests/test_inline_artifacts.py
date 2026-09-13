"""Plan-tier roles cannot write files; artifacts returned inline must still land on disk."""

from __future__ import annotations

from pathlib import Path

from cube.model import Artifact, RunResult
from cube.pipeline import materialise_inline_artifacts


def test_inline_content_is_written_under_the_run_dir_and_path_rewritten(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = RunResult(
        summary="team",
        artifacts=[
            Artifact(kind="team", path="team.yaml", content="team: []\nlead: agent:coordinator\n"),
            Artifact(kind="plan", path="../../escape.yaml", content="plan: x\n"),
            Artifact(kind="critique", path="/abs/existing.md"),
        ],
    )
    written = materialise_inline_artifacts(run_dir, result)
    assert written == [
        run_dir / "artifacts" / "team.yaml",
        (run_dir / "artifacts" / "escape.yaml").resolve(),
    ]
    assert (run_dir / "artifacts" / "team.yaml").read_text(encoding="utf-8").startswith("team:")
    # a path that only has a basename after sanitising still lands inside the run dir
    assert result.artifacts[1].path == str((run_dir / "artifacts" / "escape.yaml").resolve())
    assert (run_dir / "artifacts" / "escape.yaml").exists()
    # artifacts without content are left alone
    assert result.artifacts[2].path == "/abs/existing.md"
