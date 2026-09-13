---
name: <skill-name>
description: <What the skill does and when to use it. Include the phrases a user would say, in quotes. At most 1024 characters.>
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12; no network unless noted.
metadata:
  borg-role: <advisor|researcher|lecturer|auditor|lead|infra>
  grounding: <id>, <id>, <id>
  hermes:
    category: <advising|research|teaching|software|lead|infra|admin>
    tags: <tag>, <tag>
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# <Skill title in sentence case>

<One paragraph: what this skill produces and for whom.>

## When to use

- <Trigger situation.>

## Procedure

1. <Step with the command or file it touches.>
2. <Step.>

## Hard rules

- <Rule that lint or a script enforces, or that Robert set.>

## Grounding

- `references/<topic>.md`: <one line on what it covers>.

## Scripts

- `scripts/<name>.py --help`: <what it does; dry-run by default when it writes outside the repo>.
