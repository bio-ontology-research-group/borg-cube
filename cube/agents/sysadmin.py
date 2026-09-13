"""The sysadmin agent's daily server review: facts from the infra patrol, proposals only.

Robert, 2026-09-05: "Sys-admin must go through servers each day and check,
propose optimizations where appropriate." The agent reads; it never restarts,
deletes or edits anything (doctrine: sysadmin actions only on Robert's explicit
ask). Its proposals are kind:proposal beads with the evidence lines below.

Robert, 2026-09-07: go through the infrastructure, update the servers, make
them more robust, read the logs. Reading, measuring and preparing are the
agent's own; every change to a running system is security-critical (doctrine
7a) and waits as one approval bead per host with the exact commands and the
rollback. Nothing else about the servers is Robert's decision.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cube.beads import Beads
from cube.config import Settings

SERVER_REVIEW_TITLE = "daily server review"


def server_facts(
    settings: Settings, beads: Beads | None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Run the deterministic infra hygiene checks in dry mode and collect their facts."""
    from cube.patrols import base  # noqa: PLC0415 - the patrol package imports this module
    from cube.patrols.infra_hygiene import InfraHygienePatrol  # noqa: PLC0415

    now = now or datetime.now(UTC)
    today = now.astimezone(UTC).date()
    report = base.run_patrol(
        settings, InfraHygienePatrol(), today=today, dry_run=True, beads=beads, now=now
    )
    findings = [
        {
            "key": item.key,
            "severity": item.severity,
            "title": item.title,
            "detail": item.detail,
            "source": item.source,
        }
        for item in report.notes()
    ]
    desired = [
        {"title": item.title, "labels": list(item.labels), "body": item.body[:400]}
        for item in report.beads()
    ]
    return {
        "date": today.isoformat(),
        "summary": report.summary,
        "findings": findings,
        "attention": desired,
        "warnings": list(report.warnings),
        "data": {
            key: value
            for key, value in report.data.items()
            if key in {"disks", "ssh_tunnels", "services", "nodes", "certs", "backups", "slurm"}
        },
    }


NIGHT_SCAN_LINES = 120


def night_scan(settings: Settings, limit: int = NIGHT_SCAN_LINES) -> str:
    """The Hermes monitor's night scan (security and log digest), when present on ws."""
    path = settings.paths.hermes_home.expanduser() / "state" / "infra" / "nightly_scan.txt"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    head = lines[:limit]
    if len(lines) > limit:
        head.append(f"... {len(lines) - limit} more line(s) in {path}")
    return "\n".join(head)


def infra_briefing_path(settings: Settings, day: date) -> Path:
    return settings.root / "briefings" / "infra" / f"{day.isoformat()}.md"


