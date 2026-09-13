# ADR-0033: Model-free Mattermost goal intake

Status: accepted
Date: 2026-09-09
Source: Robert approved fixing the diagnosed silent Mattermost goal investigation.

Explicit `New goal:` messages in Robert's verified DM bypass the model loop via
a Hermes plugin. Persist the exact goal intent and its post-id provenance, queue
the coordinator, and acknowledge once. Use opaque one-use command tickets and
fixed subprocess argv; neither arbitrary senders nor a forged slash-command
payload can act as Robert. Do not fabricate a target date to satisfy GoalHeader.

Background intake work gets one goal-specific local coordinator turn, not the
general management context. Retry saved inbox work outside the chat. Normal chat
has an eight-iteration ceiling. The tradeoff is a narrow explicit trigger rather
than model-based classification of every message. This fits Robert's preference
for few messages and fast acknowledgment without repeated heartbeats.

See [implementation and evidence](../doc/mattermost-goal-intake.md).
