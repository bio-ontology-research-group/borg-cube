# ruff: noqa: E501
"""Tests for the experiment-tracking skill scripts (runs_manifest.py, figure_provenance.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "experiment-tracking"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"et_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runs_manifest = load("runs_manifest")
figure_provenance = load("figure_provenance")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x",
    "GIT_AUTHOR_DATE": "2026-01-15T10:00:00",
    "GIT_COMMITTER_DATE": "2026-01-15T10:00:00",
    "PATH": "/usr/bin:/bin",
}


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**GIT_ENV, "HOME": str(repo)},
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def severities(findings: list[dict]) -> set[str]:
    return {f["check"] for f in findings}


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    r = tmp_path / "project"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r / "train.py", "print('hi')\n")
    write(r / "requirements.txt", "numpy==1.26.4\nscikit-learn==1.5.0\nunpinned\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def tree(tmp_path: Path, repo: Path) -> Path:
    """A runs tree: one complete run, one run with no seed and a dirty tree, one bare directory."""
    runs = tmp_path / "runs"
    data = tmp_path / "data"
    write(data / "train-v3.csv", "a,b\n1,2\n")

    good = runs / "2026-09-02-baseline-01"
    write(good / "config.yaml", "lr: 0.01\n")
    write(good / "metrics.json", '{"f1": 0.81}\n')
    write(good / "figures" / "roc.png", "PNGDATA-roc\n")
    write(
        good / "run.yaml",
        yaml.safe_dump(
            {
                "run_id": "2026-09-02-baseline-01",
                "command": "python train.py --config config.yaml",
                "repo": str(repo),
                "dirty": False,
                "seeds": {"global": 20260902, "data_split": 7},
                "config": "config.yaml",
                "inputs": [{"path": str(data / "train-v3.csv"), "version": "v3"}],
                "environment": {"python": "3.12.4", "lock": str(repo / "requirements.txt")},
                "started": "2026-09-02T09:14:03",
                "ended": "2026-09-02T11:47:55",
                "exit_status": 0,
                "outputs": ["metrics.json", "figures/roc.png"],
            }
        ),
    )

    bad = runs / "2026-09-03-ablation-04"
    write(bad / "figures" / "ablation.pdf", "PDFDATA-ablation\n")
    write(
        bad / "run.yaml",
        yaml.safe_dump(
            {
                "run_id": "2026-09-03-ablation-04",
                "command": "python train.py --ablate graph",
                "commit": "0" * 40,
                "dirty": True,
                "outputs": ["figures/ablation.pdf"],
                "exit_status": 0,
            }
        ),
    )

    bare = runs / "2026-09-04-scratch"
    write(bare / "notes.txt", "nothing\n")
    return runs


def manifest_of(tree: Path, repo: Path, **kw) -> dict:
    args = runs_manifest.build_parser().parse_args(
        ["--runs", str(tree), "--repo", str(repo), *[str(a) for a in kw.get("extra", [])]]
    )
    return runs_manifest.build(args)


# --------------------------------------------------------------------------- runs_manifest


def test_help_exits_zero():
    for script in ("runs_manifest.py", "figure_provenance.py"):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--help"], capture_output=True, text=True
        )
        assert proc.returncode == 0, proc.stderr


def test_example_descriptor_is_valid_yaml():
    for script, key in (("runs_manifest.py", "run_id"), ("figure_provenance.py", "figures")):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--example"], capture_output=True, text=True
        )
        assert proc.returncode == 0
        assert key in yaml.safe_load(proc.stdout)


def test_shipped_examples_parse():
    assert "run_id" in yaml.safe_load((ASSETS / "run.yaml.example").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((ASSETS / "figure-map.yaml.example").read_text(encoding="utf-8"))
    assert [e["figure"] for e in mapping["figures"]]


def test_complete_run_is_reproducible(tree: Path, repo: Path):
    manifest = manifest_of(tree, repo)
    run = next(r for r in manifest["runs"] if r["run_id"] == "2026-09-02-baseline-01")
    assert run["reproducible"] is True
    assert run["command"].startswith("python train.py")
    assert run["git"]["commit"] and run["git"]["dirty"] is False
    assert run["seeds"] == {"global": 20260902, "data_split": 7}
    assert run["config_hash"]
    assert run["inputs"][0]["sha256"] and run["inputs"][0]["version"] == "v3"
    assert run["environment"]["packages"]["numpy"] == "1.26.4"
    assert run["started"] and run["ended"] and run["exit_status"] == 0
    assert {o["path"] for o in run["outputs"]} == {"metrics.json", "figures/roc.png"}
    assert all(o["sha256"] for o in run["outputs"])


def test_missing_seed_and_dirty_tree_are_high_findings(tree: Path, repo: Path):
    manifest = manifest_of(tree, repo)
    run = next(r for r in manifest["runs"] if r["run_id"] == "2026-09-03-ablation-04")
    checks = severities(run["findings"])
    assert "seed.missing" in checks
    assert "commit.dirty" in checks
    assert "input.undeclared" in checks
    assert run["reproducible"] is False
    high = {f["check"] for f in run["findings"] if f["severity"] == "high"}
    assert {"seed.missing", "commit.dirty"} <= high


def test_reproducible_is_false_for_failed_or_incomplete_evidence(tmp_path: Path):
    runs = tmp_path / "runs"
    run = runs / "incomplete"
    write(run / "large.dat", "0123456789\n")
    write(
        run / "run.yaml",
        yaml.safe_dump(
            {
                "command": "python train.py",
                "commit": "0" * 40,
                "seeds": {"global": 1},
                "inputs": [
                    {"path": "missing.csv", "version": "v1"},
                    {"path": "large.dat", "version": "v1"},
                ],
                "outputs": ["missing.out"],
                "exit_status": 1,
            }
        ),
    )
    args = runs_manifest.build_parser().parse_args(["--runs", str(runs), "--max-hash-bytes", "1"])
    result = runs_manifest.build(args)["runs"][0]
    checks = severities(result["findings"])
    assert {
        "status.failed",
        "input.missing",
        "input.unhashed",
        "output.missing",
        "commit.dirty-unknown",
    } <= checks
    assert result["reproducible"] is False


def test_run_without_descriptor_is_reported_not_skipped(tree: Path, repo: Path):
    args = runs_manifest.build_parser().parse_args(
        ["--runs", str(tree), "--repo", str(repo), "--infer"]
    )
    manifest = runs_manifest.build(args)
    ids = {r["run_id"] for r in manifest["runs"]}
    assert "2026-09-02-baseline-01" in ids
    assert "2026-09-03-ablation-04" in ids
    assert "2026-09-04-scratch" in ids
    run = next(r for r in manifest["runs"] if r["run_id"] == "2026-09-04-scratch")
    assert "descriptor.missing" in severities(run["findings"])
    assert run["reproducible"] is False


def test_unhashable_input_becomes_a_finding(tmp_path: Path, tree: Path, repo: Path):
    args = runs_manifest.build_parser().parse_args(
        ["--runs", str(tree), "--repo", str(repo), "--max-hash-bytes", "1"]
    )
    manifest = runs_manifest.build(args)
    run = next(r for r in manifest["runs"] if r["run_id"] == "2026-09-02-baseline-01")
    assert "input.unhashed" in severities(run["findings"])
    assert run["inputs"][0]["sha256"] is None
    assert "larger than" in run["inputs"][0]["hash_note"]


def test_missing_input_file_is_high(tmp_path: Path, repo: Path):
    runs = tmp_path / "r2"
    run_dir = runs / "run-x"
    write(run_dir / "run.yaml", yaml.safe_dump({"inputs": ["nowhere.csv"], "seeds": {"global": 1}}))
    args = runs_manifest.build_parser().parse_args(["--runs", str(runs)])
    manifest = runs_manifest.build(args)
    checks = severities(manifest["runs"][0]["findings"])
    assert "input.missing" in checks


def test_scan_limits_are_reported(tree: Path, repo: Path):
    args = runs_manifest.build_parser().parse_args(
        ["--runs", str(tree), "--repo", str(repo), "--max-runs", "1"]
    )
    manifest = runs_manifest.build(args)
    assert manifest["limits"]["runs_truncated"] is True
    assert manifest["limits"]["max_runs"] == 1
    assert len(manifest["runs"]) == 1


def test_manifest_carries_no_data_content(tree: Path, repo: Path):
    manifest = manifest_of(tree, repo)
    blob = json.dumps(manifest)
    assert "PNGDATA" not in blob
    assert '"f1"' not in blob
    assert "lr: 0.01" not in blob


def test_manifest_never_writes_into_the_runs_tree(tree: Path, repo: Path):
    before = sorted(p.relative_to(tree) for p in tree.rglob("*"))
    manifest_of(tree, repo)
    after = sorted(p.relative_to(tree) for p in tree.rglob("*"))
    assert before == after


def test_fail_on_high_exits_one(tree: Path, repo: Path, capsys):
    code = runs_manifest.main(["--runs", str(tree), "--repo", str(repo), "--fail-on", "high"])
    capsys.readouterr()
    assert code == 1


def test_output_outside_repository_requires_apply(tmp_path: Path, tree: Path, repo: Path):
    output = tmp_path / "export" / "manifest.json"
    arguments = ["--runs", str(tree), "--repo", str(repo), "--out", str(output)]
    assert runs_manifest.main(arguments) == 2
    assert not output.exists()
    assert runs_manifest.main([*arguments, "--apply"]) == 0
    assert output.is_file()


def test_render_is_plain_text(tree: Path, repo: Path):
    text = runs_manifest.render(manifest_of(tree, repo))
    assert "# Run manifest" in text
    assert "2026-09-02-baseline-01" in text
    assert "\u2014" not in text


# --------------------------------------------------------------------------- figure_provenance


@pytest.fixture
def paper(tmp_path: Path, tree: Path, repo: Path) -> tuple[Path, Path]:
    """A paper directory with figures copied from the runs, plus the manifest."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_of(tree, repo), indent=2), encoding="utf-8")
    paper_dir = tmp_path / "paper"
    write(paper_dir / "figures" / "fig2-roc.png", "PNGDATA-roc\n")
    write(paper_dir / "figures" / "fig3-ablation.pdf", "PDFDATA-ablation\n")
    write(paper_dir / "figures" / "fig9-orphan.png", "PNGDATA-orphan\n")
    write(
        paper_dir / "main.tex",
        "\\includegraphics[width=\\textwidth]{figures/fig2-roc.png}\n"
        "\\includegraphics{figures/fig3-ablation.pdf}\n"
        "\\includegraphics{figures/fig9-orphan.png}\n",
    )
    write(
        paper_dir / "figures.yaml",
        yaml.safe_dump(
            {
                "figures": [
                    {
                        "figure": "figures/fig2-roc.png",
                        "run": "2026-09-02-baseline-01",
                        "output": "figures/roc.png",
                    },
                    {
                        "figure": "figures/fig3-ablation.pdf",
                        "run": "2026-09-03-ablation-04",
                        "output": "figures/ablation.pdf",
                    },
                ]
            }
        ),
    )
    return manifest_path, paper_dir


