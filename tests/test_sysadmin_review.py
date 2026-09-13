"""The sysadmin's daily review feeds hermes-ws's morning report (ADR-0020)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cube.config import Settings
from tests.helpers_engine import fixtures

globals().update(fixtures())


def test_infra_briefing_is_written_for_hermes_ws(engine_settings: Settings, tmp_path: Path) -> None:
    from types import SimpleNamespace

    from cube.agents.sysadmin import infra_briefing_path, night_scan, write_infra_briefing

    engine_settings.paths.hermes_home = tmp_path / "hermes"
    scan = engine_settings.paths.hermes_home / "state" / "infra" / "nightly_scan.txt"
    scan.parent.mkdir(parents=True)
    scan.write_text("\n".join(f"line {i}" for i in range(130)), encoding="utf-8")
    text = night_scan(engine_settings)
    assert text.startswith("line 0") and "10 more line(s)" in text
    now = datetime(2026, 9, 7, 5, 0, tzinfo=UTC)
    report = SimpleNamespace(
        run_id="r-1",
        message=None,
        result={
            "summary": "ws disk 92%, node005 idle; nothing new since yesterday",
            "next_actions": ["reclaim runs/ older than 30 days (approval bead cube-1)"],
            "escalations": [{"kind": "decision", "condition": "unimatrix01 root at 93%"}],
            "artifacts": [{"path": "runs/r-1/review.md"}],
        },
    )
    path = write_infra_briefing(engine_settings, report, now=now)
    assert path == infra_briefing_path(engine_settings, now.date())
    body = path.read_text(encoding="utf-8")
    assert body.startswith("# Server review 2026-09-07 (sysadmin, run r-1)")
    assert "ws disk 92%" in body and "reclaim runs/" in body and "unimatrix01 root" in body
