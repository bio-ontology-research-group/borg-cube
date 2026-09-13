# ADR-0026: Artifacts leave the laptop by push into a drop directory on ws

Status: accepted
Date: 2026-09-08
Extends: ADR-0025 (the liaison channel is the ledger), ADR-0017 (ledger sync)

## Context

ADR-0025 left one gap: a liaison answer that is a file (a drafted student
report, a data table, a PDF) has no channel beyond a pointer into
`state/agents/liaison/answers/` on the laptop. Robert asked on 2026-09-08
whether Beads could carry such files. It can in the narrowest sense: bd has
no attachments, only text fields, and a file pasted into a description or
comment replicates with the whole Dolt ledger to every host and to the git
remote on every tick, stays in the ledger's history after the bead closes,
and lands in every prompt that reads the bead. CLAUDE.md already says beads
hold work items and provenance only. Robert chose option 3 of the three
offered: the laptop pushes over the ssh route it already has to ws, ws never
pulls, and the bead holds the pointer and the checksum.

Measured on ws on 2026-09-08 (`df -h` over ssh): `/` 303G at 93 percent,
`/mnt/data1` 1.8T at 48 percent with 914G free, `/mnt/data2` 1.8T at 49
percent with 895G free. Both data disks belong to Robert's account. `/mnt/data1`
already holds the group's working data (`empty-quarter`, `dl-nesy`,
`km-archives`); `/mnt/data2` holds buffers and an IBEX mount.

## Decision

1. Every host entry in `cube.yaml` may name a `drop` directory. ws names
   `/mnt/data1/cube-drop`. The laptop names none: nothing is pushed to it.
2. `cube drop <bead> <file> [--host ws] --apply` is the only way an artifact
   leaves a host. It refuses a `privacy:local-only` bead, a secret-looking
   file name (`.env`, `auth.json`, `password*`), a host without ssh or a drop
   directory. It computes the local sha256, creates `<drop>/<bead>/` on the
   receiving host with mode 700, pushes the file with rsync over ssh
   (mode 600), reads the remote sha256, and only when the two match comments
   on the bead: `artifact: ws:<path> sha256 <hex> bytes <n> pushed from
   <host>`. A mismatch or an unreachable host is an error in the result and
   the exit code, with no comment. `--dry-run` (the default) computes the
   checksum and prints the three commands.
3. The receiving side reads the artifact where the bead points and verifies
   the checksum before use; nothing on ws lists or scans the drop directory.
   Files stay under `<drop>/<bead>/`; deleting them is a sysadmin action on
   Robert's ask, never a patrol.
4. The liaison prompt tells the model step to use `cube drop` for anything
   larger than a comment and never to paste it.
5. A git checkout travels the same way (Robert, 2026-09-08: FLOPO lives on
   the laptop first, and a ws agent continues from that state). `cube drop
   <bead> <checkout> --repo --apply` writes three artifacts under
   `state/drop/<bead>/` and pushes them: `<name>.bundle` (`git bundle create
   --all`, every ref), `<name>.uncommitted.patch` (`git diff HEAD --binary`,
   tracked changes only) and `<name>.manifest.txt` (head, branch, upstream
   and how far ahead, `status --short`, the untracked files that were not
   shipped, and the receive command). One bead comment carries the three
   checksums. The receiver runs, in this order, `git fetch <bundle>
   <branch>`, `git checkout -B <branch> FETCH_HEAD`, `git apply <patch>`.
   Untracked data never travels; the flopoontology working tree is 60G, its
   bundle 93 MB and its patch 67 MB (measured 2026-09-08, bead cube-iclb).

## Consequences

- The bead stays small: one comment line per artifact. The ledger never
  carries file content.
- A `local-only` artifact stays on the laptop by construction; the pointer
  path in the answer file is the only trace, and that file is on the laptop.
- The route is one way and depends on the laptop reaching ws over ssh (the
  `ssh: ws` entry). When ws is unreachable the command fails visibly and the
  liaison's bead comment says so; there is no queue for files.
- `/mnt/data1` fills by artifacts only as fast as the liaison produces them;
  the infra hygiene patrol already watches disk use on ws.
