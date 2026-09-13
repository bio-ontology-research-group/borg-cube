#!/usr/bin/env python3
"""Compare produced outputs against reference outputs with a numeric tolerance.

Reads a reference file (or directory) and a produced file (or directory),
flattens both into named numeric items, and reports the absolute and relative
difference of every item. CSV, JSON and plain numeric text are understood; any
other file is compared byte for byte.

The run is classified as one of:

* ``identical``   every item matches exactly and every compared file is equal
* ``within``      every item is inside its tolerance, but not all are exact
* ``divergent``   at least one item is outside its tolerance, or an item or
                  file is missing on one side

Tolerances are given as ``--tolerance ABS`` (the default for every item),
``--rel-tolerance REL``, and per metric with ``--metric NAME=ABS[,REL]``,
repeatable, where NAME is an item name or a glob over item names. The most
specific matching rule wins; a metric rule beats the defaults.

Exit status is 0 for identical or within, 1 for divergent, 2 for a usage or
read error. ``--out`` is a dry run unless ``--apply`` is given; an outside
path is refused without ``--apply``.

Example:
  compare_results.py --reference paper/results --produced runs/12/results \\
      --tolerance 1e-8 --metric 'auc=0.001' --metric 'loss/*=0.01,0.05' --json
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

CHECKS_VERSION = "1"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
NUMERIC_SUFFIXES = {".csv", ".tsv", ".json", ".txt", ".dat", ".out", ".tab"}
IDENTICAL, WITHIN, DIVERGENT = "identical", "within", "divergent"


class ReadError(Exception):
    """A file could not be parsed into comparable items."""


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------- flatten


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def flatten_json(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON into ``path/to/key -> scalar`` items."""
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            out.update(flatten_json(value, f"{prefix}/{key}" if prefix else str(key)))
    elif isinstance(data, list):
        for i, value in enumerate(data):
            out.update(flatten_json(value, f"{prefix}[{i}]" if prefix else f"[{i}]"))
    else:
        out[prefix or "value"] = data
    return out


def parse_csv(text: str, delimiter: str | None = None) -> dict[str, Any]:
    """Flatten a table into ``row/column -> cell`` items.

    A header row is used for column names when its cells are not all numeric.
    Rows are named by the first column when that column is not numeric, and by
    their index otherwise.
    """
    if delimiter is None:
        delimiter = "\t" if "\t" in text.splitlines()[0] else "," if text.strip() else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if r]
    if not rows:
        return {}
    header: list[str] | None = None
    if any(_number(cell) is None and cell.strip() for cell in rows[0]):
        header = [c.strip() or f"col{i}" for i, c in enumerate(rows[0])]
        rows = rows[1:]
    out: dict[str, Any] = {}
    for i, row in enumerate(rows):
        label = str(i)
        start = 0
        if row and _number(row[0]) is None and row[0].strip():
            label = row[0].strip()
            start = 1
        for j, cell in enumerate(row):
            if j < start:
                continue
            name = header[j] if header and j < len(header) else f"col{j}"
            out[f"{label}/{name}"] = cell.strip()
    return out


def parse_numeric_text(text: str) -> dict[str, Any]:
    """Flatten whitespace-separated numbers into ``line/index -> number``."""
    out: dict[str, Any] = {}
    for i, line in enumerate(text.splitlines()):
        fields = line.split()
        if not fields:
            continue
        for j, field in enumerate(fields):
            value = _number(field)
            if value is None:
                raise ReadError(f"line {i + 1} is not numeric: {line[:60]!r}")
            out[f"{i}/{j}" if len(fields) > 1 else str(i)] = value
    return out


