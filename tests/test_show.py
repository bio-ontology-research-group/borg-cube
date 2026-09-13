import json
from pathlib import Path

from cube.cli import _rewrite_show, main


def test_rewrite_show_aliases() -> None:
    assert _rewrite_show(["runs", "show", "r1", "--json"]) == ["run-show", "r1", "--json"]
    assert _rewrite_show(["--root", "/x", "approvals", "show", "a1"]) == [
        "--root",
        "/x",
        "approval-show",
        "a1",
    ]
    assert _rewrite_show(["runs", "--json"]) == ["runs", "--json"]


def test_run_show_reads_meta_and_notes(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    d = repo / "runs" / "2026-09-02" / "r-1"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"run_id": "r-1", "role": "advisor", "state": "finished"})
    )
    (d / "notes.md").write_text("# notes\n")
    (d / "stdout.jsonl").write_text('{"a":1}\n{"b":2}\n')
    assert main(["--root", str(repo), "runs", "show", "r-1", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["notes"] == "# notes\n" and out["log_tail"] == ['{"a":1}', '{"b":2}']
    assert out["log"].endswith("stdout.jsonl")
    assert main(["--root", str(repo), "run-show", "nope", "--json"]) == 3


def test_approval_show_missing(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--root", str(repo), "approvals", "show", "apr-none", "--json"]) == 3
