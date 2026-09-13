#!/usr/bin/env python3
"""Append-only search log for a literature review, with PRISMA-style flow counts.

The log is a JSONL file. Every line is one event: the protocol, a declared
exclusion reason code, a database search, a deduplication step, a screening
decision or a retrieval attempt. Lines are only ever appended, and each line
carries a hash chain over the line before it, so an edit to history shows up in
``validate``.

``flow`` renders the counts of the PRISMA 2020 flow diagram (identified,
duplicates removed, screened, excluded, sought for retrieval, not retrieved,
assessed for eligibility, excluded with reasons, included). It refuses to
render when a screening decision carries no declared reason code, when a record
is screened twice at the same stage, or when the numbers do not reconcile.

Examples:
  search_log.py init --log runs/12/search.jsonl --question "..." --review-type systematized
  search_log.py add-code --log runs/12/search.jsonl --code E3 --stage full-text \
      --description "no evaluation on a public benchmark"
  search_log.py add-search --log runs/12/search.jsonl --date 2026-09-02 \
      --database PubMed --interface web --query '("gene ontology"[tiab]) AND ...' \
      --filters "2015:2026[dp]" --hits 412
  search_log.py add-screen --log runs/12/search.jsonl --date 2026-09-03 \
      --stage title-abstract --record 10.1093/bioinformatics/btz123 --decision exclude --reason E1
  search_log.py flow --log runs/12/search.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

STAGES = ("title-abstract", "full-text")
CODE_STAGES = STAGES + ("both",)
SOURCE_KINDS = ("database", "register", "other-methods")
DECISIONS = ("include", "exclude")
RETRIEVAL = ("retrieved", "not-retrieved")

DEFAULT_CODES = [
    ("E1", "both", "not about the review topic"),
    ("E2", "both", "wrong publication type (editorial, abstract, poster)"),
    ("E3", "both", "outside the date or language limits of the protocol"),
    ("E4", "full-text", "no method or no results reported"),
    ("E5", "full-text", "duplicate report of an already included study"),
    ("E6", "full-text", "full text not in a language we read"),
]


class LogError(Exception):
    """A refusal: the log is inconsistent or the request would guess."""


# --------------------------------------------------------------------------- io


def canonical(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "chain"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain_of(prev_chain: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256((prev_chain + canonical(entry)).encode("utf-8")).hexdigest()


def _parse_log_lines(path: Path, lines: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LogError(f"{path}:{lineno}: not JSON ({exc})") from exc
        if not isinstance(entry, dict) or "type" not in entry:
            raise LogError(f"{path}:{lineno}: entry has no type")
        entries.append(entry)
    return entries


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return _parse_log_lines(path, handle)


def _read_locked_log(path: Path, handle: Any) -> list[dict[str, Any]]:
    handle.seek(0)
    return _parse_log_lines(path, handle)


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def append(path: Path, entry: dict[str, Any], apply: bool) -> dict[str, Any]:
    """Append one entry. Writing outside the repository needs --apply."""
    if not inside_repo(path) and not apply:
        existing = read_log(path)
        prev_chain = existing[-1].get("chain", "") if existing else ""
        entry = dict(entry)
        entry["seq"] = len(existing) + 1
        entry["chain"] = chain_of(prev_chain, entry)
        print(f"[dry-run] would append to {path} (outside {REPO_ROOT}); rerun with --apply")
        print(json.dumps(entry, ensure_ascii=False))
        return entry
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            # The sequence and chain must be calculated from the file after locking.
            existing = _read_locked_log(path, handle)
            prev_chain = existing[-1].get("chain", "") if existing else ""
            entry = dict(entry)
            entry["seq"] = len(existing) + 1
            entry["chain"] = chain_of(prev_chain, entry)
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return entry
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def today() -> str:
    return dt.date.today().isoformat()


def norm_record(value: str) -> str:
    return value.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")


# --------------------------------------------------------------------------- validation


def check_chain(entries: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    prev = ""
    for i, entry in enumerate(entries, 1):
        if entry.get("seq") != i:
            problems.append(f"line {i}: seq is {entry.get('seq')!r}, expected {i}")
        expected = chain_of(prev, entry)
        if entry.get("chain") != expected:
            problems.append(f"line {i}: hash chain broken, the log was edited in place")
            prev = entry.get("chain", "")
            continue
        prev = entry["chain"]
    return problems


def codes_by_stage(entries: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {stage: set() for stage in STAGES}
    for entry in entries:
        if entry.get("type") != "code":
            continue
        stage = entry.get("stage", "both")
        for target in STAGES if stage == "both" else [stage]:
            out.setdefault(target, set()).add(str(entry.get("code")))
    return out


def validate(entries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Return the flow counts and the list of problems that block rendering."""
    problems = check_chain(entries)
    codes = codes_by_stage(entries)

    identified: Counter[str] = Counter()
    per_source: list[dict[str, Any]] = []
    duplicates = 0
    seen: dict[str, set[str]] = {stage: set() for stage in STAGES}
    decisions: dict[str, dict[str, list[dict[str, Any]]]] = {
        stage: {"include": [], "exclude": []} for stage in STAGES
    }
    retrieval: dict[str, list[str]] = {"retrieved": [], "not-retrieved": []}
    has_protocol = False

    for entry in entries:
        kind = entry.get("type")
        line = entry.get("seq", "?")
        if kind == "protocol":
            has_protocol = True
        elif kind == "code":
            if entry.get("stage") not in CODE_STAGES:
                problems.append(
                    f"line {line}: code stage {entry.get('stage')!r} is not one of {CODE_STAGES}"
                )
        elif kind == "search":
            hits = entry.get("hits")
            if not isinstance(hits, int) or hits < 0:
                problems.append(f"line {line}: search hits {hits!r} is not a count")
                hits = 0
            source_kind = entry.get("source_kind", "database")
            if source_kind not in SOURCE_KINDS:
                problems.append(
                    f"line {line}: source_kind {source_kind!r} is not one of {SOURCE_KINDS}"
                )
            if not entry.get("query") and source_kind in ("database", "register"):
                problems.append(f"line {line}: a database search with no query string")
            if not entry.get("date"):
                problems.append(
                    f"line {line}: search has no date, so the review cannot report a search date"
                )
            identified[source_kind] += hits
            per_source.append(
                {
                    "date": entry.get("date"),
                    "source_kind": source_kind,
                    "database": entry.get("database"),
                    "query": entry.get("query"),
                    "filters": entry.get("filters"),
                    "hits": hits,
                }
            )
        elif kind == "dedup":
            removed = entry.get("removed")
            if not isinstance(removed, int) or removed < 0:
                problems.append(f"line {line}: dedup removed {removed!r} is not a count")
            else:
                duplicates += removed
        elif kind == "screen":
            stage = entry.get("stage")
            decision = entry.get("decision")
            record = norm_record(str(entry.get("record", "")))
            if stage not in STAGES:
                problems.append(f"line {line}: screening stage {stage!r} is not one of {STAGES}")
                continue
            if decision not in DECISIONS:
                problems.append(f"line {line}: decision {decision!r} is not one of {DECISIONS}")
                continue
            if not record:
                problems.append(f"line {line}: screening decision without a record identifier")
                continue
            if record in seen[stage]:
                problems.append(f"line {line}: record {record} screened twice at {stage}")
                continue
            seen[stage].add(record)
            if decision == "exclude":
                reason = entry.get("reason")
                if not reason:
                    problems.append(
                        f"line {line}: exclusion of {record} at {stage} has no reason code"
                    )
                elif str(reason) not in codes[stage]:
                    problems.append(
                        f"line {line}: reason code {reason!r} was never declared for {stage}"
                        " (declare it with add-code)"
                    )
            decisions[stage][decision].append({"record": record, "reason": entry.get("reason")})
        elif kind == "retrieval":
            status = entry.get("status")
            record = norm_record(str(entry.get("record", "")))
            if status not in RETRIEVAL:
                problems.append(
                    f"line {line}: retrieval status {status!r} is not one of {RETRIEVAL}"
                )
                continue
            if not record:
                problems.append(f"line {line}: retrieval entry without a record identifier")
                continue
            if status == "not-retrieved" and not entry.get("reason"):
                problems.append(f"line {line}: {record} not retrieved and no reason given")
            retrieval[status].append(record)
        else:
            problems.append(f"line {line}: unknown entry type {kind!r}")

    total_identified = sum(identified.values())
    after_dedup = total_identified - duplicates
    screened = len(seen["title-abstract"])
    ta_included = [d["record"] for d in decisions["title-abstract"]["include"]]
    ta_excluded = decisions["title-abstract"]["exclude"]
    sought = len(ta_included)
    not_retrieved = len(retrieval["not-retrieved"])
    assessed = len(seen["full-text"])
    ft_excluded = decisions["full-text"]["exclude"]
    ft_included = [d["record"] for d in decisions["full-text"]["include"]]

    if after_dedup < 0:
        problems.append(
            f"duplicates removed ({duplicates}) exceeds records identified ({total_identified})"
        )
    if screened != after_dedup:
        problems.append(
            f"records screened ({screened}) does not equal records after duplicates removed"
            f" ({after_dedup} = {total_identified} identified - {duplicates} duplicates)"
        )
    if assessed != sought - not_retrieved:
        problems.append(
            f"reports assessed for eligibility ({assessed}) does not equal reports sought"
            f" ({sought}) minus not retrieved ({not_retrieved})"
        )
    unknown_retrieval = sorted(
        set(retrieval["retrieved"] + retrieval["not-retrieved"]) - set(ta_included)
    )
    if unknown_retrieval:
        problems.append(
            "retrieval recorded for records that were never included at title-abstract: "
            + ", ".join(unknown_retrieval)
        )
    not_sought = sorted(set(seen["full-text"]) - set(ta_included))
    if not_sought:
        problems.append(
            "assessed at full text without being included at title-abstract: "
            + ", ".join(not_sought)
        )
    dropped = sorted(set(retrieval["not-retrieved"]) & set(seen["full-text"]))
    if dropped:
        problems.append("recorded as not retrieved and still assessed: " + ", ".join(dropped))
    if not entries:
        problems.append("the log is empty")
    if not has_protocol:
        problems.append("no protocol entry: run init before the first search")
    if total_identified and not screened:
        problems.append("records were identified but none were screened")

    flow = {
        "identified": {kind: identified.get(kind, 0) for kind in SOURCE_KINDS},
        "identified_total": total_identified,
        "duplicates_removed": duplicates,
        "records_after_duplicates": after_dedup,
        "records_screened": screened,
        "records_excluded_title_abstract": len(ta_excluded),
        "excluded_title_abstract_by_reason": dict(Counter(str(d["reason"]) for d in ta_excluded)),
        "reports_sought": sought,
        "reports_not_retrieved": not_retrieved,
        "reports_assessed": assessed,
        "reports_excluded_full_text": len(ft_excluded),
        "excluded_full_text_by_reason": dict(Counter(str(d["reason"]) for d in ft_excluded)),
        "studies_included": len(ft_included),
        "included_records": sorted(ft_included),
        "searches": per_source,
        "search_dates": sorted({str(s["date"]) for s in per_source if s["date"]}),
        "reason_codes": {stage: sorted(codes[stage]) for stage in STAGES},
    }
    return flow, problems


