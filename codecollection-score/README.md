## Purpose
The `codecollection-score` action is used by codecolleciton authors to perform some basic linting and scoring of the codebundle (.robot file) quality. 
One main feature is that it evaulates the Task title, which is very important in the system to have specific detail, and provides suggestions
as to titles that may improve searchability within the RunWhen Platform. 

Additional checks include:
- amount of tasks in a codebundle
- if issues are raised (for runbook tasks)
- if issues are dynamic or statis (for runbook tasks)
- if metrics are pushed (for sli tasks)
- if basic linting checks pass (Metadata, Display Name, etc exist)

## Example Usage: 

```
name: Score CodeCollection
on: 
  workflow_dispatch:

jobs:
  score-codebundles:
    runs-on: ubuntu-latest
    permissions:
      contents: write  # <-- This ensures we can push commits
    steps:
      - name: Check out the repo
        uses: actions/checkout@v3
        with:
          fetch-depth: 0  # so we can push back

      - name: Set Git user
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

      - uses: runwhen-contrib/github-actions/codecollection-score@score
        with:
          directory: './codebundles'
          commit_results: true
```