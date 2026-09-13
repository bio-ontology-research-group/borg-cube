# Note to students about borg-cube

This note is sent by Robert himself, never by the system, and only to a
student who has agreed to take part in the advisor pilot. It says what the
system does, what Robert sees, what is stored where, and how to stop.

## What it is

borg-cube is a set of software tools Robert uses to keep track of the group's
work: papers, software, courses, infrastructure, and the KAUST milestones each
student has to meet. Some of the tools use language models (the same kind of
models behind Claude or ChatGPT) to draft summaries and suggestions for
Robert. The tools do not make decisions about you. Robert does.

## What it does by default (without your agreement)

- Reads material Robert already has: the group's public knowledge graph and
  roster, his own meeting notes about your project, the papers and code
  repositories you share with him, and the KAUST milestone rules.
- Prepares, for Robert only, a weekly summary of visible progress (commits,
  drafts, notes), the dates of your upcoming milestones (qualifying exam,
  proposal, thesis application, defense), and suggested topics for your 1:1.
- Never contacts you. Nothing from the system reaches you unless Robert sends
  it himself.

## What changes if you agree to the pilot

- A Mattermost bot, `@borg-advisor`, will send you a short check-in once a
  week (Wednesday 10:00): what moved, what is blocked, what is next, plus one
  question about your next milestone. You answer as much or as little as you
  like, or not at all.
- The bot can answer questions about your own milestone plan and your own
  earlier check-ins. It cannot see other students, Robert's private notes, or
  any assessment, and it never gives you one.
- Your replies are processed only on a computer inside KAUST (the group's
  own GPU node), never by a cloud service.
- The bot tells you when it is going to summarise something for Robert. The
  summary is a draft that Robert reads; it says what you said, with a link to
  your message, and nothing the system inferred about you.
- If you mention a blocker or a concern, the system flags it for Robert so he
  can talk to you. It does not act on it itself.

## What Robert sees

Your check-in replies and the drafts made from them, the progress summary,
milestone dates, and any flagged concern. Robert already has access to the
other material (your shared repositories, drafts, his own notes).

## What is stored and where

- Your check-in messages and drafts made from them: on the group workstation
  and GPU node inside KAUST, deleted after 90 days.
- A milestone plan and short work items: in the group's work tracker on the
  same workstation, visible to Robert; you can see your own on request.
- Nothing about grades, HR, visas or health is stored in the system.
- You can ask Robert at any time for a complete export of everything the
  system holds about you.

## How to stop

Tell Robert, in any form. Your permission is removed the same day, the bot
stops answering you, and your stored check-in messages are deleted if you
want. Stopping has no consequence for your supervision.

## Questions

Ask Robert directly. The full rules the system follows are in the group's
repository (`brain/doctrine.md`, `doc/privacy.md`, `doc/contact-policy.md`);
he can show them to you.
