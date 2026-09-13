from pathlib import Path

import pytest

from tools.fleet_reset import archive, digest


def test_reset_preserves_sources_and_verifies_runtime(tmp_path: Path) -> None:
    root = tmp_path / "cube"
    root.mkdir()
    (root / "cube").mkdir()
    (root / "cube.yaml").write_text("host: ws")
    (root / ".env").write_text("do not touch")
    (root / "state").mkdir()
    (root / "state" / "goals.json").write_text("old goals")
    before = digest(root / "state")
    dest = tmp_path / "archive"
    assert archive(root, dest, None, apply=False)["targets"] == [str(root / "state")]
    assert not dest.exists()
    result = archive(root, dest, None, apply=True)
    assert result["verified_targets"] == 1
    assert digest(dest / "000-state") == before
    assert list((root / "state").iterdir()) == []
    assert (root / ".env").read_text() == "do not touch"
    with pytest.raises(ValueError, match="already exists"):
        archive(root, dest, None, apply=True)
    with pytest.raises(ValueError, match="outside"):
        archive(root, root / "backup", None, apply=True)
