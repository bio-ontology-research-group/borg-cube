"""The cockpit calls `cube brief` and `cube beads show`; both must exist on the host."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cube.cli import main


def _json(capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    out = capsys.readouterr().out
    return json.loads(out)  # type: ignore[no-any-return]


def test_brief_returns_markdown_without_writing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(repo), "brief", "--json", "--today", "2026-09-03"]) == 0
    data = _json(capsys)
    assert data["date"] == "2026-09-03"
    assert data["markdown"].startswith("# Digest 2026-09-03")
    assert "## Attention" in data["markdown"]
    assert not (repo / "briefings").exists()


def test_beads_show_alias_matches_bead_show(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cube.commands.show.bead_show", lambda *_a, **_k: None)
    code_alias = main(["--root", str(repo), "beads", "show", "cube-none", "--json"])
    alias = _json(capsys)
    code_direct = main(["--root", str(repo), "bead-show", "cube-none", "--json"])
    direct = _json(capsys)
    assert code_alias == code_direct == 3
    assert alias == direct == {"error": "bead not found", "id": "cube-none"}
