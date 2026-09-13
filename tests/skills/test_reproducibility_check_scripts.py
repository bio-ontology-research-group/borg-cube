# ruff: noqa: E501
"""Tests for the reproducibility-check scripts (repro_env.sh, compare_results.py)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "reproducibility-check"
SCRIPTS = SKILL / "scripts"
REPRO_ENV = SCRIPTS / "repro_env.sh"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"rc_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


compare_results = load("compare_results")


# --------------------------------------------------------------- compare_results


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_compare(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "compare_results.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_compare_help_exits_zero():
    proc = run_compare("--help")
    assert proc.returncode == 0
    assert "tolerance" in proc.stdout


def test_identical_json(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.9, "loss": 0.1}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.9, "loss": 0.1}))
    proc = run_compare("--reference", str(ref), "--produced", str(got), "--json")
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["outcome"] == "identical"
    assert result["counts"] == {
        "total": 2,
        "exact": 2,
        "within": 0,
        "outside": 0,
        "missing": 0,
        "added": 0,
    }


def test_within_tolerance_json(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.900000}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.900001}))
    proc = run_compare(
        "--reference", str(ref), "--produced", str(got), "--tolerance", "1e-4", "--json"
    )
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["outcome"] == "within"
    assert result["items"][0]["status"] == "within"
    assert result["items"][0]["abs_diff"] == pytest.approx(1e-6, rel=1e-3)


def test_divergent_exits_one(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.90}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.72}))
    proc = run_compare(
        "--reference", str(ref), "--produced", str(got), "--tolerance", "1e-6", "--json"
    )
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["outcome"] == "divergent"
    assert result["items"][0]["status"] == "outside"
    assert result["items"][0]["rel_diff"] == pytest.approx(0.2, rel=1e-6)


def test_per_metric_tolerance_beats_default(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.90, "runtime": 100.0}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.90, "runtime": 140.0}))
    strict = run_compare(
        "--reference", str(ref), "--produced", str(got), "--tolerance", "1e-6", "--json"
    )
    assert strict.returncode == 1
    loose = run_compare(
        "--reference",
        str(ref),
        "--produced",
        str(got),
        "--tolerance",
        "1e-6",
        "--metric",
        "runtime=100",
        "--json",
    )
    assert loose.returncode == 0
    result = json.loads(loose.stdout)
    by_item = {r["item"]: r for r in result["items"]}
    assert by_item["runtime"]["rule"] == "runtime"
    assert by_item["auc"]["rule"] == "default"


def test_relative_tolerance_applies(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"loss": 1000.0}))
    got = write(tmp_path / "got.json", json.dumps({"loss": 1010.0}))
    proc = run_compare(
        "--reference",
        str(ref),
        "--produced",
        str(got),
        "--metric",
        "loss=0,0.02",
        "--json",
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["outcome"] == "within"


def test_missing_item_is_divergent(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.9, "f1": 0.5}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.9}))
    proc = run_compare("--reference", str(ref), "--produced", str(got), "--json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    statuses = {r["item"]: r["status"] for r in result["items"]}
    assert statuses["f1"] == "missing"


def test_csv_with_header_and_row_labels(tmp_path: Path):
    ref = write(tmp_path / "ref.csv", "model,auc,f1\nbase,0.90,0.71\nours,0.94,0.80\n")
    got = write(tmp_path / "got.csv", "model,auc,f1\nbase,0.90,0.71\nours,0.9401,0.80\n")
    proc = run_compare(
        "--reference", str(ref), "--produced", str(got), "--tolerance", "0.001", "--json"
    )
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    items = {r["item"] for r in result["items"]}
    assert "ours/auc" in items
    assert result["outcome"] == "within"


def test_plain_numeric_text(tmp_path: Path):
    ref = write(tmp_path / "ref.txt", "1.0\n2.0\n3.0\n")
    got = write(tmp_path / "got.txt", "1.0\n2.0\n3.5\n")
    proc = run_compare("--reference", str(ref), "--produced", str(got), "--json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["counts"]["outside"] == 1


def test_nonnumeric_txt_falls_back_to_byte_comparison(tmp_path: Path):
    ref = write(tmp_path / "ref.txt", "success\n")
    got = write(tmp_path / "got.txt", "failure\n")
    proc = run_compare("--reference", str(ref), "--produced", str(got), "--json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["outcome"] == "divergent"
    assert result["files"][0]["status"] == "bytes-differ"


def test_directory_comparison_reports_missing_file(tmp_path: Path):
    ref_dir = tmp_path / "ref"
    got_dir = tmp_path / "got"
    write(ref_dir / "metrics.json", json.dumps({"auc": 0.9}))
    write(ref_dir / "table.csv", "k,v\na,1\n")
    write(got_dir / "metrics.json", json.dumps({"auc": 0.9}))
    proc = run_compare("--reference", str(ref_dir), "--produced", str(got_dir), "--json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    files = {f["file"]: f["status"] for f in result["files"]}
    assert files["table.csv"] == "missing"


def test_file_and_directory_mismatch_is_usage_error(tmp_path: Path):
    ref = write(tmp_path / "ref.json", "{}")
    got_dir = tmp_path / "got"
    got_dir.mkdir()
    proc = run_compare("--reference", str(ref), "--produced", str(got_dir))
    assert proc.returncode == 2


def test_bad_metric_spec_is_usage_error(tmp_path: Path):
    ref = write(tmp_path / "ref.json", "{}")
    proc = run_compare("--reference", str(ref), "--produced", str(ref), "--metric", "auc")
    assert proc.returncode == 2


def test_unparsable_file_falls_back_to_bytes(tmp_path: Path):
    ref = write(tmp_path / "ref.pdf", "one")
    got = write(tmp_path / "got.pdf", "two")
    proc = run_compare("--reference", str(ref), "--produced", str(got), "--json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["files"][0]["status"] == "bytes-differ"


def test_out_is_dry_run_until_apply(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.9}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.9}))
    out = tmp_path / "report" / "compare.md"
    dry = run_compare("--reference", str(ref), "--produced", str(got), "--out", str(out))
    assert dry.returncode == 2
    assert not out.exists()
    assert "outside" in dry.stderr
    applied = run_compare(
        "--reference", str(ref), "--produced", str(got), "--out", str(out), "--apply"
    )
    assert applied.returncode == 0
    assert out.exists()
    assert "# Result comparison" in out.read_text(encoding="utf-8")


def test_json_out_is_written_when_applied(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.9}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.9}))
    out = tmp_path / "report" / "compare.json"
    proc = run_compare(
        "--reference",
        str(ref),
        "--produced",
        str(got),
        "--json",
        "--out",
        str(out),
        "--apply",
    )
    assert proc.returncode == 0
    assert json.loads(out.read_text(encoding="utf-8"))["outcome"] == "identical"


def test_report_has_no_em_dash(tmp_path: Path):
    ref = write(tmp_path / "ref.json", json.dumps({"auc": 0.9}))
    got = write(tmp_path / "got.json", json.dumps({"auc": 0.5}))
    proc = run_compare("--reference", str(ref), "--produced", str(got))
    assert proc.returncode == 1
    assert "—" not in proc.stdout
    assert "divergent" in proc.stdout


def test_parse_metric_and_tolerance_lookup():
    rule = compare_results.parse_metric("loss/*=0.01,0.05")
    assert rule == ("loss/*", 0.01, 0.05)
    tol = compare_results.Tolerances(1e-9, 0.0, [rule])
    assert tol.for_item("loss/train")[0] == 0.01
    assert tol.for_item("auc") == (1e-9, 0.0, "default")


def test_classify_prefers_worst_status():
    assert compare_results.classify([{"status": "exact"}], []) == "identical"
    assert compare_results.classify([{"status": "within"}], []) == "within"
    assert compare_results.classify([{"status": "exact"}], [{"status": "bytes-differ"}]) == (
        "divergent"
    )


# ------------------------------------------------------------------- repro_env.sh


def run_env(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(REPRO_ENV), *args], capture_output=True, text=True, check=False
    )


def test_repro_env_help_exits_zero():
    proc = run_env("--help")
    assert proc.returncode == 0
    assert "--repo" in proc.stdout


def test_repro_env_requires_repo_and_work():
    proc = run_env("--repo", "/tmp")
    assert proc.returncode == 2


def test_repro_env_rejects_bad_prefer(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = run_env(
        "--repo", str(repo), "--work", str(tmp_path / "w"), "--prefer", "whatever-i-like"
    )
    assert proc.returncode == 2


def test_repro_env_refuses_without_any_recipe(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "analysis.py").write_text("print(1)\n", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--json")
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert result["strategy"] == "none"
    kinds = {f["kind"] for f in result["findings"]}
    assert "no-environment-recipe" in kinds
    assert "refusing to fall back" in proc.stderr


def test_repro_env_prefers_container_recipe(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Dockerfile").write_text("FROM python:3.12.1\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--json")
    result = json.loads(proc.stdout)
    have_runtime = any(shutil.which(rt) for rt in ("docker", "podman"))
    if have_runtime:
        assert proc.returncode == 0
        assert result["strategy"] == "container"
        assert result["source"] == "Dockerfile"
        assert "--no-cache" in result["command"]
    else:
        assert proc.returncode == 1
        kinds = {f["kind"] for f in result["findings"]}
        assert "no-container-runtime" in kinds
        assert result["strategy"] == "none"


def test_repro_env_reports_missing_runtime_without_failing_obscurely(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "workflow.def").write_text("Bootstrap: docker\nFrom: python:3.12.1\n", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--json")
    result = json.loads(proc.stdout)
    if any(shutil.which(rt) for rt in ("apptainer", "singularity")):
        assert result["strategy"] == "container"
    else:
        assert proc.returncode == 1
        kinds = {f["kind"] for f in result["findings"]}
        assert "no-container-runtime" in kinds
        assert "no runtime found on PATH" in json.dumps(result["findings"])


def test_repro_env_venv_from_pinned_requirements(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("numpy==1.26.4\npandas==2.2.0\n", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--prefer", "venv", "--json")
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["strategy"] == "venv-requirements"
    assert result["source"] == "requirements.txt"
    kinds = {f["kind"] for f in result["findings"]}
    assert "resolver-in-the-loop" not in kinds
    assert "[dry-run]" not in proc.stdout  # --json prints only JSON


def test_repro_env_flags_unpinned_requirements(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("numpy\npandas==2.2.0\n", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--prefer", "venv", "--json")
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    kinds = {f["kind"] for f in result["findings"]}
    assert "unpinned-dependencies" in kinds
    assert "resolver-in-the-loop" in kinds


def test_repro_env_flags_image_without_recipe(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "env.sif").write_bytes(b"not really an image")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--json")
    result = json.loads(proc.stdout)
    kinds = {f["kind"] for f in result["findings"]}
    if any(shutil.which(rt) for rt in ("apptainer", "singularity")):
        assert "image-without-recipe" in kinds
    else:
        assert "no-container-runtime" in kinds


def test_repro_env_dry_run_writes_only_under_work(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    before = sorted(p.name for p in repo.iterdir())
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--prefer", "venv")
    assert proc.returncode == 0
    assert "[dry-run]" in proc.stdout
    assert sorted(p.name for p in repo.iterdir()) == before
    assert (work / "repro-env.json").exists()
    assert (work / "repro-env.txt").exists()
    assert not (work / "venv").exists()
    assert not (work / ".repro_env_findings").exists()


def test_repro_env_records_no_version_control(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    proc = run_env(
        "--repo", str(repo), "--work", str(tmp_path / "work"), "--prefer", "venv", "--json"
    )
    result = json.loads(proc.stdout)
    assert result["commit"] == "unknown"
    kinds = {f["kind"] for f in result["findings"]}
    assert "no-version-control" in kinds


def test_repro_env_build_creates_venv(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env(
        "--repo",
        str(repo),
        "--work",
        str(work),
        "--prefer",
        "venv",
        "--python",
        sys.executable,
        "--build",
        "--json",
    )
    result = json.loads(proc.stdout)
    assert result["strategy"] == "venv-requirements"
    assert result["build"] == "ok", proc.stderr + (work / "repro-env.log").read_text(
        encoding="utf-8"
    )
    assert (work / "venv").is_dir()
    assert proc.returncode == 0


def test_repro_env_output_has_no_em_dash(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    work = tmp_path / "work"
    proc = run_env("--repo", str(repo), "--work", str(work), "--prefer", "venv")
    assert "—" not in proc.stdout
    assert "—" not in (work / "repro-env.txt").read_text(encoding="utf-8")


# ------------------------------------------------------------------- skill files


def test_badge_reference_uses_acm_terms_accurately():
    text = (SKILL / "references" / "acm-badges.md").read_text(encoding="utf-8")
    assert "Results Reproduced" in text
    assert "Results Replicated" in text
    assert "Artifacts Available" in text
    for level in ("Functional", "Reusable"):
        assert level in text
    assert "Never claim Results Replicated" in text


def test_report_template_demands_the_evidence():
    text = (SKILL / "assets" / "repro-report.md").read_text(encoding="utf-8")
    for section in ("## Missing steps", "## Comparison", "## Badge grade", "## Improvisations"):
        assert section in text


def test_skill_cross_references_remote_connect_without_restating_it():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "remote-connect" in text
    assert "—" not in text
