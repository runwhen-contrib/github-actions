# Generate Date-Based Release

A reusable GitHub Action that creates date-based tags and GitHub releases with automatic versioning.

## Tag Format

Tags follow the format `YYYY-MM-DD.N` where `N` auto-increments for multiple releases on the same day:

- First release of the day: `2024-01-15.1`
- Second release: `2024-01-15.2`
- With prefix `v`: `v2024-01-15.1`

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github_token` | Yes | - | GitHub token for creating releases |
| `tag_prefix` | No | `""` | Optional prefix for the tag |

## Outputs

| Output | Description |
|--------|-------------|
| `release_tag` | The full tag name of the created release |
| `version` | Alias for `release_tag` |

## Usage

### Basic

```yaml
name: Release
on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: true

      - name: Create Release
        uses: runwhen-contrib/github-actions/generate-release@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

### With Tag Prefix

```yaml
      - name: Create Release
        id: release
        uses: runwhen-contrib/github-actions/generate-release@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          tag_prefix: "v"

      - name: Use release tag
        run: echo "Released ${{ steps.release.outputs.release_tag }}"
```

## Requirements

- The calling workflow must set `permissions: contents: write`
- The checkout step must use `fetch-depth: 0` and `persist-credentials: true`
