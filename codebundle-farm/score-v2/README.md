# CodeBundle Score v2

Scores CodeBundle quality against a 100-point rubric. Designed to run in CI on CodeCollection repositories.

## Features

- **Single or batch** — score one CodeBundle or every bundle in a repo
- **PR-aware** — detect changed CodeBundles in a pull request, score only those
- **PR comments** — posts (or updates) a markdown summary directly on the PR
- **Threshold gating** — fail the check if any bundle scores below a configurable threshold
- **Rubric v2** — structure, robot quality, execution design, generation rules, documentation

## Quick Start

### Score all CodeBundles on push

```yaml
name: Score CodeBundles
on: [push]

jobs:
  score:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: runwhen-contrib/github-actions/codebundle-farm/score-v2@main
        with:
          directory: ./codebundles
          batch: "true"
          threshold: "70"
```

### Score only changed bundles on PR

```yaml
name: Score Changed CodeBundles
on: [pull_request]

jobs:
  score:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: runwhen-contrib/github-actions/codebundle-farm/score-v2@main
        with:
          directory: ./codebundles
          only_changed: "true"
          post_comment: "true"
```

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `directory` | `./` | CodeBundle directory or parent directory (batch mode) |
| `batch` | `false` | Score all CodeBundles under `directory` |
| `threshold` | `70` | Minimum score to pass (0–100) |
| `only_changed` | `false` | Only score bundles with changed files in the PR |
| `base_sha` | *(auto)* | Base SHA for diff |
| `head_sha` | *(auto)* | Head SHA for diff |
| `post_comment` | `true` | Post markdown summary as PR comment |
| `fail_below_threshold` | `true` | Fail the action if any bundle is below threshold |
| `github_token` | `${{ github.token }}` | Token for PR comment API calls |

## Outputs

| Output | Description |
|--------|-------------|
| `total_scored` | Number of CodeBundles scored |
| `total_passed` | Number that passed |
| `total_failed` | Number that failed |
| `report_markdown` | Full markdown report |

## Rubric Categories (100 points)

| Category | Points | Checks |
|----------|--------|--------|
| Structure | 20 | S1–S5 |
| Robot Framework Quality | 30 | R1–R10 |
| Execution Design | 20 | E1–E6 |
| Generation Rules & Templates | 19 | G1–G5 |
| Documentation | 11 | D1–D2 |

See the [full rubric](https://github.com/stewartshea/codebundle-farm/blob/main/docs/scorer/rubric.yaml) for details.

## Migration from v1 (`codecollection-score`)

v2 replaces the monolithic `score.py` with a modular scorer package. Key changes:

- **`meta.yaml` is deprecated** — no longer scored. Remove it from your CodeBundles.
- **New rubric** — 100-point scale with 5 categories, 28 checks.
- **PR comments** — automatic, updating (no duplicate comments).
- **Changed-only mode** — faster CI on large CodeCollections.
- **Inputs renamed** — `commit_results`, `apply_suggestions`, `open_pr` are removed. The action is now read-only (scoring only). Use a separate workflow for automated fixes.

### Before (v1)

```yaml
- uses: runwhen-contrib/github-actions/codecollection-score@main
  with:
    directory: ./codebundles
    commit_results: "true"
```

### After (v2)

```yaml
- uses: runwhen-contrib/github-actions/codebundle-farm/score-v2@main
  with:
    directory: ./codebundles
    batch: "true"
```
