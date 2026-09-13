# Research explorer

The private browser explorer runs on ws. It reads existing telemetry, not model
prompts, and makes no model calls to produce statistics or summaries.

## Open it

```sh
ssh -N -L 8765:127.0.0.1:8765 ws
```

Open <http://127.0.0.1:8765>. Keep the SSH tunnel running. The service binds only
to IPv4 loopback: no public domain, firewall change, or unauthenticated LAN port.
SSH authenticates remote users. Local processes on ws can access the explorer,
so this design assumes a trusted workstation. Do not expose it through a public
reverse proxy without adding authentication. Writes require same-origin requests,
a session CSRF token and explicit confirmation. No general command endpoint exists.

## Explore and act

- Select a 1, 7 or 30 UTC-calendar-day window and filter agents by name, role or host.
- Fleet activity shows runs and token use over time. Select an agent for its scope,
  latest summary, source-backed run history, assigned tasks and memory files.
- Input, output and cache tokens are distinct. Recorded billed costs are separate
  from equivalent/estimated costs. Unknown API-call counts are not zero or runs.
- Mattermost gateway counters come from read-only numeric session fields only.
  They are lifetime counters for sessions active in the window, not daily API
  usage, and remain separate from workday totals.
- **Run this agent** starts one normal workday after confirmation. An optional
  instruction enters its inbox with Robert/explorer provenance. The existing
  workday lock, budgets, pause/kill switches and role approval boundaries apply.
  A successful workday can legitimately be idle when it has nothing eligible.
- Laptop agents are not started remotely: ws never connects back to the laptop.
  The Mattermost concierge is managed by its gateway, not by workday triggers.

Protected/local-only run details and liaison memory are withheld. Only fixed
agent memory filenames are exposed; there is no filesystem browser. Rendering
uses text, not executable HTML from research records. Credential screening is
pattern-based and does not replace the private-access boundary.

Refresh runs every 30 seconds while the page is visible. Server projections cache
for ten seconds. The explorer reads local cube state and does not poll Mattermost.
Run scans cap at 10,000 records and event scans use the newest 64 MB. Large or malformed records are skipped. Attribution
uses explicit metadata, historical workday events, then current bead labels;
unattributed runs still count toward fleet totals but are not guessed from roles.

## Service lifecycle

Install the versioned user unit only after the deployment is authorized:

```sh
install -m 644 systemd/cube-explorer.service ~/.config/systemd/user/cube-explorer.service
systemctl --user daemon-reload
systemctl --user enable --now cube-explorer.service
systemctl --user status cube-explorer.service
curl -fsS http://127.0.0.1:8765/healthz
```

Logs: `journalctl --user -u cube-explorer.service`. Stop/rollback the explorer with
`systemctl --user disable --now cube-explorer.service`. This does not revert cube
code or change other timers. Stop only when no explorer-triggered work is running:
the service owns those child processes and stopping it interrupts them.

For development, `uv run cube explorer --port 8765` previews the listener;
add `--apply` to start it. No model, job or external-message call belongs in a
smoke test. HTTP action tests inject fake workers.
