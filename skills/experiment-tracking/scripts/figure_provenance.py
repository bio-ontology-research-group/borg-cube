#!/usr/bin/env python3
"""Map the figures of a manuscript back to the runs that produced them.

Read-only and offline. Takes the manifest written by ``runs_manifest.py`` and
an explicit mapping file (``figure`` to ``run`` and ``output``; see
``assets/figure-map.yaml.example``), collects the figures actually used, and
reports for each one the run id, commit, dirty flag, seeds and whether the file
on disk still matches the artifact hash the run recorded.

Figures are collected from three places, in this order: every entry of the
mapping file, every image included by a manuscript given with ``--manuscript``
(LaTeX ``\\includegraphics`` and Markdown image links), and every image file in
a directory given with ``--figures``.

Findings carry a severity (high, medium, low, info):

* a figure with no mapping entry, or an entry naming an unknown run, is
  untraceable and reported as such rather than guessed at;
* a figure whose bytes differ from the run output it claims to come from is
  reported as edited after the run;
* a figure whose run has no seed, no commit or a dirty working tree inherits
  that run's unreproducible status;
* a run whose outputs no figure uses is reported as unused.

Nothing is written to the manuscript, the figures or the runs. Only paths,
hashes and run ids appear in the output.

Examples:
  figure_provenance.py --manifest runs/manifest.json --map paper/figures.yaml
  figure_provenance.py --manifest runs/manifest.json --map paper/figures.yaml \\
      --manuscript paper/main.tex --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPORT_VERSION = "2026-09-02"

IMAGE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".eps", ".tif", ".tiff", ".gif"}
INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
SEVERITIES = ("high", "medium", "low", "info")
BLOCKING_CHECKS = {"seed.missing", "commit.missing", "commit.dirty", "input.unversioned"}

DEFAULT_MAX_FIGURES = 500
DEFAULT_MAX_HASH_BYTES = 512 * 1024 * 1024


class ProvenanceError(Exception):
    """A problem that stops the report entirely."""


def finding(severity: str, check: str, message: str) -> dict[str, str]:
    if severity not in SEVERITIES:
        raise ProvenanceError(f"unknown severity {severity!r}")
    return {"severity": severity, "check": check, "message": message}


def sha256_file(path: Path, max_bytes: int) -> tuple[str | None, str | None]:
    try:
        if max_bytes and path.stat().st_size > max_bytes:
            return None, f"larger than --max-hash-bytes ({max_bytes})"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        return None, f"read failed: {exc.strerror or exc}"
    return digest.hexdigest(), None


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or "runs" not in data:
        raise ProvenanceError(f"{path} is not a runs_manifest.py manifest")
    return data


def load_map(path: Path) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProvenanceError(f"cannot read mapping {path}: {exc}") from exc
    if isinstance(data, dict):
        entries = data.get("figures")
    else:
        entries = data
    if not isinstance(entries, list):
        raise ProvenanceError(f"{path} must hold a list under 'figures'")
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("figure"):
            raise ProvenanceError(f"{path}: every mapping entry needs a 'figure' key")
        out.append(entry)
    return out


def manuscript_figures(paths: list[Path]) -> tuple[list[str], list[dict[str, str]]]:
    refs: list[str] = []
    findings: list[dict[str, str]] = []
    for path in paths:
        if not path.is_file():
            findings.append(finding("high", "manuscript.missing", f"{path} does not exist"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in INCLUDEGRAPHICS_RE.finditer(text):
            refs.append(match.group(1).strip())
        for match in MARKDOWN_IMAGE_RE.finditer(text):
            refs.append(match.group(1).strip())
    return refs, findings


def directory_figures(figures_dir: Path, max_figures: int) -> tuple[list[str], bool]:
    found: list[str] = []
    for path in sorted(figures_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if len(found) >= max_figures:
            return found, True
        found.append(str(path))
    return found, False


def resolve_figure(raw: str, roots: list[Path]) -> Path | None:
    """Resolve a figure reference against the given roots, trying image suffixes."""
    candidates = [Path(raw)]
    if not Path(raw).suffix:
        candidates += [Path(raw).with_suffix(suffix) for suffix in sorted(IMAGE_SUFFIXES)]
    for candidate in candidates:
        if candidate.is_absolute() and candidate.is_file():
            return candidate
        for root in roots:
            probe = root / candidate
            if probe.is_file():
                return probe
    return None


def match_entry(raw: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Exact path match first, then basename without suffix."""
    for entry in entries:
        if str(entry["figure"]) == raw:
            return entry
    stem = Path(raw).stem
    for entry in entries:
        if Path(str(entry["figure"])).stem == stem:
            return entry
    return None


def output_record(run: dict[str, Any], wanted: str) -> dict[str, Any] | None:
    for record in run.get("outputs", []):
        if (
            record.get("path") == wanted
            or Path(str(record.get("path", ""))).name == Path(wanted).name
        ):
            return record
    return None


