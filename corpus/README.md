# Corpus: grounding sources for borg-cube skills

Every borg-cube skill cites its methodological sources through this directory.
The pipeline is: manifest -> fetch -> convert -> distill -> sync into skills.

## Layout

| Path | Tracked | Content |
| --- | --- | --- |
| `sources.yaml` | yes | Manifest: one entry per source with id, type, citation, DOI or URL, license, open-access flag, excerpt policy, topics, verification and fetch state |
| `raw/` | no (gitignored) | Downloaded PDFs and HTML pages, named `<id>.<ext>`; `raw/crossref/` caches Crossref JSON for `corpus_verify` |
| `text/` | no (gitignored) | Plain-text conversions, `<id>.txt` |
| `distilled/` | yes | One file per topic in the group's own words, written from the text and reviewed by Robert; `TEMPLATE.md` is the shape |
| `notes/` | yes | Robert's own notes on copyrighted books (referenced by `notes:` in the manifest); never copies |

## Recipes

```
just corpus-fetch [--id ID] [--topic T] [--dry-run]   # OA items into raw/, 1 request/s
just corpus-convert [--id ID]                          # pdftotext -layout, pandoc html -> text/
just corpus-verify [--offline] [--urls] [--mark-verified]  # Crossref title match for every DOI
just skills-sync [--check]                             # copy distilled/<topic>.md into skills
```

`corpus-fetch` writes `fetched` and `sha256` back into the manifest entry in
place. NAP reports need a manual download click: save the PDF as
`raw/<id>.pdf` and rerun the fetcher to record the hash.

## Copyright rules

- CC-BY (PLOS, F1000, PeerJ, Turing Way, Carpentries, BMJ open access): short
  excerpts with attribution, no quote longer than 25 words.
- CC-BY-NC and CC-BY-NC-ND (Teaching Tech Together, Vitae): summarise only.
- NAP free-to-read PDFs and paywalled articles: summarise only, never excerpt.
- KAUST pages (`excerpt_ok: quote-rules-only`): store locally, quote the rules
  briefly, never republish the page.
- Books (`type: book`, `oa: false`): cite only; the corpus holds Robert's own
  notes under `notes/`.

Distilled files are the group's own words. Every claim carries a manifest id.

## Manifest conventions

- `verified_by: memory` means the entry was written from memory and
  `corpus-verify` must confirm the DOI against Crossref before it is trusted;
  `--mark-verified` upgrades matching entries to `fetch`. `robert` marks
  institutional entries that only Robert can confirm.
- Never invent a DOI. Leave `doi: null` and say so in `notes:`.
- Ids are lowercase, stable, and cited as `[id]` in distilled files and in the
  Sources block of every `skills/<s>/references/*.md`.

## Adding a source

1. Add the entry to `sources.yaml` (copy a neighbour; keep the field order).
2. `just corpus-verify --id <id>` (DOI entries) or check the URL by hand.
3. `just corpus-fetch --id <id>` and `just corpus-convert --id <id>` when it
   is open access.
4. Cite it from a distilled file or a skill reference; `just skills-lint`
   fails on ids that exist in no Sources block.
