# ADR-0029: Private fleet explorer

Status: accepted
Date: 2026-09-08
Source: Robert's request to visualize agent activity, statistics, work and memory,
trigger individual agents, and run the explorer on ws.

Use a dependency-free browser client and Python loopback HTTP server alongside
the existing CLI. Read run metadata and agent memories rather than creating a
second work database. Add explicit agent identity to new run metadata; recover
historical ownership from workday events when possible. Unknown telemetry stays
unknown. Gateway session counters are numeric-only and separate from workday runs.

Use SSH for private remote access, Host/Origin validation and CSRF checks for
actions. Local ws processes are trusted; internet/LAN exposure is not supported.
Serve a fixed static asset list, never arbitrary files. No cloud-generated summary
or Mattermost polling is introduced. Protected material is screened/withheld.

An explicit trigger launches the existing workday CLI, with no shell interpolation
or approval bypass. Existing workday locks prevent concurrent cycles of one agent.
Remote laptop workers and the independently managed concierge are not launched.
The user service owns child lifecycles and stops them with the service. No automatic
retry of a trigger or timed-out browser action: inspect workday status first.

The UI is a compact research console: searchable roster, activity timeline and
an agent detail pane with overview, runs and memory. The design skill guided the
cool blue/slate palette, information hierarchy and responsive keyboard-accessible
layout. See [the operator guide](../doc/explorer.md) for commands and limits.
