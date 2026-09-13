from __future__ import annotations

from pathlib import Path

import pytest

from cube.config import Settings


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "cube.yaml").write_text(
        "host: testhost\npaths:\n  pa: pa\n  org: org\n", encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text(".env\nruns/\nstate/\n", encoding="utf-8")
    (tmp_path / "contacts.yaml").write_text("grants: {}\n", encoding="utf-8")
    for d in (
        "pa",
        "org",
        "state",
        "runs",
        "roles",
        "brain/facts",
        "systemd",
        "hermes/profiles/advisor",
    ):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def settings(repo: Path) -> Settings:
    from cube.config import load_settings

    return load_settings(repo)