def report_of(manifest_path: Path, paper_dir: Path, *extra: str) -> dict:
    args = figure_provenance.build_parser().parse_args(
        [
            "--manifest",
            str(manifest_path),
            "--map",
            str(paper_dir / "figures.yaml"),
            "--manuscript",
            str(paper_dir / "main.tex"),
            *extra,
        ]
    )
    return figure_provenance.build(args)


def test_traceable_figure_carries_run_commit_and_seeds(paper):
    report = report_of(*paper)
    fig = next(f for f in report["figures"] if f["figure"] == "figures/fig2-roc.png")
    assert fig["traceable"] is True
    assert fig["run_id"] == "2026-09-02-baseline-01"
    assert fig["seeds"]["global"] == 20260902
    assert fig["commit"]
    assert fig["matches_run_output"] is True
    assert fig["findings"] == []


def test_untraceable_figure_is_high(paper):
    report = report_of(*paper)
    fig = next(f for f in report["figures"] if f["figure"] == "figures/fig9-orphan.png")
    assert fig["traceable"] is False
    assert "figure.untraceable" in severities(fig["findings"])
    assert report["summary"]["untraceable"] == 1


def test_figure_inherits_unreproducible_run(paper):
    report = report_of(*paper)
    fig = next(f for f in report["figures"] if f["figure"] == "figures/fig3-ablation.pdf")
    assert "figure.unreproducible-run" in severities(fig["findings"])


