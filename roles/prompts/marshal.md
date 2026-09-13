# Marshal

Not an LLM role by default. The Marshal is `cube worker --slots N`: it
claims ready beads within the slot limits in `cube.yaml`, dispatches the role
runner chosen by the router, writes leases, expires dead leases every 15
minutes and requeues, tracks budget windows, and raises a `needs:robert`
finding when the ready queue starves for over 48 hours. An optional cheap
model may order the queue when it exceeds the slots; it never changes what a
bead says.

Rules: never send a `privacy:local-only` bead to a cloud runner (queue when
local is down); never exceed slots or daily budgets; idempotent; never
contact anyone; stop when `state/KILL` exists.

## What to escalate

Escalation kinds: `decision` (scope, money or plan), `permission` (resources),
`integrity` (suspected fabrication), `people` (anything about a person),
`conflict` (sources), `blocked` (tooling or input; the group fixes it), `note`
(information). Robert decides only what is security-critical (a change to a
running system, spend over budget, contact) or privacy-critical (a person's
data, secrets, local-only data leaving the local tier): set `critical:
security|privacy` on that escalation. Everything else the coordinator settles;
decide what you can yourself. Never escalate "no work assigned"; idle is fine.
