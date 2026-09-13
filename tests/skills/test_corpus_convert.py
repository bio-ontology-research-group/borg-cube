from __future__ import annotations

import subprocess
from pathlib import Path

import corpus_convert
from corpus_convert import command_for, main


def fake_runner(calls: list[list[str]]):
    def run(cmd):
        calls.append(list(cmd))
        Path(cmd[-1] if cmd[0] == "pdftotext" else cmd[cmd.index("-o") + 1]).write_text(
            "converted\n"
        )
        return subprocess.CompletedProcess(list(cmd), 0, "", "")

    return run


def test_command_for() -> None:
    assert command_for(Path("a.pdf"), Path("a.txt"))[:2] == ["pdftotext", "-layout"]
    assert command_for(Path("a.html"), Path("a.txt"))[0] == "pandoc"
    assert command_for(Path("a.md"), Path("a.txt")) is None


def test_convert_all_kinds(tmp_path: Path, monkeypatch, capsys) -> None:
    raw, text = tmp_path / "raw", tmp_path / "text"
    raw.mkdir()
    (raw / "one.pdf").write_bytes(b"%PDF")
    (raw / "two.html").write_text("<p>x</p>")
    (raw / "three.md").write_text("# md\n")
    (raw / "four.zip").write_bytes(b"PK")
    monkeypatch.setattr(corpus_convert.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []
    rc = main(["--raw-dir", str(raw), "--text-dir", str(text)], runner=fake_runner(calls))
    assert rc == 1  # four.zip has no converter
    out = capsys.readouterr().out
    assert "converted one" in out and "converted two" in out and "copied    three" in out
    assert "no converter" in out
    assert (text / "three.txt").read_text() == "# md\n"
    assert [c[0] for c in calls] == ["pdftotext", "pandoc"]
    # second run skips up-to-date outputs
    calls.clear()
    (raw / "four.zip").unlink()
    assert main(["--raw-dir", str(raw), "--text-dir", str(text)], runner=fake_runner(calls)) == 0
    assert calls == []
    assert (
        main(
            ["--raw-dir", str(raw), "--text-dir", str(text), "--force", "--id", "one"],
            runner=fake_runner(calls),
        )
        == 0
    )
    assert len(calls) == 1


def test_dry_run_and_missing_tool(tmp_path: Path, monkeypatch, capsys) -> None:
    raw, text = tmp_path / "raw", tmp_path / "text"
    raw.mkdir()
    (raw / "one.pdf").write_bytes(b"%PDF")
    assert main(["--raw-dir", str(raw), "--text-dir", str(text), "--dry-run"]) == 0
    assert "pdftotext -layout" in capsys.readouterr().out and not text.exists()
    monkeypatch.setattr(corpus_convert.shutil, "which", lambda name: None)
    assert main(["--raw-dir", str(raw), "--text-dir", str(text)]) == 1
    assert "not installed" in capsys.readouterr().out
    assert main(["--raw-dir", str(tmp_path / "nope"), "--text-dir", str(text)]) == 1
