# Operational facts

`cube brain push` loads every `brain/facts/*.yaml` into `bd remember`. The files
are site-specific (hosts, services, roster facts) and gitignored. Format:

```yaml
facts:
  - text: >-
      One self-contained paragraph. Facts about people are roster facts, never
      assessments; conflicts are stated as conflicts.
    source: doc/plan.md (hosting topology), cube.yaml paths
```
