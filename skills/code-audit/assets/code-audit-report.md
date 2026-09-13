# Code audit: {{REPO_NAME}}

Repository: {{REPO_PATH}} ({{REMOTE}})
Collected: {{COLLECTED}} by audit_collect.py; report {{GENERATED}}
Last commit: {{LAST_COMMIT}} ({{DAYS_SINCE_COMMIT}} days ago); {{FILE_COUNT}} tracked files; languages {{LANGUAGES}}
Context flags: {{CONTEXT}}

## Summary
{{SUMMARY}}

## Findings

Each finding: severity, location (file:line or the evidence command), the problem, the fix, the sources it rests on (corpus ids).

### High
{{HIGH}}

### Medium
{{MEDIUM}}

### Low
{{LOW}}

### Info
{{INFO}}

## Checks that passed
{{PASSED}}

## Not checked
{{NOT_CHECKED}}

## Fix list
Proposed as beads (stage design, owner programmer unless stated); each has the acceptance criterion "the finding is no longer reported by audit_collect.py".
{{FIXES}}

## Judgement
{{JUDGEMENT}}