def describe_codes(entries: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(e.get("code")): str(e.get("description", ""))
        for e in entries
        if e.get("type") == "code"
    }


def render_flow(flow: dict[str, Any], code_text: dict[str, str]) -> str:
    lines = ["# Search and screening flow", ""]
    dates = flow["search_dates"]
    lines.append(f"Search dates: {', '.join(dates) if dates else 'none recorded'}")
    lines.append(f"Last search: {dates[-1] if dates else 'none recorded'}")
    lines.append("")
    lines.append("## Identification")
    for kind in SOURCE_KINDS:
        lines.append(f"- {kind}: {flow['identified'][kind]}")
    lines.append(f"- records identified in total: {flow['identified_total']}")
    lines.append(f"- duplicates removed before screening: {flow['duplicates_removed']}")
    lines.append("")
    lines.append("## Screening")
    lines.append(f"- records screened on title and abstract: {flow['records_screened']}")
    lines.append(f"- records excluded: {flow['records_excluded_title_abstract']}")
    for code, count in sorted(flow["excluded_title_abstract_by_reason"].items()):
        lines.append(f"  - {code} {code_text.get(code, '')}: {count}")
    lines.append(f"- reports sought for retrieval: {flow['reports_sought']}")
    lines.append(f"- reports not retrieved: {flow['reports_not_retrieved']}")
    lines.append("")
    lines.append("## Eligibility")
    lines.append(f"- reports assessed for eligibility: {flow['reports_assessed']}")
    lines.append(f"- reports excluded: {flow['reports_excluded_full_text']}")
    for code, count in sorted(flow["excluded_full_text_by_reason"].items()):
        lines.append(f"  - {code} {code_text.get(code, '')}: {count}")
    lines.append("")
    lines.append("## Included")
    lines.append(f"- studies included in the review: {flow['studies_included']}")
    for record in flow["included_records"]:
        lines.append(f"  - {record}")
    lines.append("")
    lines.append("## Searches as run")
    lines.append("")
    lines.append("| date | source | database | query | filters | hits |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for search in flow["searches"]:
        query = str(search["query"] or "").replace("|", "\\|")
        lines.append(
            f"| {search['date']} | {search['source_kind']} | {search['database']} |"
            f" `{query}` | {search['filters'] or ''} | {search['hits']} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.log)
    if read_log(path):
        raise LogError(
            f"{path} already has entries; a search log is append-only, never re-initialized"
        )
    append(
        path,
        {
            "type": "protocol",
            "date": args.date or today(),
            "question": args.question,
            "review_type": args.review_type,
            "protocol_path": args.protocol,
        },
        args.apply,
    )
    if not args.no_default_codes:
        for code, stage, description in DEFAULT_CODES:
            append(
                path,
                {
                    "type": "code",
                    "date": args.date or today(),
                    "code": code,
                    "stage": stage,
                    "description": description,
                },
                args.apply,
            )
    print(f"initialized {path} for a {args.review_type} review")
    return 0


def cmd_add_code(args: argparse.Namespace) -> int:
    path = Path(args.log)
    existing = describe_codes(read_log(path))
    if args.code in existing:
        raise LogError(f"reason code {args.code!r} is already declared: {existing[args.code]!r}")
    append(
        path,
        {
            "type": "code",
            "date": args.date or today(),
            "code": args.code,
            "stage": args.stage,
            "description": args.description,
        },
        args.apply,
    )
    print(f"declared {args.code} for {args.stage}")
    return 0


def cmd_add_search(args: argparse.Namespace) -> int:
    if args.source_kind in ("database", "register") and not args.query:
        raise LogError("a database search needs the exact query string (--query)")
    append(
        Path(args.log),
        {
            "type": "search",
            "date": args.date or today(),
            "source_kind": args.source_kind,
            "database": args.database,
            "interface": args.interface,
            "query": args.query,
            "filters": args.filters,
            "hits": args.hits,
            "note": args.note,
        },
        args.apply,
    )
    print(f"logged {args.hits} hits from {args.database}")
    return 0


def cmd_add_dedup(args: argparse.Namespace) -> int:
    append(
        Path(args.log),
        {
            "type": "dedup",
            "date": args.date or today(),
            "removed": args.removed,
            "tool": args.tool,
            "note": args.note,
        },
        args.apply,
    )
    print(f"logged {args.removed} duplicates removed")
    return 0


def cmd_add_screen(args: argparse.Namespace) -> int:
    path = Path(args.log)
    entries = read_log(path)
    if args.decision == "exclude":
        if not args.reason:
            raise LogError(
                "an exclusion needs a reason code (--reason); declare codes with add-code"
            )
        if args.reason not in codes_by_stage(entries)[args.stage]:
            raise LogError(
                f"reason code {args.reason!r} is not declared for {args.stage};"
                " declare it with add-code before using it"
            )
    if args.decision == "include" and args.reason:
        raise LogError("an inclusion carries no reason code; put anything worth saying in --note")
    record = norm_record(args.record)
    for entry in entries:
        if (
            entry.get("type") == "screen"
            and entry.get("stage") == args.stage
            and norm_record(str(entry.get("record", ""))) == record
        ):
            raise LogError(
                f"{record} already has a {args.stage} decision at line {entry.get('seq')}"
            )
    append(
        path,
        {
            "type": "screen",
            "date": args.date or today(),
            "stage": args.stage,
            "record": record,
            "decision": args.decision,
            "reason": args.reason,
            "screener": args.screener,
            "note": args.note,
        },
        args.apply,
    )
    print(f"{args.decision} {record} at {args.stage}")
    return 0


def cmd_add_retrieval(args: argparse.Namespace) -> int:
    if args.status == "not-retrieved" and not args.reason:
        raise LogError("a report that could not be retrieved needs a reason (--reason)")
    append(
        Path(args.log),
        {
            "type": "retrieval",
            "date": args.date or today(),
            "record": norm_record(args.record),
            "status": args.status,
            "reason": args.reason,
        },
        args.apply,
    )
    print(f"{args.status}: {norm_record(args.record)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    entries = read_log(Path(args.log))
    flow, problems = validate(entries)
    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems, "flow": flow}, indent=2))
    else:
        if problems:
            print("the log does not reconcile:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(
                f"log is consistent: {len(entries)} entries,"
                f" {flow['studies_included']} studies included"
            )
    return 2 if problems else 0


