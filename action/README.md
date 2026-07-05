# Calma validity check — CLI + GitHub Action

Catch the three ways a reported number lies — **data leakage**, a **trivial/degenerate baseline**, and a
**misreport** (a number the code doesn't produce) — **without running the repo**. Calma re-computes reported
numbers from raw committed outputs: deterministic, **fail-closed** (it never confirms a wrong number; when
there's nothing to check it says so, INCOMPLETE — never a false verdict).

Free. No signup. No data leaves your CI.

## CLI

```bash
python spike/validity_scan.py <path> [--format text|md|json] [--fail-on fail|incomplete|never] [--claim VALUE --metric acc]
```

- Exit code `1` when a validity problem is found (`--fail-on fail`, the default), so it gates CI.
- `--format md` prints a Markdown report card; `--summary-file $GITHUB_STEP_SUMMARY` appends it to the CI summary.
- `--claim 0.97 --metric accuracy` also checks a specific stated number against the repo's committed predictions.

Example:

```
## ❌ Calma validity check — FAIL
| Check            | Result |
|------------------|--------|
| Data leakage     | ❌ fail |
| Trivial baseline | ◻️ not-applicable |
| Misreport        | ◻️ not-applicable |

### Findings
- Data leakage — 2 of 3 test rows (66.7%) appear verbatim in train — the held-out evaluation is contaminated
```

## GitHub Action (PR checking)

Add to `.github/workflows/calma.yml`:

```yaml
on: [pull_request]
permissions:
  contents: read
  pull-requests: write        # to post the report-card comment
jobs:
  validity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rikhinkavuru/calma@v1
        with:
          path: '.'            # or a subdir
          fail-on: fail        # fail | incomplete | never
          comment: 'true'      # post/update a sticky report-card comment on the PR
```

On each PR the action scans the diff's repo state, **posts a sticky report-card comment**, writes a job
summary, and **fails the check** when a leakage / trivial-baseline / misreport is found — so a contaminated
or misreported number can't merge unnoticed. Exit `1` = a validity problem; exit `2` = the scanner itself
errored (a bad path/config — surfaced as a CI warning, never mistaken for a validity failure).

### Prebuilt image (maintainers)

The action runs a **prebuilt** image (`ghcr.io/rikhinkavuru/calma-validity:latest`) so consumers don't rebuild
the SciPy recompute stack on every PR. It is published by `.github/workflows/publish-validity-image.yml` on
each push to `main` and on release, using the repo's built-in `GITHUB_TOKEN` (no manual credentials).

**One-time setup:** after the first publish run, open the repo's *Packages* → `calma-validity` → *Package
settings* and set **visibility to Public** so external `uses: rikhinkavuru/calma@…` can pull it. (To develop the
action from source, temporarily set `image: 'Dockerfile'` in `action.yml`.)

### Inputs

| Input | Default | Description |
|---|---|---|
| `path` | `.` | Path within the repo to scan |
| `fail-on` | `fail` | `fail` \| `incomplete` \| `never` (report-only) |
| `comment` | `true` | Post/update a PR report-card comment (needs `pull-requests: write`) |
| `github-token` | `${{ github.token }}` | Token for the PR comment |

### Output

| Output | Description |
|---|---|
| `grade` | `PASS` \| `FAIL` \| `INCOMPLETE` |

## What it does NOT do

It does not execute your code (that's the deep-verify product). This is the no-run **validity wedge**: it
only inspects committed data, splits, and predictions. A repo with nothing committed to check returns
`INCOMPLETE` — honest, never a false pass.