def test_edited_figure_is_detected(paper):
    manifest_path, paper_dir = paper
    (paper_dir / "figures" / "fig2-roc.png").write_text("PNGDATA-roc-EDITED\n", encoding="utf-8")
    report = report_of(manifest_path, paper_dir)
    fig = next(f for f in report["figures"] if f["figure"] == "figures/fig2-roc.png")
    assert fig["matches_run_output"] is False
    assert "figure.edited" in severities(fig["findings"])


def test_unknown_run_in_mapping_is_high(paper):
    manifest_path, paper_dir = paper
    mapping = yaml.safe_load((paper_dir / "figures.yaml").read_text(encoding="utf-8"))
    mapping["figures"][0]["run"] = "no-such-run"
    (paper_dir / "figures.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")
    report = report_of(manifest_path, paper_dir)
    fig = next(f for f in report["figures"] if f["figure"] == "figures/fig2-roc.png")
    assert "figure.unknown-run" in severities(fig["findings"])
    assert fig["traceable"] is False


def test_output_not_in_run_is_high(paper):
    manifest_path, paper_dir = paper
    mapping = yaml.safe_load((paper_dir / "figures.yaml").read_text(encoding="utf-8"))
    mapping["figures"][0]["output"] = "figures/does-not-exist.png"
    (paper_dir / "figures.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")
    report = report_of(manifest_path, paper_dir)
    fig = next(f for f in report["figures"] if f["figure"] == "figures/fig2-roc.png")
    assert "figure.output-not-in-run" in severities(fig["findings"])