def cmd_flow(args: argparse.Namespace) -> int:
    path = Path(args.log)
    entries = read_log(path)
    flow, problems = validate(entries)
    if problems:
        print("refusing to render the flow counts:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("fix the log with further entries, never by editing it.", file=sys.stderr)
        return 2
    if args.json:
        text = json.dumps(flow, indent=2)
    else:
        text = render_flow(flow, describe_codes(entries))
    if not args.out:
        print(text)
        return 0
    out = Path(args.out)
    if not inside_repo(out) and not args.apply:
        print(f"[dry-run] would write {out} (outside {REPO_ROOT}); rerun with --apply")
        print(text)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search_log.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--log", required=True, help="path to the JSONL search log")
        p.add_argument("--date", help="ISO date of the event (default: today)")
        p.add_argument(
            "--apply",
            action="store_true",
            help="write even when the log is outside the borg-cube checkout",
        )

    p_init = sub.add_parser(
        "init", help="start a log with the protocol and the default reason codes"
    )
    common(p_init)
    p_init.add_argument(
        "--question", required=True, help="the review question as written in the protocol"
    )
    p_init.add_argument(
        "--review-type",
        required=True,
        help="narrative, scoping, systematized, systematic, rapid, umbrella"
        " (Grant and Booth typology)",
    )
    p_init.add_argument("--protocol", help="path to the protocol file")
    p_init.add_argument(
        "--no-default-codes", action="store_true", help="declare every reason code by hand"
    )
    p_init.set_defaults(func=cmd_init)

    p_code = sub.add_parser("add-code", help="declare an exclusion reason code")
    common(p_code)
    p_code.add_argument("--code", required=True)
    p_code.add_argument("--stage", required=True, choices=CODE_STAGES)
    p_code.add_argument("--description", required=True)
    p_code.set_defaults(func=cmd_add_code)

    p_search = sub.add_parser("add-search", help="log one search exactly as it was run")
    common(p_search)
    p_search.add_argument("--database", required=True, help="PubMed, Scopus, DBLP, Paperclip, ...")
    p_search.add_argument("--interface", help="web, API, OVID, ...")
    p_search.add_argument("--query", help="the exact query string")
    p_search.add_argument("--filters", help="date, language and type limits as applied")
    p_search.add_argument("--hits", type=int, required=True)
    p_search.add_argument("--source-kind", default="database", choices=SOURCE_KINDS)
    p_search.add_argument("--note")
    p_search.set_defaults(func=cmd_add_search)

    p_dedup = sub.add_parser("add-dedup", help="log a deduplication step")
    common(p_dedup)
    p_dedup.add_argument("--removed", type=int, required=True)
    p_dedup.add_argument("--tool", help="the reference manager or script used")
    p_dedup.add_argument("--note")
    p_dedup.set_defaults(func=cmd_add_dedup)

    p_screen = sub.add_parser("add-screen", help="log one screening decision")
    common(p_screen)
    p_screen.add_argument("--stage", required=True, choices=STAGES)
    p_screen.add_argument("--record", required=True, help="DOI, PMID or arXiv id of the record")
    p_screen.add_argument("--decision", required=True, choices=DECISIONS)
    p_screen.add_argument("--reason", help="declared reason code, required for an exclusion")
    p_screen.add_argument("--screener", help="who made the decision")
    p_screen.add_argument("--note")
    p_screen.set_defaults(func=cmd_add_screen)

    p_ret = sub.add_parser("add-retrieval", help="log whether a full text could be obtained")
    common(p_ret)
    p_ret.add_argument("--record", required=True)
    p_ret.add_argument("--status", required=True, choices=RETRIEVAL)
    p_ret.add_argument("--reason", help="why the report could not be retrieved")
    p_ret.set_defaults(func=cmd_add_retrieval)

    p_val = sub.add_parser(
        "validate", help="check the hash chain, the reason codes and the arithmetic"
    )
    p_val.add_argument("--log", required=True)
    p_val.add_argument("--json", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_flow = sub.add_parser("flow", help="render the PRISMA-style flow counts")
    p_flow.add_argument("--log", required=True)
    p_flow.add_argument("--json", action="store_true")
    p_flow.add_argument("--out", help="write the rendered flow to this path")
    p_flow.add_argument("--apply", action="store_true", help="write even outside the checkout")
    p_flow.set_defaults(func=cmd_flow)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except LogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
