from pathlib import Path

from cube.config import Settings, load_settings, parse_env_file


def test_load_settings_reads_yaml_and_env(repo: Path) -> None:
    (repo / ".env").write_text("MATTERMOST_TOKEN=abc # comment\nEMPTY=\n# c\n", encoding="utf-8")
    s = load_settings(repo)
    assert s.host == "testhost"
    assert s.dirs["pa"] == repo / "pa"
    assert s.env["MATTERMOST_TOKEN"] == "abc"
    assert s.env["EMPTY"] == ""


def test_defaults_when_no_yaml(tmp_path: Path) -> None:
    s = load_settings(tmp_path)
    assert isinstance(s, Settings)
    assert s.slots["plan"] == 1
    assert s.dirs["state"] == tmp_path / "state"
    assert s.software_dirs() == [Path("~/Public/software").expanduser()]
    assert s.pipeline.max_iterations == 3


def test_parse_env_missing(tmp_path: Path) -> None:
    assert parse_env_file(tmp_path / "nope") == {}


def test_coordination_defaults_and_repo_values(tmp_path: Path) -> None:
    from cube.config import load_settings

    defaults = load_settings(tmp_path)
    assert defaults.coordination.review_every_hours == 4
    assert defaults.coordination.stale_hours == 24
    assert defaults.coordination.project_gap_days == 14
    repo = load_settings(Path(__file__).resolve().parents[1])
    assert repo.slots["plan"] >= 6
    assert repo.pipeline.autonomy.recruit == "coordinator"
    assert repo.coordination.review_every_hours == 4