def test_unused_run_outputs_are_reported(paper):
    manifest_path, paper_dir = paper
    mapping = {"figures": [yaml.safe_load((paper_dir / "figures.yaml").read_text())["figures"][0]]}
    (paper_dir / "figures.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")
    report = report_of(manifest_path, paper_dir)
    unused = {u["run_id"] for u in report["unused_runs"] if not u.get("partial")}
    assert "2026-09-03-ablation-04" in unused
    assert "run.unused" in {f["check"] for f in report["findings"]}


def test_missing_mapping_file_reports_rather_than_crashes(paper):
    manifest_path, _paper_dir = paper
    args = figure_provenance.build_parser().parse_args(["--manifest", str(manifest_path)])
    report = figure_provenance.build(args)
    assert "map.missing" in {f["check"] for f in report["findings"]}
    assert report["summary"]["figures"] == 0


def test_report_carries_no_data_content(paper):
    report = report_of(*paper)
    assert "PNGDATA" not in json.dumps(report)


def test_provenance_writes_nothing_without_out(paper):
    manifest_path, paper_dir = paper
    before = sorted(p.relative_to(paper_dir) for p in paper_dir.rglob("*"))
    report_of(manifest_path, paper_dir)
    after = sorted(p.relative_to(paper_dir) for p in paper_dir.rglob("*"))
    assert before == after


def test_render_lists_every_figure(paper):
    text = figure_provenance.render(report_of(*paper))
    assert "# Figure provenance" in text
    for name in ("fig2-roc.png", "fig3-ablation.pdf", "fig9-orphan.png"):
        assert name in text
    assert "\u2014" not in text


def test_bad_manifest_exits_two(tmp_path: Path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert figure_provenance.main(["--manifest", str(bad)]) == 2
    capsys.readouterr()


def test_missing_runs_directory_exits_two(tmp_path: Path, capsys):
    assert runs_manifest.main(["--runs", str(tmp_path / "nope")]) == 2
    capsys.readouterr()


def test_templates_are_present_and_have_the_required_sections():
    card = (ASSETS / "model-card.md").read_text(encoding="utf-8")
    for section in (
        "## Model details",
        "## Intended use",
        "## Factors",
        "## Metrics",
        "## Evaluation data",
        "## Training data",
        "## Quantitative analyses",
        "## Ethical considerations",
        "## Caveats and recommendations",
    ):
        assert section in card
    sheet = (ASSETS / "datasheet.md").read_text(encoding="utf-8")
    for section in (
        "## Motivation",
        "## Composition",
        "## Collection process",
        "## Preprocessing, cleaning and labeling",
        "## Uses",
        "## Distribution",
        "## Maintenance",
    ):
        assert section in sheet
