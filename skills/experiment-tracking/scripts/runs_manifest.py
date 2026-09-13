#!/usr/bin/env python3
"""Build a run manifest for every experiment run under a runs directory.

Read-only and offline. For each run it records: run id, command, git commit and
dirty flag, seeds, config hash, input paths with sizes and hashes, environment
(python and pinned package versions when a lock or requirements file is
present), start and end time, exit status, and output artifacts with hashes.

A run directory is one that contains a descriptor (``run.yaml``, ``run.yml`` or
``run.json``; see ``assets/run.yaml.example``). With ``--infer`` every immediate
subdirectory of the runs directory counts as a run even without a descriptor,
and the fields that can be observed from the filesystem are filled in.

Anything the collector cannot establish becomes a finding with a severity
(high, medium, low, info) rather than a silent gap: a run with no recorded
seed, no commit, or a dirty working tree is reported as unreproducible; an
input that could not be hashed is reported as unhashed. Nothing is repaired.

The scan is bounded and states its limits in the output: ``--max-runs``,
``--max-files`` per run and ``--max-hash-bytes`` per file. Files over the hash
limit are recorded with their size and a null hash plus a finding.

Only paths, sizes, hashes and versions are recorded. No data content is read
into the output.

Examples:
  runs_manifest.py --runs runs/experiments --json
  runs_manifest.py --runs runs/experiments --repo . --out runs/manifest.json
  runs_manifest.py --runs runs/experiments --fail-on high
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

MANIFEST_VERSION = "2026-09-02"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

DESCRIPTOR_NAMES = ("run.yaml", "run.yml", "run.json")
LOCK_NAMES = (
    "requirements.txt",
    "requirements.lock",
    "uv.lock",
    "poetry.lock",
    "environment.yml",
    "environment.yaml",
    "Pipfile.lock",
    "conda-lock.yml",
)
CONFIG_SUFFIXES = (".yaml", ".yml", ".json", ".toml", ".ini", ".cfg")
SKIP_DIRS = {".git", "__pycache__", ".ipynb_checkpoints", ".venv", "venv", "node_modules"}

DEFAULT_MAX_RUNS = 500
DEFAULT_MAX_FILES = 2000
DEFAULT_MAX_HASH_BYTES = 512 * 1024 * 1024

SEVERITIES = ("high", "medium", "low", "info")
PINNED_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([^\s;#]+)")
REPRODUCIBILITY_BLOCKERS = {
    "seed.missing",
    "commit.missing",
    "commit.dirty",
    "commit.dirty-unknown",
    "status.failed",
    "input.missing",
    "input.unversioned",
    "input.unhashed",
    "input.hash-mismatch",
    "input.undeclared",
    "output.missing",
    "output.none",
}


class CollectError(Exception):
    """A problem that stops collection entirely."""


# --------------------------------------------------------------------------- helpers


def sha256_file(path: Path, max_bytes: int) -> tuple[str | None, int, str | None]:
    """Return (hash, size, reason-if-not-hashed) for a file. Never reads content out."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, -1, f"stat failed: {exc.strerror or exc}"
    if max_bytes and size > max_bytes:
        return None, size, f"larger than --max-hash-bytes ({max_bytes})"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        return None, size, f"read failed: {exc.strerror or exc}"
    return digest.hexdigest(), size, None