def build(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.manifest)
    entries = load_map(args.map) if args.map else []
    runs = {str(r.get("run_id")): r for r in manifest.get("runs", [])}

    findings: list[dict[str, str]] = []
    if not entries:
        findings.append(
            finding(
                "high", "map.missing", "no mapping file given; no figure can be traced to a run"
            )
        )

    roots: list[Path] = [Path.cwd()]
    if args.map:
        roots.insert(0, args.map.resolve().parent)
    for path in args.manuscript:
        roots.insert(0, path.resolve().parent)
    if args.figures:
        roots.insert(0, args.figures.resolve())

    refs: list[str] = [str(e["figure"]) for e in entries]
    manuscript_refs, manuscript_findings = manuscript_figures(args.manuscript)
    findings += manuscript_findings
    refs += manuscript_refs
    truncated = False
    if args.figures:
        if not args.figures.is_dir():
            findings.append(
                finding("high", "figures.missing", f"{args.figures} is not a directory")
            )
        else:
            directory_refs, truncated = directory_figures(args.figures, args.max_figures)
            refs += directory_refs
            if truncated:
                findings.append(
                    finding(
                        "info",
                        "scan.truncated",
                        f"stopped after --max-figures ({args.max_figures}); "
                        "the figure list is incomplete",
                    )
                )

    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    ordered = ordered[: args.max_figures]

    used_outputs: set[tuple[str, str]] = set()
    figures: list[dict[str, Any]] = []
    for raw in ordered:
        record: dict[str, Any] = {
            "figure": raw,
            "resolved": None,
            "run_id": None,
            "output": None,
            "commit": None,
            "dirty": None,
            "seeds": {},
            "traceable": False,
            "matches_run_output": None,
            "findings": [],
        }
        resolved = resolve_figure(raw, roots)
        record["resolved"] = str(resolved) if resolved else None
        if resolved is None:
            record["findings"].append(
                finding("medium", "figure.missing", f"figure file {raw!r} not found on disk")
            )
        entry = match_entry(raw, entries)
        if entry is None:
            record["findings"].append(
                finding(
                    "high", "figure.untraceable", f"figure {raw!r} has no entry in the mapping file"
                )
            )
            figures.append(record)
            findings += record["findings"]
            continue
        run_id = str(entry.get("run") or "")
        record["run_id"] = run_id or None
        record["output"] = entry.get("output")
        run = runs.get(run_id)
        if run is None:
            record["findings"].append(
                finding(
                    "high",
                    "figure.unknown-run",
                    f"figure {raw!r} names run {run_id!r}, which is not in the manifest",
                )
            )
            figures.append(record)
            findings += record["findings"]
            continue
        record["commit"] = run.get("git", {}).get("commit")
        record["dirty"] = run.get("git", {}).get("dirty")
        record["seeds"] = run.get("seeds", {})
        record["traceable"] = True

        blocking = sorted(
            {f["check"] for f in run.get("findings", []) if f["check"] in BLOCKING_CHECKS}
        )
        if blocking:
            record["findings"].append(
                finding(
                    "high",
                    "figure.unreproducible-run",
                    f"run {run_id!r} is unreproducible ({', '.join(blocking)}); "
                    "the figure inherits this",
                )
            )

        wanted = str(entry.get("output") or "")
        if not wanted:
            record["findings"].append(
                finding(
                    "medium",
                    "figure.no-output",
                    f"figure {raw!r} names run {run_id!r} but no output artifact within it",
                )
            )
        else:
            out_record = output_record(run, wanted)
            if out_record is None:
                record["findings"].append(
                    finding(
                        "high",
                        "figure.output-not-in-run",
                        f"run {run_id!r} has no recorded output {wanted!r}",
                    )
                )
            else:
                used_outputs.add((run_id, str(out_record.get("path"))))
                recorded = out_record.get("sha256")
                if resolved is not None and recorded:
                    digest, reason = sha256_file(resolved, args.max_hash_bytes)
                    if digest is None:
                        record["findings"].append(
                            finding(
                                "low", "figure.unhashed", f"figure {raw!r} not hashed: {reason}"
                            )
                        )
                    else:
                        record["matches_run_output"] = digest == recorded
                        if digest != recorded:
                            record["findings"].append(
                                finding(
                                    "high",
                                    "figure.edited",
                                    f"figure {raw!r} differs from the run output {wanted!r}; "
                                    "it was edited or regenerated outside the run",
                                )
                            )
                elif not recorded:
                    record["findings"].append(
                        finding(
                            "medium",
                            "figure.output-unhashed",
                            f"run {run_id!r} recorded no hash for {wanted!r}; "
                            "the figure cannot be verified",
                        )
                    )
        figures.append(record)
        findings += record["findings"]

    unused: list[dict[str, Any]] = []
    for run_id, run in runs.items():
        outputs = [str(o.get("path")) for o in run.get("outputs", [])]
        used = [o for o in outputs if (run_id, o) in used_outputs]
        if outputs and not used:
            unused.append({"run_id": run_id, "outputs": len(outputs)})
            findings.append(
                finding("info", "run.unused", f"no figure uses any output of run {run_id!r}")
            )
        elif outputs:
            leftover = [o for o in outputs if (run_id, o) not in used_outputs]
            if leftover:
                unused.append({"run_id": run_id, "outputs": len(leftover), "partial": True})

    counts = {s: 0 for s in SEVERITIES}
    for f in findings:
        counts[f["severity"]] += 1

    return {
        "report_version": REPORT_VERSION,
        "generated": dt.datetime.now().replace(microsecond=0).isoformat(),
        "manifest": str(args.manifest),
        "map": str(args.map) if args.map else None,
        "limits": {
            "max_figures": args.max_figures,
            "max_hash_bytes": args.max_hash_bytes,
            "figures_truncated": truncated,
            "note": "read-only; paths, hashes and run ids only",
        },
        "summary": {
            "figures": len(figures),
            "traceable": sum(1 for f in figures if f["traceable"]),
            "untraceable": sum(1 for f in figures if not f["traceable"]),
            "runs": len(runs),
            "runs_unused": sum(1 for u in unused if not u.get("partial")),
            "findings": counts,
        },
        "figures": figures,
        "unused_runs": unused,
        "findings": findings,
    }