def write_infra_briefing(settings: Settings, report: Any, *, now: datetime | None = None) -> Path:
    """Write the review's outcome where hermes-ws's morning report reads it (ADR-0020)."""
    day = review_day(now)
    path = infra_briefing_path(settings, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = report.result if isinstance(getattr(report, "result", None), dict) else {}
    lines = [
        f"# Server review {day.isoformat()} (sysadmin, run {report.run_id})",
        "",
        str(result.get("summary") or report.message or "no summary").strip(),
    ]
    actions = [str(x) for x in (result.get("next_actions") or [])]
    if actions:
        lines += ["", "## Proposed next", *(f"- {x}" for x in actions)]
    escalations = result.get("escalations") or []
    if escalations:
        lines += ["", "## Escalations"]
        for esc in escalations:
            if isinstance(esc, dict):
                lines.append(f"- {esc.get('kind', 'note')}: {esc.get('condition', '')}")
    artifacts = [a.get("path") for a in (result.get("artifacts") or []) if isinstance(a, dict)]
    if artifacts:
        lines += ["", "## Artifacts", *(f"- {a}" for a in artifacts if a)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def server_review_context(
    settings: Settings, beads: Beads | None, *, now: datetime | None = None
) -> str:
    facts = server_facts(settings, beads, now=now)
    scan = night_scan(settings)
    lines = [
        f"# Daily server review {facts['date']}",
        "",
        "Charter: go through every server each day, check the logs, and prepare the",
        "upgrades and robustness fixes. You read and prepare; you never restart, delete,",
        "edit or install anything. Robert approves each change; a change to a running",
        "system is the one thing that waits for him.",
        "",
        f"## Infra hygiene patrol ({facts['summary']})",
    ]
    for item in facts["findings"]:
        src = f" (source: {item['source']})" if item.get("source") else ""
        detail = f": {item['detail']}" if item.get("detail") else ""
        lines.append(f"- [{item['severity']}] {item['title']}{detail}{src}")
    for item in facts["attention"]:
        lines.append(f"- [attention] {item['title']}")
    for warning in facts["warnings"]:
        lines.append(f"- [warning] {warning}")
    if not facts["findings"] and not facts["attention"] and not facts["warnings"]:
        lines.append("- no observations recorded; the patrol found nothing to report")
    if scan:
        lines += ["", "## Night scan (hermes-ws monitor, security and logs)", ""]
        lines += ["```", scan, "```"]
    if settings.fleet_enabled:
        lines += [
            "",
            "## Guarded fleet review",
            "Use only `cube boundary inspect <host> --check <check>`. Checks are",
            "uptime, disk, memory, services, journal and slurm. Check free bytes and",
            "inodes; use the central reserve floors. Do not execute shell or SSH yourself.",
            "Bundle related fixes per host with `cube boundary propose '<JSON>' --apply`.",
            "Include host, commands (argv lists), rationale, impact, prechecks, postchecks,",
            "rollback and evidence. Robert receives the exact bundle in his batched DM.",
            "Approval executes only that bundle. A modification requires a new approval.",
            "Return a source-backed inline report; do not write files or approval beads.",
            "Routine healthy checks stay in the ledger, not Robert's inbox.",
        ]
        return "\n".join(lines)
    lines += [
        "",
        "## Checks to run yourself (read-only)",
        "- ws: `uptime`, `df -h / ~`, `free -h`, `systemctl --user --failed`,",
        "  `journalctl --user -p err --since yesterday | tail -50`, largest directories",
        "  under runs/ and state/ (`du -sh runs/* state/* | sort -h | tail`).",
        "- every host you can reach (ws, unimatrix01, its nodes through unimatrix01,",
        "  borg-server): `uptime`, `df -h`, `free -h`, `systemctl --failed`,",
        "  `journalctl -p err --since yesterday | tail -40`, `journalctl -u ssh --since",
        "  yesterday | grep -ci 'failed password'`, `dmesg -T | tail -30`,",
        "  `apt list --upgradable 2>/dev/null | wc -l` and the security subset,",
        "  `last -n 20`, `docker ps` and `docker logs --since 24h <container> | tail -30`",
        "  where docker runs, backup ages under the paths the runbooks name.",
        "- node005: `ssh -o BatchMode=yes node005 'uptime; nvidia-smi --query-gpu="
        "name,utilization.gpu,memory.used,memory.total --format=csv; df -h /'`.",
        "- ibex: `sinfo -o '%P %a %D %t'` and `squeue -u $USER` when reachable.",
        "- borg-cube timers: `systemctl --user list-timers` for missed or failed runs.",
        "",
        "## What to do now",
        "1. Record one journal entry with the numbers you measured, each with its host and",
        "   command as source: load, disks, memory, failed units, error and auth log",
        "   counts, pending upgrades (security ones separately), GPU state, backup ages.",
        "2. Robustness. For every weakness you can see (a service without a restart",
        "   policy or a health check, an unmonitored disk, a timer that missed, a backup",
        "   older than its threshold, a log growing without rotation, an unpinned or",
        "   unattended dependency, a host without unattended security upgrades) prepare",
        "   the fix in full: the exact commands or the config diff, the evidence, the",
        "   expected gain, the rollback, and a kill criterion.",
        "3. Changes wait for Robert. Bundle every prepared change for one host into ONE",
        "   `kind:approval` bead per host and day with `cube create --kind approval",
        "   --title '<host>: <what>' --xid sysadmin:<host>:<topic> --provenance",
        "   '<host>:<command>::<line>' --acceptance '<what is true after the change>'",
        "   --apply`, then `bd comment <id>` with the commands quoted in order, security",
        "   upgrades first, and the rollback. A subject already open on the ledger gets",
        "   a comment, never a second bead. Never run those commands.",
        "4. Anything broken right now (service down, disk above 90 percent, certificate",
        "   under 14 days) you diagnose to the exact fixing command and file the same",
        "   way; it is not a question for Robert, it is an approval with the fix ready.",
        "5. Nothing to propose is a fine outcome; say so in the journal and stop.",
        "6. Your summary is the input of hermes-ws's daily ~infra-alerts report: at most",
        "   twelve lines, new or changed state first, what needs a human today, nothing",
        "   already reported on previous days.",
    ]
    return "\n".join(lines)


def review_day(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(UTC).date()
