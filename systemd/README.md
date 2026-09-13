# systemd user units for ws

Deterministic patrols, the worker loop and the Hermes gateways run as systemd
user units for `leechuck` on ws (ADR-0004). `loginctl enable-linger leechuck`
is already set (the `hermes-gateway` unit depends on it).

| Unit | What | Schedule |
|---|---|---|
| `cube-patrol@.service` | `cube patrol <name>` template, oneshot, no LLM | by timer |
| `cube-patrol-milestones.timer` | 180/90/30-day milestone warnings | daily 07:00 |
| `cube-patrol-papers.timer` | papers.org vs paper directories | daily 07:10 |
| `cube-patrol-deadlines.timer` | 7/30-day horizon | daily 07:20 |
| `cube-patrol-calendar.timer` | tomorrow's meetings to prep beads | daily 17:00 |
| `cube-patrol-student-digest.timer` | Robert-only student digests | Thu 12:00 |
| `cube-patrol-repos.timer` | GitHub org scan, audit candidates | Mon 06:00 |
| `cube-patrol-infra-hygiene.timer` | certs, disks, backups, tunnels, upgrades, SLURM, vLLM | daily 04:00 |
| `cube-patrol-data-pull.timer` | git pull of ~/org, ~/pa, KGs | hourly |
| `cube-patrol-leases.timer` | expire dead leases, requeue | every 15 min |
| `cube-patrol-pipeline.timer` | advance research pipeline stages | every 10 min |
| `cube-corpus-verify.timer` | verify corpus DOI metadata and notify on failure | monthly |
| `cube-worker@.service` | marshal loop, instance = slots (`cube-worker@3`) | always |
| `cube-worker-laptop.timer` | laptop liaison worker for `host:laptop` beads | every 5 min on `lc-dell` |
| `cube-gateway-concierge.service` | Hermes concierge gateway, Robert-only | always (Phase 1) |
| `cube-gateway-advisor.service` | Hermes advisor gateway `@borg-advisor` | always once a grant exists (Phase 4) |
| `cube-events-tail.service` | placeholder, not enabled | n/a |

Event-driven inputs (`mattermost-events`, `infra-incidents`) have no timer:
they arrive through the gateway and `cube event`.

The laptop installs `cube-worker-laptop.service` and
`cube-worker-laptop.timer` from the same checkout. `ConditionHost=lc-dell`
keeps these units inactive on ws. The worker uses Beads as shared state and
does not mount or copy laptop files to ws.

## Install

`just install-timers` runs `cube systemd install`, which renders these files
with the schedules from `cube.yaml` `patrols:` (the checked-in files are the
rendered defaults), copies them to `~/.config/systemd/user/`, runs
`systemctl --user daemon-reload`, and enables the timers plus
`cube-worker@3`. Gateways are enabled separately (`cube systemd enable
gateway-concierge`).

Manual equivalent:

```
install -m 644 systemd/*.service systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cube-patrol-{milestones,papers,deadlines,calendar,student-digest,repos,infra-hygiene,data-pull,leases,pipeline}.timer cube-corpus-verify.timer
systemctl --user enable --now cube-worker@3.service
```

## Operating

- `systemctl --user list-timers 'cube-*'` shows next runs.
- `journalctl --user -u cube-patrol@milestones --since today` shows a patrol's log.
- Kill switch: `cube kill` creates `state/KILL`; every unit has
  `ConditionPathExists=!.../state/KILL`, so timers fire but the service is
  skipped and gateways will not restart. `cube resume` removes the file.
  Running processes finish their step.
- `.env` is read through `EnvironmentFile=-`; Hermes profiles read their own
  `~/.hermes/profiles/<p>/.env`.
- The ws clock is Asia/Riyadh; `OnCalendar` values are local time, matching
  the Hermes cron timezone used by `hermes-ws`.
- `hermes-ws` and its `hermes-gateway` unit are not managed here.