def render(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [f"# Figure provenance ({report['manifest']})", ""]
    lines.append(
        f"{summary['figures']} figure(s), {summary['traceable']} traceable, "
        f"{summary['untraceable']} untraceable; "
        f"{summary['runs_unused']} of {summary['runs']} run(s) unused"
    )
    lines.append("Findings: " + ", ".join(f"{k} {summary['findings'][k]}" for k in SEVERITIES))
    limits = report["limits"]
    lines.append(
        f"Limits: at most {limits['max_figures']} figures, "
        f"{limits['max_hash_bytes']} bytes hashed per file"
        + ("; figure list truncated" if limits["figures_truncated"] else "")
    )
    lines.append("")
    lines.append("| figure | run | commit | seeds | matches run output |")
    lines.append("| --- | --- | --- | --- | --- |")
    for fig in report["figures"]:
        commit = (fig["commit"] or "")[:12] or "-"
        if fig["dirty"]:
            commit += " (dirty)"
        seeds = ", ".join(f"{k}={v}" for k, v in sorted(fig["seeds"].items())) or "-"
        match = {True: "yes", False: "no", None: "-"}[fig["matches_run_output"]]
        lines.append(f"| {fig['figure']} | {fig['run_id'] or '-'} | {commit} | {seeds} | {match} |")
    lines.append("")
    if report["findings"]:
        lines.append("## Findings")
        lines.append("")
        for f in report["findings"]:
            lines.append(f"- {f['severity']}: {f['check']}: {f['message']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


EXAMPLE = """figures:
  - figure: figures/fig2-roc.png
    run: 2026-09-02-baseline-01
    output: figures/roc.png
  - figure: figures/fig3-ablation.pdf
    run: 2026-09-03-ablation-04
    output: figures/ablation.pdf
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--manifest", type=Path, help="JSON manifest from runs_manifest.py")
    p.add_argument("--map", type=Path, default=None, help="figure to run mapping (YAML)")
    p.add_argument(
        "--manuscript",
        type=Path,
        action="append",
        default=[],
        help="manuscript source to scan for figure includes (repeatable)",
    )
    p.add_argument("--figures", type=Path, default=None, help="directory of figure files")
    p.add_argument("--max-figures", type=int, default=DEFAULT_MAX_FIGURES)
    p.add_argument("--max-hash-bytes", type=int, default=DEFAULT_MAX_HASH_BYTES)
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    p.add_argument(
        "--fail-on",
        choices=SEVERITIES,
        default=None,
        help="exit 1 when a finding of this severity or worse was recorded",
    )
    p.add_argument("--example", action="store_true", help="print an example mapping file and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.example:
        print(EXAMPLE, end="")
        return 0
    if args.manifest is None:
        print("figure_provenance: --manifest is required (or use --example)", file=sys.stderr)
        return 2
    try:
        report = build(args)
    except ProvenanceError as exc:
        print(f"figure_provenance: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2) if args.json else render(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"figure_provenance: wrote {args.out}", file=sys.stderr)
    print(text)
    if args.fail_on:
        threshold = SEVERITIES.index(args.fail_on)
        for level in SEVERITIES[: threshold + 1]:
            if report["summary"]["findings"][level]:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