def load_items(path: Path) -> dict[str, Any]:
    """Parse one file into named items, or raise ReadError."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReadError(str(exc)) from exc
    if suffix == ".json":
        try:
            return flatten_json(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ReadError(f"invalid JSON: {exc}") from exc
    if suffix in {".csv", ".tsv", ".tab"}:
        return parse_csv(text, "\t" if suffix in {".tsv", ".tab"} else ",")
    if suffix in NUMERIC_SUFFIXES:
        return parse_numeric_text(text)
    raise ReadError(f"no parser for {suffix or 'a file without a suffix'}")


# ------------------------------------------------------------------ tolerance


class Tolerances:
    """Absolute and relative tolerance per item name, with glob rules."""

    def __init__(self, absolute: float, relative: float, rules: list[tuple[str, float, float]]):
        self.absolute = absolute
        self.relative = relative
        self.rules = rules

    def for_item(self, name: str) -> tuple[float, float, str]:
        best: tuple[str, float, float] | None = None
        for pattern, abs_tol, rel_tol in self.rules:
            if pattern == name or fnmatch.fnmatch(name, pattern) or name.endswith("/" + pattern):
                if best is None or len(pattern) > len(best[0]):
                    best = (pattern, abs_tol, rel_tol)
        if best is None:
            return self.absolute, self.relative, "default"
        return best[1], best[2], best[0]


def parse_metric(spec: str) -> tuple[str, float, float]:
    """Parse ``NAME=ABS[,REL]`` into a tolerance rule."""
    if "=" not in spec:
        raise ValueError(f"--metric needs NAME=ABS[,REL], got {spec!r}")
    name, _, values = spec.partition("=")
    parts = [p.strip() for p in values.split(",") if p.strip()]
    if not parts or len(parts) > 2:
        raise ValueError(f"--metric needs NAME=ABS[,REL], got {spec!r}")
    try:
        abs_tol = float(parts[0])
        rel_tol = float(parts[1]) if len(parts) == 2 else 0.0
    except ValueError as exc:
        raise ValueError(f"--metric tolerances must be numbers: {spec!r}") from exc
    if not name.strip():
        raise ValueError(f"--metric needs a name: {spec!r}")
    return name.strip(), abs_tol, rel_tol


# ------------------------------------------------------------------- compare


def compare_items(
    reference: dict[str, Any], produced: dict[str, Any], tolerances: Tolerances, label: str
) -> list[dict[str, Any]]:
    """One record per item, with status exact, within, outside, missing or added."""
    out: list[dict[str, Any]] = []
    for name in sorted(set(reference) | set(produced)):
        item = f"{label}:{name}" if label else name
        abs_tol, rel_tol, rule = tolerances.for_item(name)
        record: dict[str, Any] = {
            "item": item,
            "abs_tolerance": abs_tol,
            "rel_tolerance": rel_tol,
            "rule": rule,
        }
        if name not in produced:
            record.update(status="missing", reference=reference[name], produced=None)
            out.append(record)
            continue
        if name not in reference:
            record.update(status="added", reference=None, produced=produced[name])
            out.append(record)
            continue
        ref_raw, got_raw = reference[name], produced[name]
        ref_num, got_num = _number(ref_raw), _number(got_raw)
        record.update(reference=ref_raw, produced=got_raw)
        if ref_num is None or got_num is None:
            record["status"] = "exact" if str(ref_raw) == str(got_raw) else "outside"
            record["note"] = "compared as text"
            out.append(record)
            continue
        if math.isnan(ref_num) and math.isnan(got_num):
            record["status"] = "exact"
            out.append(record)
            continue
        abs_diff = abs(got_num - ref_num)
        denominator = abs(ref_num)
        rel_diff = abs_diff / denominator if denominator else (0.0 if abs_diff == 0 else math.inf)
        record["abs_diff"] = abs_diff
        record["rel_diff"] = rel_diff
        if abs_diff == 0:
            record["status"] = "exact"
        elif abs_diff <= abs_tol or (rel_tol > 0 and rel_diff <= rel_tol):
            record["status"] = "within"
        else:
            record["status"] = "outside"
        out.append(record)
    return out


def list_files(path: Path) -> dict[str, Path]:
    if path.is_file():
        return {path.name: path}
    return {
        str(p.relative_to(path)): p
        for p in sorted(path.rglob("*"))
        if p.is_file() and not p.name.startswith(".")
    }


def compare_paths(
    reference: Path, produced: Path, tolerances: Tolerances
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare two files or two directories; returns (item records, file records)."""
    ref_files = list_files(reference)
    got_files = list_files(produced)
    if reference.is_file() and produced.is_file():
        ref_files = {"": reference}
        got_files = {"": produced}
    items: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for rel in sorted(set(ref_files) | set(got_files)):
        if rel not in got_files:
            files.append({"file": rel, "status": "missing"})
            continue
        if rel not in ref_files:
            files.append({"file": rel, "status": "added"})
            continue
        ref_path, got_path = ref_files[rel], got_files[rel]
        try:
            ref_items = load_items(ref_path)
            got_items = load_items(got_path)
        except ReadError as exc:
            same = ref_path.read_bytes() == got_path.read_bytes()
            files.append(
                {
                    "file": rel,
                    "status": "bytes-equal" if same else "bytes-differ",
                    "note": str(exc),
                }
            )
            continue
        records = compare_items(ref_items, got_items, tolerances, rel)
        files.append({"file": rel, "status": "compared", "items": len(records)})
        items.extend(records)
    return items, files


def classify(items: list[dict[str, Any]], files: list[dict[str, Any]]) -> str:
    statuses = {r["status"] for r in items} | {f["status"] for f in files}
    if statuses & {"outside", "missing", "added", "bytes-differ"}:
        return DIVERGENT
    if "within" in statuses:
        return WITHIN
    return IDENTICAL