def load_descriptor(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise CollectError(f"{path}: descriptor must be a mapping")
    return data


def find_descriptor(run_dir: Path) -> Path | None:
    for name in DESCRIPTOR_NAMES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def mtime_iso(path: Path) -> str | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()
    except OSError:
        return None


def git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def git_state(repo: Path | None) -> dict[str, Any]:
    """Observed git state of a checkout. All fields None when git cannot answer."""
    out: dict[str, Any] = {"repo": str(repo) if repo else None, "commit": None, "dirty": None}
    if repo is None or not repo.is_dir():
        return out
    commit = git(repo, "rev-parse", "HEAD")
    if commit is None:
        return out
    out["commit"] = commit
    status = git(repo, "status", "--porcelain")
    out["dirty"] = bool(status)
    out["branch"] = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return out


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def walk_files(root: Path, max_files: int) -> tuple[list[Path], bool]:
    """Files under root, skipping noise directories. Second value is True when truncated."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if len(found) >= max_files:
                return found, True
            found.append(Path(dirpath) / name)
    return found, False


def parse_lock(path: Path) -> dict[str, str]:
    """Pinned ``name==version`` entries from a requirements or lock file."""
    packages: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return packages
    for line in text.splitlines():
        match = PINNED_RE.match(line)
        if match:
            packages[match.group(1).lower()] = match.group(2)
    return packages


# --------------------------------------------------------------------------- one run


def finding(severity: str, check: str, message: str) -> dict[str, str]:
    if severity not in SEVERITIES:
        raise CollectError(f"unknown severity {severity!r}")
    return {"severity": severity, "check": check, "message": message}


def resolve(run_dir: Path, raw: str) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (run_dir / candidate)


def hash_entries(
    run_dir: Path, entries: list[Any], max_hash_bytes: int, kind: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Hash a list of declared paths. Returns (records, findings)."""
    records: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    for entry in entries:
        if isinstance(entry, str):
            spec: dict[str, Any] = {"path": entry}
        elif isinstance(entry, dict) and entry.get("path"):
            spec = dict(entry)
        else:
            findings.append(
                finding("medium", f"{kind}.malformed", f"{kind} entry without a path: {entry!r}")
            )
            continue
        path = resolve(run_dir, str(spec["path"]))
        record: dict[str, Any] = {
            "path": str(spec["path"]),
            "resolved": str(path),
            "version": spec.get("version"),
            "exists": path.is_file(),
            "size": None,
            "sha256": spec.get("sha256"),
            "hash_note": None,
        }
        if not path.is_file():
            record["hash_note"] = "path does not exist or is not a file"
            findings.append(
                finding("high", f"{kind}.missing", f"{kind} {spec['path']!r} does not exist")
            )
            records.append(record)
            continue
        digest, size, reason = sha256_file(path, max_hash_bytes)
        record["size"] = size
        record["hash_note"] = reason
        if digest is None:
            findings.append(
                finding(
                    "medium", f"{kind}.unhashed", f"{kind} {spec['path']!r} not hashed: {reason}"
                )
            )
        else:
            declared = spec.get("sha256")
            if declared and declared != digest:
                findings.append(
                    finding(
                        "high",
                        f"{kind}.hash-mismatch",
                        f"{kind} {spec['path']!r} hash differs from the recorded one",
                    )
                )
            record["sha256"] = digest
        if kind == "input" and not record["version"] and record["sha256"] is None:
            findings.append(
                finding(
                    "high",
                    "input.unversioned",
                    f"input {spec['path']!r} has neither a hash nor a version",
                )
            )
        records.append(record)
    return records, findings


def collect_run(
    run_dir: Path,
    default_repo: Path | None,
    max_files: int,
    max_hash_bytes: int,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    descriptor_path = find_descriptor(run_dir)
    data: dict[str, Any] = {}
    if descriptor_path is not None:
        try:
            data = load_descriptor(descriptor_path)
        except (CollectError, yaml.YAMLError, json.JSONDecodeError, OSError) as exc:
            findings.append(finding("high", "descriptor.unreadable", f"{descriptor_path}: {exc}"))
    else:
        findings.append(
            finding(
                "high",
                "descriptor.missing",
                f"no {' / '.join(DESCRIPTOR_NAMES)} in {run_dir}; "
                "fields inferred from the filesystem",
            )
        )

    run_id = str(data.get("run_id") or data.get("id") or run_dir.name)

    command = data.get("command")
    if not command:
        cmd_file = run_dir / "command.txt"
        if cmd_file.is_file():
            command = cmd_file.read_text(encoding="utf-8", errors="replace").strip()
    if not command:
        findings.append(finding("high", "command.missing", "no command recorded for this run"))

    # git
    repo_raw = data.get("repo")
    repo = resolve(run_dir, str(repo_raw)) if repo_raw else default_repo
    observed = git_state(repo)
    commit = data.get("commit") or observed.get("commit")
    dirty = data.get("dirty")
    if dirty is None:
        dirty = observed.get("dirty")
    if not commit:
        findings.append(
            finding("high", "commit.missing", "no git commit recorded and none observable")
        )
    elif observed.get("commit") and data.get("commit") and observed["commit"] != data["commit"]:
        findings.append(
            finding(
                "info",
                "commit.moved",
                "the checkout is now at a different commit than the one recorded for the run",
            )
        )
    if dirty:
        findings.append(
            finding(
                "high",
                "commit.dirty",
                "the working tree was dirty; this result is not reproducible from a commit",
            )
        )
    elif dirty is None:
        findings.append(
            finding(
                "medium",
                "commit.dirty-unknown",
                "no dirty flag recorded and no checkout to inspect",
            )
        )

    # seeds
    seeds = data.get("seeds")
    if isinstance(seeds, (int, str)):
        seeds = {"global": seeds}
    if not isinstance(seeds, dict) or not seeds:
        seeds = {}
        findings.append(
            finding(
                "high", "seed.missing", "no seed recorded; this result cannot be reproduced exactly"
            )
        )

    # config
    config_records: list[dict[str, Any]] = []
    config_entries = data.get("config")
    if isinstance(config_entries, str):
        config_entries = [config_entries]
    if not config_entries:
        config_entries = [
            str(p.relative_to(run_dir))
            for p in sorted(run_dir.glob("*"))
            if p.is_file() and p.suffix in CONFIG_SUFFIXES and p.name not in DESCRIPTOR_NAMES
        ]
    if config_entries:
        config_records, config_findings = hash_entries(
            run_dir, list(config_entries), max_hash_bytes, "config"
        )
        findings += config_findings
    else:
        findings.append(
            finding("medium", "config.missing", "no configuration file recorded for this run")
        )
    config_hash = None
    hashes = [c["sha256"] for c in config_records if c.get("sha256")]
    if hashes:
        config_hash = hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()

    # inputs and outputs
    inputs, input_findings = hash_entries(
        run_dir, list(data.get("inputs") or []), max_hash_bytes, "input"
    )
    findings += input_findings
    if not data.get("inputs"):
        findings.append(
            finding("medium", "input.undeclared", "no input data declared for this run")
        )

    declared_outputs = data.get("outputs")
    truncated = False
    if declared_outputs:
        outputs, output_findings = hash_entries(
            run_dir, list(declared_outputs), max_hash_bytes, "output"
        )
        findings += output_findings
    else:
        outputs = []
        files, truncated = walk_files(run_dir, max_files)
        for path in files:
            if path.name in DESCRIPTOR_NAMES:
                continue
            if str(path) in {c.get("resolved") for c in config_records}:
                continue
            digest, size, reason = sha256_file(path, max_hash_bytes)
            outputs.append(
                {
                    "path": str(path.relative_to(run_dir)),
                    "resolved": str(path),
                    "version": None,
                    "exists": True,
                    "size": size,
                    "sha256": digest,
                    "hash_note": reason or "discovered by walking the run directory",
                }
            )
            if digest is None and reason:
                findings.append(
                    finding("low", "output.unhashed", f"output {path.name!r} not hashed: {reason}")
                )
        if truncated:
            findings.append(
                finding(
                    "info",
                    "scan.truncated",
                    f"stopped after --max-files ({max_files}); "
                    "the output list for this run is incomplete",
                )
            )
    if not outputs:
        findings.append(finding("info", "output.none", "the run produced no output artifacts"))

    # environment
    environment: dict[str, Any] = {}
    env_data = data.get("environment") if isinstance(data.get("environment"), dict) else {}
    environment["python"] = env_data.get("python")
    lock_raw = env_data.get("lock")
    lock_path: Path | None = None
    if lock_raw:
        lock_path = resolve(run_dir, str(lock_raw))
    else:
        for name in LOCK_NAMES:
            for base in (run_dir, repo) if repo else (run_dir,):
                if base is None:
                    continue
                candidate = base / name
                if candidate.is_file():
                    lock_path = candidate
                    break
            if lock_path is not None:
                break
    if lock_path is not None and lock_path.is_file():
        environment["lock"] = str(lock_path)
        digest, size, reason = sha256_file(lock_path, max_hash_bytes)
        environment["lock_sha256"] = digest
        environment["lock_size"] = size
        if reason:
            environment["lock_note"] = reason
        packages = parse_lock(lock_path)
        environment["packages"] = packages
        if not packages:
            findings.append(
                finding(
                    "medium",
                    "environment.unpinned",
                    f"{lock_path.name} contains no name==version pins",
                )
            )
    else:
        environment["lock"] = None
        environment["packages"] = {}
        findings.append(
            finding(
                "medium", "environment.missing", "no lock or requirements file found for this run"
            )
        )
    if not environment.get("python"):
        findings.append(finding("low", "environment.python", "no python version recorded"))

    # timing and status
    started = iso(data.get("started") or data.get("start"))
    ended = iso(data.get("ended") or data.get("end"))
    if started is None and descriptor_path is not None:
        started = mtime_iso(descriptor_path)
        findings.append(
            finding(
                "low", "time.inferred", "start time inferred from the descriptor modification time"
            )
        )
    elif started is None:
        findings.append(finding("low", "time.missing", "no start time recorded"))
    if ended is None:
        findings.append(finding("low", "time.missing", "no end time recorded"))

    exit_status = data.get("exit_status", data.get("exit_code"))
    if exit_status is None:
        findings.append(finding("medium", "status.missing", "no exit status recorded"))
    elif isinstance(exit_status, int) and exit_status != 0:
        findings.append(
            finding("high", "status.failed", f"the run exited with status {exit_status}")
        )

    reproducible = not any(
        f["check"] in REPRODUCIBILITY_BLOCKERS for f in findings
    )

    return {
        "run_id": run_id,
        "path": str(run_dir),
        "descriptor": str(descriptor_path) if descriptor_path else None,
        "command": command,
        "git": {
            "repo": str(repo) if repo else None,
            "commit": commit,
            "dirty": dirty,
            "branch": observed.get("branch"),
        },
        "seeds": seeds,
        "config": config_records,
        "config_hash": config_hash,
        "inputs": inputs,
        "environment": environment,
        "started": started,
        "ended": ended,
        "exit_status": exit_status,
        "outputs": outputs,
        "reproducible": reproducible,
        "findings": findings,
    }


# --------------------------------------------------------------------------- driver


def discover_runs(runs_dir: Path, infer: bool, max_runs: int) -> tuple[list[Path], bool]:
    found: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(runs_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        current = Path(dirpath)
        if current == runs_dir:
            continue
        if find_descriptor(current) is not None:
            if len(found) >= max_runs:
                return found, True
            found.append(current)
            dirnames[:] = []
    if infer:
        known = set(found)
        for child in sorted(
            p for p in runs_dir.iterdir() if p.is_dir() and p.name not in SKIP_DIRS
        ):
            if child in known:
                continue
            if len(found) >= max_runs:
                return found, True
            found.append(child)
            known.add(child)
    return found, False


def build(args: argparse.Namespace) -> dict[str, Any]:
    runs_dir = args.runs.resolve()
    if not runs_dir.is_dir():
        raise CollectError(f"runs directory not found: {runs_dir}")
    repo = args.repo.resolve() if args.repo else None
    run_dirs, truncated = discover_runs(runs_dir, args.infer, args.max_runs)
    runs = [collect_run(d, repo, args.max_files, args.max_hash_bytes) for d in run_dirs]
    counts = {s: 0 for s in SEVERITIES}
    for run in runs:
        for f in run["findings"]:
            counts[f["severity"]] += 1
    return {
        "manifest_version": MANIFEST_VERSION,
        "generated": dt.datetime.now().replace(microsecond=0).isoformat(),
        "runs_dir": str(runs_dir),
        "repo": str(repo) if repo else None,
        "limits": {
            "max_runs": args.max_runs,
            "max_files_per_run": args.max_files,
            "max_hash_bytes": args.max_hash_bytes,
            "runs_truncated": truncated,
            "infer": args.infer,
            "note": "read-only scan; paths, sizes and hashes only, never data content",
        },
        "summary": {
            "runs": len(runs),
            "reproducible": sum(1 for r in runs if r["reproducible"]),
            "findings": counts,
        },
        "runs": runs,
    }


def render(manifest: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = manifest["summary"]
    lines.append(f"# Run manifest ({manifest['runs_dir']})")
    lines.append("")
    lines.append(
        f"{summary['runs']} run(s), {summary['reproducible']} reproducible; "
        f"findings: " + ", ".join(f"{k} {summary['findings'][k]}" for k in SEVERITIES)
    )
    limits = manifest["limits"]
    lines.append(
        f"Limits: at most {limits['max_runs']} runs, {limits['max_files_per_run']} files per run, "
        f"{limits['max_hash_bytes']} bytes hashed per file"
        + ("; run list truncated" if limits["runs_truncated"] else "")
    )
    lines.append("")
    for run in manifest["runs"]:
        git_info = run["git"]
        commit = (git_info["commit"] or "no commit")[:12]
        dirty = (
            "dirty" if git_info["dirty"] else ("clean" if git_info["dirty"] is False else "unknown")
        )
        lines.append(f"## {run['run_id']}")
        lines.append("")
        lines.append(f"- path: {run['path']}")
        lines.append(f"- command: {run['command'] or 'not recorded'}")
        lines.append(f"- commit: {commit} ({dirty})")
        lines.append(
            "- seeds: "
            + (", ".join(f"{k}={v}" for k, v in sorted(run["seeds"].items())) or "none recorded")
        )
        lines.append(f"- config hash: {run['config_hash'] or 'none'}")
        lines.append(f"- inputs: {len(run['inputs'])}, outputs: {len(run['outputs'])}")
        lines.append(f"- started: {run['started'] or '?'}, ended: {run['ended'] or '?'}")
        lines.append(
            f"- exit status: {run['exit_status'] if run['exit_status'] is not None else '?'}"
        )
        lines.append(f"- reproducible: {'yes' if run['reproducible'] else 'no'}")
        if run["findings"]:
            lines.append("- findings:")
            for f in run["findings"]:
                lines.append(f"  - {f['severity']}: {f['check']}: {f['message']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--runs", type=Path, required=False, help="directory holding the run directories"
    )
    p.add_argument("--repo", type=Path, default=None, help="git checkout the runs came from")
    p.add_argument(
        "--infer",
        action="store_true",
        help="treat every immediate subdirectory as a run, including bare directories",
    )
    p.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS)
    p.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    p.add_argument("--max-hash-bytes", type=int, default=DEFAULT_MAX_HASH_BYTES)
    p.add_argument("--json", action="store_true", help="print the manifest as JSON")
    p.add_argument("--out", type=Path, default=None, help="write the JSON manifest here")
    p.add_argument(
        "--apply", action="store_true", help="allow --out outside this repository"
    )
    p.add_argument(
        "--fail-on",
        choices=SEVERITIES,
        default=None,
        help="exit 1 when a finding of this severity or worse was recorded",
    )
    p.add_argument(
        "--example", action="store_true", help="print an example run descriptor and exit"
    )
    return p


EXAMPLE = """run_id: 2026-09-02-baseline-01
command: python train.py --config config.yaml --seed 20260902
repo: ../../..
commit: 0000000000000000000000000000000000000000
dirty: false
seeds:
  global: 20260902
  data_split: 7
config: config.yaml
inputs:
  - path: ../../data/train-v3.parquet
    version: v3
environment:
  python: '3.12.4'
  lock: ../../requirements.txt
started: '2026-09-02T09:14:03'
ended: '2026-09-02T11:47:55'
exit_status: 0
outputs:
  - metrics.json
  - figures/roc.png
"""


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.example:
        print(EXAMPLE, end="")
        return 0
    if args.runs is None:
        print("runs_manifest: --runs is required (or use --example)", file=sys.stderr)
        return 2
    try:
        manifest = build(args)
    except CollectError as exc:
        print(f"runs_manifest: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(manifest, indent=2) if args.json else render(manifest)
    if args.out:
        output = args.out.resolve()
        if not inside_repo(output) and not args.apply:
            print(
                f"runs_manifest: refusing to write {output} outside {REPO_ROOT}; "
                "rerun with --apply",
                file=sys.stderr,
            )
            return 2
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"runs_manifest: wrote {output}", file=sys.stderr)
    print(text)
    if args.fail_on:
        threshold = SEVERITIES.index(args.fail_on)
        for level in SEVERITIES[: threshold + 1]:
            if manifest["summary"]["findings"][level]:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
