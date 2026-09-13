import re
from pathlib import Path

import pytest

from cube.config import deep_merge, load_settings


def test_deep_merge_merges_mappings_and_replaces_scalars_and_lists() -> None:
    base = {"a": 1, "m": {"x": 1, "y": {"z": 1}}, "l": [1, 2]}
    overlay = {"a": 2, "m": {"y": {"w": 3}}, "l": [9]}
    merged = deep_merge(base, overlay)
    assert merged == {"a": 2, "m": {"x": 1, "y": {"z": 1, "w": 3}}, "l": [9]}
    assert base["m"]["y"] == {"z": 1}, "deep_merge must not mutate its input"


def test_local_overlay_merges_over_cube_yaml(tmp_path: Path) -> None:
    (tmp_path / "cube.yaml").write_text(
        "host: ws\nslots: {plan: 2, implement: 1}\nmattermost: {team: example}\n"
        "hosts:\n  ws: {role: orchestration, ssh: ws}\n",
        encoding="utf-8",
    )
    (tmp_path / "cube.local.yaml").write_text(
        "slots: {plan: 6}\nmattermost: {infra_alerts_channel: chan123}\n"
        "hosts:\n  laptop: {role: personal, hostname: my-laptop}\n"
        "projects:\n  demo: {path: ~/src/demo, runner: codex}\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path)
    assert s.slots == {"plan": 6, "implement": 1}
    assert s.mattermost.team == "example"
    assert s.mattermost.infra_alerts_channel == "chan123"
    assert set(s.hosts) == {"ws", "laptop"}
    assert s.hosts["laptop"].hostname == "my-laptop"
    assert s.projects["demo"].runner == "codex"


def test_local_overlay_must_be_a_mapping(tmp_path: Path) -> None:
    (tmp_path / "cube.yaml").write_text("host: ws\n", encoding="utf-8")
    (tmp_path / "cube.local.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a mapping"):
        load_settings(tmp_path)


def test_repo_cube_yaml_has_no_site_specific_values() -> None:
    """The committed cube.yaml is shareable; site data lives in cube.local.yaml."""
    text = (Path(__file__).resolve().parents[1] / "cube.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        if not code.strip():
            continue
        for needle in ("/home/", "kaust.edu.sa", "infra_alerts_channel:", "home_channel:"):
            if needle in code:
                value = code.split(needle, 1)[1].split(",", 1)[0].strip().rstrip("}").strip()
                assert needle.endswith(":") and value in ("null", "~", ""), code.strip()
        ip = re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", code)
        assert ip is None, f"IP address in cube.yaml: {code.strip()}"