def render(result: dict[str, Any]) -> str:
    lines = [
        "# Result comparison",
        "",
        f"- reference: {result['reference']}",
        f"- produced: {result['produced']}",
        f"- outcome: {result['outcome']}",
        f"- items compared: {result['counts']['total']}"
        f" (exact {result['counts']['exact']},"
        f" within {result['counts']['within']},"
        f" outside {result['counts']['outside']},"
        f" missing {result['counts']['missing']},"
        f" added {result['counts']['added']})",
        "",
    ]
    problems = [r for r in result["items"] if r["status"] in {"outside", "missing", "added"}]
    if problems:
        lines += [
            "## Items outside tolerance",
            "",
            "| item | reference | produced | abs diff | rel diff | tolerance | status |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in problems[:200]:
            abs_diff = f"{r['abs_diff']:.6g}" if "abs_diff" in r else ""
            rel_diff = f"{r['rel_diff']:.6g}" if "rel_diff" in r else ""
            tol = f"abs {r['abs_tolerance']:g}"
            if r["rel_tolerance"]:
                tol += f", rel {r['rel_tolerance']:g}"
            tol += f" ({r['rule']})"
            lines.append(
                f"| {r['item']} | {r['reference']} | {r['produced']} |"
                f" {abs_diff} | {rel_diff} | {tol} | {r['status']} |"
            )
        if len(problems) > 200:
            lines.append(f"| ... | | | | | | {len(problems) - 200} more |")
        lines.append("")
    odd_files = [f for f in result["files"] if f["status"] != "compared"]
    if odd_files:
        lines += ["## Files not compared item by item", ""]
        for f in odd_files:
            note = f" ({f['note']})" if f.get("note") else ""
            lines.append(f"- {f['file'] or '(single file)'}: {f['status']}{note}")
        lines.append("")
    if result["outcome"] == IDENTICAL:
        lines.append("Every compared item is exactly equal.")
    elif result["outcome"] == WITHIN:
        lines.append("Every compared item is inside its stated tolerance; none is exactly equal.")
    else:
        lines.append("The run is divergent. It is not evidence that the result was reproduced.")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="compare_results.py",
        description=(
            "Compare produced outputs against reference outputs with a numeric "
            "tolerance per metric and classify the run as identical, within "
            "tolerance, or divergent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit status: 0 identical or within tolerance, 1 divergent, 2 usage "
            "or read error. --out is a dry run unless --apply is given; outside "
            "paths are refused without --apply."
        ),
    )
    p.add_argument("--reference", required=True, type=Path, help="reference file or directory")
    p.add_argument("--produced", required=True, type=Path, help="produced file or directory")
    p.add_argument(
        "--tolerance", type=float, default=0.0, help="default absolute tolerance (default 0)"
    )
    p.add_argument(
        "--rel-tolerance", type=float, default=0.0, help="default relative tolerance (default 0)"
    )
    p.add_argument(
        "--metric",
        action="append",
        default=[],
        metavar="NAME=ABS[,REL]",
        help="tolerance for one item name or glob; repeatable",
    )
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    p.add_argument("--out", type=Path, default=None, help="write the report here (with --apply)")
    p.add_argument("--apply", action="store_true", help="write --out (default: print)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rules = [parse_metric(spec) for spec in args.metric]
    except ValueError as exc:
        print(f"compare-results: {exc}", file=sys.stderr)
        return 2
    for path in (args.reference, args.produced):
        if not path.exists():
            print(f"compare-results: no such path: {path}", file=sys.stderr)
            return 2
    if args.reference.is_dir() != args.produced.is_dir():
        print(
            "compare-results: --reference and --produced must both be files or both directories",
            file=sys.stderr,
        )
        return 2
    tolerances = Tolerances(args.tolerance, args.rel_tolerance, rules)
    try:
        items, files = compare_paths(args.reference, args.produced, tolerances)
    except OSError as exc:
        print(f"compare-results: {exc}", file=sys.stderr)
        return 2
    counts = {
        "total": len(items),
        "exact": sum(1 for r in items if r["status"] == "exact"),
        "within": sum(1 for r in items if r["status"] == "within"),
        "outside": sum(1 for r in items if r["status"] == "outside"),
        "missing": sum(1 for r in items if r["status"] == "missing"),
        "added": sum(1 for r in items if r["status"] == "added"),
    }
    result = {
        "checks_version": CHECKS_VERSION,
        "reference": str(args.reference),
        "produced": str(args.produced),
        "tolerance": {
            "absolute": args.tolerance,
            "relative": args.rel_tolerance,
            "metrics": [{"pattern": n, "abs": a, "rel": r} for n, a, r in rules],
        },
        "counts": counts,
        "outcome": classify(items, files),
        "files": files,
        "items": items,
    }
    report = (json.dumps(result, indent=2, default=str) + "\n") if args.json else render(result)
    if args.out:
        output = args.out.resolve()
        if not inside_repo(output) and not args.apply:
            print(
                f"compare-results: refusing to write {output} outside {REPO_ROOT}; "
                "rerun with --apply",
                file=sys.stderr,
            )
            return 2
        if args.apply:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report, encoding="utf-8")
            if args.json:
                print(report, end="")
            else:
                print(f"compare-results: {result['outcome']}; wrote {output}")
        else:
            print(report, end="")
            if not args.json:
                print("\n[dry-run] rerun with --apply to write the report")
    else:
        print(report, end="")
    return 1 if result["outcome"] == DIVERGENT else 0


if __name__ == "__main__":
    sys.exit(main())
