#!/usr/bin/env bash
# Hermes pre-prompt hook for the advisor profile (ADR-0003).
# Prints the per-student context that `cube student context --mm-user <u> --json` rendered on ws into
#   ~/.hermes/profiles/advisor/context/<mm-user>.json
# so memory about the student lives in cube/pa/org, never in Hermes. Prints nothing (and exits 0) when
# the user is unknown or has no grant, so the model gets no context and the allowlist stays the only gate.
# Hermes passes the platform user id in HERMES_USER_ID (verify the variable name against the pinned Hermes version).
set -euo pipefail
user="${HERMES_USER_ID:-${MATTERMOST_USER_ID:-}}"
[ -n "$user" ] || exit 0
case "$user" in *[!A-Za-z0-9_.@-]*) exit 0;; esac   # refuse path characters
ctx="${HERMES_HOME:-$HOME/.hermes/profiles/advisor}/context/${user}.json"
[ -r "$ctx" ] || exit 0
# Refuse stale context (older than 24 h): the weekly digest re-renders it; stale means cube is not running.
if [ -n "$(find "$ctx" -mmin +1440 2>/dev/null)" ]; then
  echo "[student context stale; tell the student you will summarise for Robert and answer only from what they say]"
  exit 0
fi
echo "[student context, rendered by cube; contains only the student's own milestone plan, check-in history and visible:student beads]"
cat "$ctx"
