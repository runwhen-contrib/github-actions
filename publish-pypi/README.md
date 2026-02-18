# Publish PyPI Package

A reusable GitHub Action that builds and publishes Python packages to PyPI with date-based versioning.

## Version Format

Versions follow PyPI-compatible format `YYYY.MM.DD.N` where `N` auto-increments:

- First publish of the day: `2024.01.15.1`
- Second publish: `2024.01.15.2`

Versions are tracked with git tags prefixed by the `tag_prefix` input (default: `pypi-`), e.g., `pypi-2024.01.15.1`.

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `pip_package_name` | Yes | - | PyPI package name (for Slack links) |
| `pypi_token` | Yes | - | PyPI authentication token |
| `version_placeholder` | No | `0.0.0` | Placeholder version in pyproject.toml to replace |
| `pyproject_path` | No | `pyproject.toml` | Path to pyproject.toml |
| `tag_prefix` | No | `pypi-` | Prefix for version tracking tags |
| `python_version` | No | `3.x` | Python version for building |
| `slack_channel` | No | `""` | Slack channel for notifications (empty to skip) |
| `slack_bot_token` | No | `""` | Slack bot token for notifications |

## Outputs

| Output | Description |
|--------|-------------|
| `version` | The version published to PyPI |

## Usage

### Basic

```yaml
name: Publish to PyPI
on:
  push:
    branches: [main]
    paths:
      - 'libraries/**'
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Publish to PyPI
        uses: runwhen-contrib/github-actions/publish-pypi@main
        with:
          pip_package_name: my-package
          pypi_token: ${{ secrets.PYPI_TOKEN }}
```

### With Slack Notification

```yaml
      - name: Publish to PyPI
        uses: runwhen-contrib/github-actions/publish-pypi@main
        with:
          pip_package_name: my-package
          pypi_token: ${{ secrets.PYPI_TOKEN }}
          slack_channel: "#deployments"
          slack_bot_token: ${{ secrets.SLACK_BOT_TOKEN }}
```

### Custom pyproject.toml Location

```yaml
      - name: Publish to PyPI
        uses: runwhen-contrib/github-actions/publish-pypi@main
        with:
          pip_package_name: my-package
          pypi_token: ${{ secrets.PYPI_TOKEN }}
          pyproject_path: packages/my-lib/pyproject.toml
          version_placeholder: "0.0.0-dev"
```

## Requirements

- A `pyproject.toml` with a placeholder version string (default `0.0.0`)
- The checkout step must use `fetch-depth: 0` so tags are available
- A valid PyPI token stored as a repository secret
