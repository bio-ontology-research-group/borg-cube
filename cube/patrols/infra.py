"""Shared shapes for the sysadmin patrols: incident beads keyed by hermes-infra service name."""

from __future__ import annotations

from datetime import date

from cube.model import BeadHeader, Privacy, Provenance, WorkKind
from cube.sync.derivers import DesiredBead

OK, WARN, DOWN, UNKNOWN = "OK", "WARN", "DOWN", "UNKNOWN"


def incident_xid(service: str) -> str:
    return f"incident:{service}"


def finding_xid(service: str) -> str:
    return f"finding:infra:{service}"


def service_labels(
    name: str,
    *,
    group: str | None = None,
    scope: str | None = None,
    severity: str | None = None,
    host: str | None = None,
) -> list[str]:
    labels = [f"service:{name}", "src:hermes-infra"]
    if host:
        labels.append(f"host:{host}")
    elif name.startswith(("host-", "vm-")):
        labels.append(f"host:{name.split('-', 1)[1]}")
    if group:
        labels.append(f"group:{group}")
    if scope:
        labels.append(f"scope:{scope}")
    if severity:
        labels.append(f"severity:{severity}")
    return labels


def needs_robert(scope: str | None, severity: str | None) -> bool:
    return scope == "external" or severity == "critical"


def incident_bead(
    service: str,
    *,
    today: date,
    source: str,
    locator: str,
    msg: str = "",
    since: str | None = None,
    url: str | None = None,
    description: str = "",
    group: str | None = None,
    scope: str | None = None,
    severity: str | None = None,
    host: str | None = None,
    closed: bool = False,
    close_reason: str | None = None,
    extra_body: list[str] | None = None,
) -> DesiredBead:
    xid = incident_xid(service)
    labels = service_labels(service, group=group, scope=scope, severity=severity, host=host)
    if not closed and needs_robert(scope, severity):
        labels.append("needs:robert")
    body = [f"Service: {service}" + (f" ({description})" if description else "")]
    if url:
        body.append(f"Target: {url}")
    if since:
        body.append(f"Down since: {since}")
    if msg:
        body.append(f"Last message: {msg}")
    body.extend(extra_body or [])
    body.append(
        "Playbook: brain/playbooks/incident-response.md. Read-only diagnosis first; any "
        "restart, delete, scancel or config edit only on Robert's explicit ask, quoted back."
    )
    title = f"DOWN: {service}" + (f" ({scope})" if scope else "")
    return DesiredBead(
        xid=xid,
        title=title,
        kind=WorkKind.incident,
        labels=labels,
        header=BeadHeader(
            xid=xid,
            provenance=[Provenance(source=source, locator=locator, seen=today)],
            privacy=Privacy.internal,
        ),
        body="\n".join(body),
        priority=1 if severity == "critical" or scope == "external" else 2,
        closed=closed,
        close_reason=close_reason,
    )


def warning_bead(
    service: str,
    *,
    today: date,
    source: str,
    locator: str,
    msg: str = "",
    group: str | None = None,
    scope: str | None = None,
    severity: str | None = None,
    closed: bool = False,
    close_reason: str | None = None,
    title: str | None = None,
    priority: int = 3,
    needs_robert_label: bool = False,
    extra_body: list[str] | None = None,
) -> DesiredBead:
    xid = finding_xid(service)
    labels = service_labels(service, group=group, scope=scope, severity=severity)
    if needs_robert_label and not closed:
        labels.append("needs:robert")
    return DesiredBead(
        xid=xid,
        title=title or f"WARN: {service}: {msg[:80]}",
        kind=WorkKind.finding,
        labels=labels,
        header=BeadHeader(
            xid=xid, provenance=[Provenance(source=source, locator=locator, seen=today)]
        ),
        body="\n".join([f"Service: {service}", f"Message: {msg}", *(extra_body or [])]),
        priority=priority,
        closed=closed,
        close_reason=close_reason,
    )
