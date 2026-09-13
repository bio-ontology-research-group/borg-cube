"""Infra-hygiene patrol (daily 04:00): the sysadmin role's deterministic checks.

Sources, in order of preference: hermes-infra's ``status.json`` on this host (service
states with ``fails`` counts), else the ``services.yaml`` registry to list what should be
checked. Local probes: certificate expiry of registered https services (``openssl
s_client``), disk usage, tunnel liveness (``ss``/``ps``), pending apt upgrades, SLURM node
health (``sinfo``) and the vLLM endpoint (``VLLM_BASE_URL/v1/models``). Every probe is
injectable; failures become ``kind:incident`` beads, softer signals ``kind:finding``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from cube.beads import Beads
from cube.config import Settings
from cube.model import BeadHeader, WorkKind
from cube.patrols.base import Finding, PatrolReport, attention_event, prov, register
from cube.patrols.infra import DOWN, OK, WARN, incident_bead, warning_bead
from cube.runners.base import Exec, default_exec
from cube.sync.derivers import DesiredBead

HttpGet = Callable[[str, float], tuple[int, str]]
DiskUsage = Callable[[str], tuple[int, int]]  # (total, used) bytes

CERT_CRITICAL_DAYS = 14
CERT_WARN_DAYS = 30
DISK_WARN_PERCENT = 85
DISK_CRITICAL_PERCENT = 90
STATUS_STALE_MINUTES = 15  # infra-check runs every 5 min; stale_factor 2 plus slack
BAD_SLURM_STATES = ("down", "drain", "drng", "fail", "unk")
RE_NOT_AFTER = re.compile(r"notAfter=(.+)")


def default_http_get(url: str, timeout: float) -> tuple[int, str]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed hosts
            return int(resp.status), resp.read().decode("utf-8", errors="replace")[:4000]
    except urllib.error.HTTPError as exc:
        return int(exc.code), ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, str(exc)


def default_disk_usage(path: str) -> tuple[int, int]:
    du = shutil.disk_usage(path)
    return du.total, du.used


def cert_days_left(url: str, exec_fn: Exec, now: datetime, timeout: float = 15.0) -> int | None:
    """Days until the TLS certificate of ``url`` expires, via ``openssl s_client``."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or 443
    script = (
        f"echo | openssl s_client -servername {shlex.quote(host)} "
        f"-connect {shlex.quote(host)}:{port} 2>/dev/null | openssl x509 -noout -enddate"
    )
    res = exec_fn(["bash", "-c", script], cwd=Path.cwd(), env=dict(os.environ), timeout=timeout)
    m = RE_NOT_AFTER.search(res.stdout or "")
    if res.returncode != 0 or not m:
        return None
    try:
        expires = datetime.strptime(m[1].strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (expires - now).days


@dataclass
class Probes:
    exec_fn: Exec = default_exec
    which: Callable[[str], str | None] = shutil.which
    disk_usage: DiskUsage = default_disk_usage
    http_get: HttpGet = default_http_get
    hostname: str = field(default_factory=socket.gethostname)
    now: datetime | None = None
    check_certs: bool = True
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    def run(self, cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
        res = self.exec_fn(cmd, cwd=Path.cwd(), env=self.env, timeout=timeout, stdin_devnull=True)
        return res.returncode, res.stdout or "", res.stderr or ""


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def registry_services(reg: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (reg.get("services") or []) if isinstance(s, dict) and s.get("name")]


def _string_or_none(value: object) -> str | None:
    return None if not value else str(value)


@dataclass
class InfraHygienePatrol:
    name: str = "infra_hygiene"
    probes: Probes = field(default_factory=Probes)
    disk_paths: tuple[str, ...] = ("/", "~")

    # -- sources ------------------------------------------------------------------------

    def status_checks(
        self, status_path: Path, today: date, now: datetime, report: PatrolReport
    ) -> None:
        try:
            state = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.warnings.append(f"unreadable {status_path}: {exc}")
            return
        services = state.get("services") if isinstance(state, dict) else None
        if not isinstance(services, dict):
            report.warnings.append(f"{status_path} has no services map")
            return
        last_check = str(state.get("last_check") or "")
        age_min: float | None = None
        try:
            checked = datetime.fromisoformat(last_check)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=now.tzinfo or UTC)
            age_min = (now - checked).total_seconds() / 60
        except ValueError:
            pass
        src = str(status_path)
        stale_xid = "finding:infra:monitor-stale"
        stale_header = BeadHeader(
            xid=stale_xid,
            provenance=[prov(src, f"last_check {last_check}", today)],
        )
        if age_min is None or age_min > STATUS_STALE_MINUTES:
            report.findings.append(
                DesiredBead(
                    xid=stale_xid,
                    title=f"hermes-infra monitor stale: last check {last_check or 'unknown'}",
                    kind=WorkKind.finding,
                    labels=["src:hermes-infra", "service:infra-check", "needs:robert"],
                    header=stale_header,
                    body=(
                        f"status.json last_check {last_check or 'missing'}"
                        + (f" ({age_min:.0f} min ago)" if age_min is not None else "")
                        + "; the infra-check cron runs every 5 min. Check "
                        "`systemctl --user status hermes-gateway` and hermes cron on ws."
                    ),
                    priority=2,
                )
            )
        else:
            report.findings.append(
                DesiredBead(
                    xid=stale_xid,
                    title="hermes-infra monitor stale",
                    kind=WorkKind.finding,
                    labels=["src:hermes-infra", "service:infra-check"],
                    header=stale_header,
                    closed=True,
                    close_reason=f"last check {age_min:.0f} min ago",
                )
            )
        counts = {OK: 0, WARN: 0, DOWN: 0}
        for name, svc in sorted(services.items()):
            if not isinstance(svc, dict):
                continue
            status = str(svc.get("status") or "").upper()
            locator = f"services.{name}"
            msg = str(svc.get("msg") or "")
            group = _string_or_none(svc.get("group"))
            scope = _string_or_none(svc.get("scope"))
            severity = _string_or_none(svc.get("severity"))
            since = _string_or_none(svc.get("since"))
            url = _string_or_none(svc.get("url"))
            if status == DOWN and int(svc.get("fails") or 0) >= 2:
                counts[DOWN] += 1
                bead = incident_bead(
                    str(name),
                    today=today,
                    source=src,
                    locator=locator,
                    msg=msg,
                    since=since,
                    url=url,
                    description=str(svc.get("description") or ""),
                    group=group,
                    scope=scope,
                    severity=severity,
                    extra_body=[f"Consecutive failures: {svc.get('fails')}"],
                )
                report.findings.append(bead)
                report.events.append(
                    attention_event(
                        self.name,
                        f"DOWN: {name} since {since}: {msg[:100]}",
                        body=bead.body,
                        xid=bead.xid,
                        data={"service": name, "scope": svc.get("scope")},
                    )
                )
            elif status == WARN:
                counts[WARN] += 1
                report.findings.append(
                    incident_bead(
                        str(name),
                        today=today,
                        source=src,
                        locator=locator,
                        msg=msg,
                        group=group,
                        scope=scope,
                        severity=severity,
                        closed=True,
                        close_reason="state WARN",
                    )
                )
                report.findings.append(
                    warning_bead(
                        str(name),
                        today=today,
                        source=src,
                        locator=locator,
                        msg=msg,
                        group=group,
                        scope=scope,
                        severity=severity,
                    )
                )
            elif status == OK:
                counts[OK] += 1
                report.findings.append(
                    incident_bead(
                        str(name),
                        today=today,
                        source=src,
                        locator=locator,
                        msg=msg,
                        group=group,
                        scope=scope,
                        severity=severity,
                        closed=True,
                        close_reason="state OK",
                    )
                )
                report.findings.append(
                    warning_bead(
                        str(name),
                        today=today,
                        source=src,
                        locator=locator,
                        msg=msg,
                        group=group,
                        scope=scope,
                        severity=severity,
                        closed=True,
                        close_reason="state OK",
                    )
                )
        report.data["status"] = {"last_check": last_check, "age_min": age_min, "counts": counts}

    def cert_checks(
        self, services: list[dict[str, Any]], today: date, now: datetime, report: PatrolReport
    ) -> None:
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for svc in services:
            url = str(svc.get("url") or "")
            if not url.startswith("https://") or not svc.get("enabled", True):
                continue
            host = urlparse(url).hostname or ""
            if not host or host in seen:
                continue
            seen.add(host)
            days = cert_days_left(url, self.probes.exec_fn, now)
            results.append({"host": host, "days": days})
            xid_name = f"cert-{host}"
            scope = _string_or_none(svc.get("scope"))
            severity = _string_or_none(svc.get("severity"))
            if days is None:
                report.findings.append(
                    Finding(f"cert:{host}", f"certificate check failed for {host}", "info")
                )
                continue
            if days < CERT_CRITICAL_DAYS:
                bead = warning_bead(
                    xid_name,
                    msg=f"certificate expires in {days} day(s)",
                    title=f"Certificate for {host} expires in {days} day(s)",
                    priority=1,
                    needs_robert_label=True,
                    extra_body=[f"Registered service: {svc.get('name')} ({url})"],
                    today=today,
                    source="openssl s_client",
                    locator=f"{host}:443 notAfter",
                    scope=scope,
                    severity=severity,
                )
                report.findings.append(bead)
                report.events.append(
                    attention_event(self.name, bead.title, body=bead.body, xid=bead.xid)
                )
            elif days < CERT_WARN_DAYS:
                report.findings.append(
                    warning_bead(
                        xid_name,
                        msg=f"certificate expires in {days} day(s)",
                        title=f"Certificate for {host} expires in {days} day(s)",
                        priority=2,
                        today=today,
                        source="openssl s_client",
                        locator=f"{host}:443 notAfter",
                        scope=scope,
                        severity=severity,
                    )
                )
            else:
                report.findings.append(
                    warning_bead(
                        xid_name,
                        today=today,
                        source="openssl s_client",
                        locator=f"{host}:443 notAfter",
                        scope=scope,
                        severity=severity,
                        closed=True,
                        close_reason=f"{days} days left",
                    )
                )
        report.data["certs"] = results

    # -- local probes -------------------------------------------------------------------

    def disk_checks(self, today: date, report: PatrolReport) -> None:
        host = self.probes.hostname
        results: list[dict[str, Any]] = []
        for raw in self.disk_paths:
            path = os.path.expanduser(raw)
            try:
                total, used = self.probes.disk_usage(path)
            except OSError as exc:
                report.warnings.append(f"disk usage {path}: {exc}")
                continue
            pct = round(100 * used / total, 1) if total else 0.0
            results.append({"path": path, "percent": pct})
            name = f"disk-{host}-{path.strip('/').replace('/', '-') or 'root'}"
            source = f"shutil.disk_usage on {host}"
            msg = f"{pct}% used"
            severity = "critical" if pct >= DISK_CRITICAL_PERCENT else "normal"
            if pct >= DISK_CRITICAL_PERCENT:
                bead = incident_bead(
                    name,
                    today=today,
                    source=source,
                    locator=path,
                    msg=msg,
                    severity=severity,
                    host=host,
                    description=f"disk {path} on {host}",
                    extra_body=[f"Threshold: {DISK_CRITICAL_PERCENT}% (incident)"],
                )
                report.findings.append(bead)
                report.events.append(
                    attention_event(self.name, f"disk {path} on {host} at {pct}%", xid=bead.xid)
                )
            else:
                report.findings.append(
                    incident_bead(
                        name,
                        today=today,
                        source=source,
                        locator=path,
                        msg=msg,
                        severity=severity,
                        host=host,
                        closed=True,
                        close_reason=f"{pct}% used",
                    )
                )
                if pct >= DISK_WARN_PERCENT:
                    report.findings.append(
                        warning_bead(
                            name,
                            title=f"Disk {path} on {host} at {pct}%",
                            priority=2,
                            today=today,
                            source=source,
                            locator=path,
                            msg=msg,
                            severity=severity,
                        )
                    )
                else:
                    report.findings.append(
                        warning_bead(
                            name,
                            today=today,
                            source=source,
                            locator=path,
                            msg=msg,
                            severity=severity,
                            closed=True,
                            close_reason=f"{pct}% used",
                        )
                    )
        report.data["disks"] = results

    def tunnel_checks(
        self, services: list[dict[str, Any]], today: date, report: PatrolReport
    ) -> None:
        host = self.probes.hostname
        listening: set[int] = set()
        if self.probes.which("ss"):
            rc, out, _ = self.probes.run(["ss", "-tln"])
            if rc == 0:
                for line in out.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        m = re.search(r":(\d+)$", parts[3])
                        if m:
                            listening.add(int(m[1]))
        tunnels = 0
        if self.probes.which("ps"):
            rc, out, _ = self.probes.run(["ps", "-eo", "args"])
            if rc == 0:
                tunnels = sum(
                    1
                    for line in out.splitlines()
                    if line.startswith("ssh") and re.search(r"\s-(N|L|R|D)\b", line)
                )
        report.data["listening_ports"] = sorted(listening)
        report.data["ssh_tunnels"] = tunnels
        for svc in services:
            if svc.get("type") != "listen" or svc.get("ssh") not in ("local", host):
                continue
            ports = [int(p) for p in (svc.get("ports") or []) if str(p).isdigit()]
            missing = [p for p in ports if p not in listening]
            name = str(svc["name"])
            source = f"ss -tln on {host}"
            locator = f"ports {ports}"
            msg = f"missing ports {missing}" if missing else "all ports listening"
            scope = _string_or_none(svc.get("scope"))
            severity = _string_or_none(svc.get("severity"))
            if missing:
                bead = incident_bead(
                    name,
                    today=today,
                    source=source,
                    locator=locator,
                    msg=msg,
                    scope=scope,
                    severity=severity,
                    host=host,
                    description=str(svc.get("description") or ""),
                )
                report.findings.append(bead)
                report.events.append(
                    attention_event(self.name, f"tunnel/listener {name}: {msg}", xid=bead.xid)
                )
            elif listening:
                report.findings.append(
                    incident_bead(
                        name,
                        today=today,
                        source=source,
                        locator=locator,
                        msg=msg,
                        scope=scope,
                        severity=severity,
                        host=host,
                        closed=True,
                        close_reason="ports listening",
                    )
                )
        report.findings.append(
            Finding("tunnels", f"{tunnels} ssh tunnel process(es) on {host}", "info")
        )

    def apt_checks(self, today: date, report: PatrolReport) -> None:
        if not self.probes.which("apt"):
            report.findings.append(Finding("apt", "apt not available; upgrade check skipped"))
            return
        rc, out, _ = self.probes.run(["apt", "list", "--upgradable"], timeout=120)
        if rc != 0:
            report.warnings.append("apt list --upgradable failed")
            return
        lines = [ln for ln in out.splitlines() if "/" in ln and not ln.startswith("Listing")]
        count = len(lines)
        security = sum(1 for ln in lines if "security" in ln.lower())
        host = self.probes.hostname
        report.data["apt_upgradable"] = {"count": count, "security": security}
        name = f"apt-{host}"
        source = f"apt list --upgradable on {host}"
        locator = f"{count} packages"
        msg = f"{count} upgradable package(s), {security} security"
        if count:
            report.findings.append(
                warning_bead(
                    name,
                    title=f"Pending upgrades on {host}: {count} package(s), {security} security",
                    priority=3,
                    extra_body=[
                        "Apply only on Robert's ask: `sudo apt upgrade` quoted back first.",
                        *lines[:15],
                    ],
                    today=today,
                    source=source,
                    locator=locator,
                    msg=msg,
                )
            )
        else:
            report.findings.append(
                warning_bead(
                    name,
                    today=today,
                    source=source,
                    locator=locator,
                    msg=msg,
                    closed=True,
                    close_reason="no pending upgrades",
                )
            )

    def slurm_checks(self, today: date, report: PatrolReport) -> None:
        if not self.probes.which("sinfo"):
            report.findings.append(Finding("slurm", "sinfo not available on this host; skipped"))
            return
        rc, out, err = self.probes.run(["sinfo", "-h", "-N", "-o", "%N %t %G"], timeout=60)
        if rc != 0:
            report.warnings.append(f"sinfo failed: {err.strip()[:120]}")
            return
        nodes: list[dict[str, str]] = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                nodes.append(
                    {
                        "node": parts[0],
                        "state": parts[1],
                        "gres": parts[2] if len(parts) > 2 else "",
                    }
                )
        report.data["slurm"] = nodes
        seen: set[str] = set()
        for n in nodes:
            if n["node"] in seen:
                continue
            seen.add(n["node"])
            bad = any(n["state"].lower().startswith(s) for s in BAD_SLURM_STATES)
            name = f"slurm-{n['node']}"
            locator = f"{n['node']} {n['state']}"
            msg = f"state {n['state']} gres {n['gres']}"
            severity = "critical" if n["node"] == "node005" else "normal"
            if bad:
                bead = incident_bead(
                    name,
                    today=today,
                    source="sinfo -N",
                    locator=locator,
                    msg=msg,
                    severity=severity,
                    host=n["node"],
                    description="SLURM node",
                )
                report.findings.append(bead)
                report.events.append(
                    attention_event(self.name, f"SLURM {n['node']} is {n['state']}", xid=bead.xid)
                )
            else:
                report.findings.append(
                    incident_bead(
                        name,
                        today=today,
                        source="sinfo -N",
                        locator=locator,
                        msg=msg,
                        severity=severity,
                        host=n["node"],
                        closed=True,
                        close_reason=f"state {n['state']}",
                    )
                )

    def vllm_checks(self, settings: Settings, today: date, report: PatrolReport) -> None:
        base = settings.env.get("VLLM_BASE_URL") or self.probes.env.get("VLLM_BASE_URL")
        if not base:
            report.findings.append(Finding("vllm", "VLLM_BASE_URL not set; endpoint check skipped"))
            return
        url = base.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/models"
        status, body = self.probes.http_get(url, 10.0)
        models: list[str] = []
        if status == 200:
            try:
                data = json.loads(body)
                models = [str(m.get("id")) for m in data.get("data", []) if isinstance(m, dict)]
            except (json.JSONDecodeError, AttributeError):
                models = []
        report.data["vllm"] = {"url": url, "status": status, "models": models}
        locator = f"HTTP {status}"
        msg = f"HTTP {status}" + (f": {body[:80]}" if status != 200 else "")
        if status == 200:
            report.findings.append(
                warning_bead(
                    "vllm-endpoint",
                    today=today,
                    source=url,
                    locator=locator,
                    msg=msg,
                    closed=True,
                    close_reason="serving",
                )
            )
            report.findings.append(
                Finding("vllm", f"vLLM serving {', '.join(models) or 'no models listed'}")
            )
        else:
            report.findings.append(
                warning_bead(
                    "vllm-endpoint",
                    title=f"vLLM endpoint unreachable ({url}: HTTP {status})",
                    priority=2,
                    extra_body=[
                        "The local tier is unavailable; privacy:local-only work queues until "
                        "vLLM on node005 is back (ADR-0011). Restart only on Robert's ask."
                    ],
                    today=today,
                    source=url,
                    locator=locator,
                    msg=msg,
                )
            )

    # -- entry point --------------------------------------------------------------------

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        now = self.probes.now or datetime.now(UTC)
        report = PatrolReport(self.name, today, dry_run)
        status_path = settings.dirs["hermes_home"] / "state" / "infra" / "status.json"
        registry_path = settings.dirs["infra"] / "hermes-infra" / "scripts" / "services.yaml"
        reg = load_registry(registry_path)
        services = registry_services(reg)
        report.data["registry"] = {
            "path": str(registry_path) if registry_path.exists() else None,
            "services": len(services),
        }
        if status_path.exists():
            self.status_checks(status_path, today, now, report)
        else:
            report.findings.append(
                Finding(
                    "infra-status:missing",
                    f"no hermes-infra status on this host ({status_path}); "
                    f"{len(services)} registered service(s) are checked by hermes-ws",
                    "info",
                    detail=", ".join(str(s["name"]) for s in services[:40]),
                    source=str(registry_path) if registry_path.exists() else None,
                )
            )
        if self.probes.check_certs and services:
            self.cert_checks(services, today, now, report)
        self.disk_checks(today, report)
        self.tunnel_checks(services, today, report)
        self.apt_checks(today, report)
        self.slurm_checks(today, report)
        self.vllm_checks(settings, today, report)
        incidents = [b for b in report.beads() if b.kind == WorkKind.incident and not b.closed]
        warnings_ = [b for b in report.beads() if b.kind == WorkKind.finding and not b.closed]
        report.summary = (
            f"{len(incidents)} incident(s), {len(warnings_)} warning(s) on {self.probes.hostname}"
            + (f"; hermes-infra status {'read' if status_path.exists() else 'absent'}")
        )
        return report


register(InfraHygienePatrol, "infra_hygiene")
