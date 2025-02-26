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

## Content Caching 
This codebundle supports the storage and usage of a json file in order to reduce the load of LLM calls and speeding up subsequent calls. This feature, as in the example below, comitted to the user repo if desired by setting `commit_results: true`. Simply remove the file from the repo to reset the content. 

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

# RunWhen CodeCollection Scoring Action

This Action provides analysis and scoring for `.robot` files (CodeCollection). It can:

1. **Analyze all `.robot` files** or only those **changed in a pull request** (using `git diff`).  
2. **Score** tasks based on clarity, whether they raise issues (for runbooks), whether SLI tasks push metrics, etc.  
3. **Lint** codebundles for missing metadata, documentation, or access tags.  
4. **Optionally apply suggestions** to `.robot` files (e.g., updated task titles, missing `access:...` tags).  
5. **Commit changes** or **open a pull request** automatically with the changes (`task_analysis.json` plus any `.robot` file modifications).

---

## Inputs

Below is a list of inputs you can provide to the Action:

| **Input**            | **Description**                                                                                                                                                                 | **Default**  |
|----------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------|
| **directory**        | Directory with `.robot` files if **not** using a remote repository clone. Ignored if `git_url` is set.                                                                          | `./`         |
| **commit_results**   | **Deprecated** in favor of `commit_changes`. If `true`, sets `commit_changes` to `true` internally.                                                                             | `false`      |
| **git_url**          | A remote Git URL to clone. If provided, the Action will clone that repo into a temp directory, check out `branch`, and analyze there instead of using `directory`.              | *(empty)*    |
| **branch**           | The branch to check out when cloning `git_url`.                                                                                                                                 | `main`       |
| **only_changed**     | If `true`, only analyze `.robot` files that changed between `base_sha` and `head_sha`. If no `base_sha` and `head_sha` are provided, defaults to `HEAD~1`..`HEAD`.             | `false`      |
| **base_sha**         | Base commit SHA for the PR diff. Only used if `only_changed` is `true`.                                                                                                         | *(empty)*    |
| **head_sha**         | Head commit SHA for the PR diff. Only used if `only_changed` is `true`.                                                                                                         | *(empty)*    |
| **apply_suggestions**| If `true`, the script will automatically apply suggested task title changes and missing `access:...` tags to `.robot` files in place.                                           | `false`      |
| **commit_changes**   | If `true`, the Action will commit local changes (including any `.robot` modifications and `task_analysis.json`) to the repo.                                                    | `false`      |
| **open_pr**          | If `true`, the Action will open a new pull request after committing changes (requires `gh` CLI installed).                                                                      | `false`      |
| **pr_branch**        | The branch name to create/checkout when opening a PR (if `open_pr` is `true`).                                                                                                  | `auto-task-analysis` |
| **base_branch**      | The branch into which the PR will be merged.                                                                                                                                    | `main`       |

---

## How It Works

1. **Set up Python**  
   The Action will install Python 3.x and your dependencies (from `requirements.txt`).

2. **Default `base_sha` and `head_sha`** (if needed)  
   - If `only_changed` = `true` **and** both `base_sha` and `head_sha` are empty, the Action sets them to `HEAD~1`..`HEAD`.  
   - Otherwise, it uses whatever values were provided.

3. **Run the scoring script**  
   - Passes along the relevant flags to `score.py`.  
   - For example:
     - `--dir` or `--git-url`  
     - `--only-changed`, `--base-sha`, `--head-sha`  
     - `--apply-suggestions`  
     - `--commit-changes`  
     - `--open-pr`, `--pr-branch`, `--base-branch`  

4. **Script actions**:
   - If `git_url` is supplied, it clones that repo. Otherwise, it analyzes the local `directory`.  
   - If `only_changed` is set, it only scans files returned by `git diff base_sha..head_sha`. Otherwise, it analyzes *all* `.robot` files.  
   - **Lint & scoring** is performed, including checks for missing `access:readonly` or `access:read-write` tags.  
   - If `apply_suggestions` is `true`, the script tries to update `.robot` files with the recommended task titles & tags.  
   - If `commit_changes` is `true`, the script commits (and if `open_pr` is `true`) also opens a PR to `base_branch` from `pr_branch`.

---

## Usage Examples

### 1) Analyze **all** `.robot` files in the current repository, print results only

```yaml
jobs:
  run-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: CodeCollection Scoring
        uses: your-org/code-scoring-action@v1
        with:
          directory: './codebundles'
          # No commit, no PR
```

2) Analyze only changed .robot files in a PR diff
```yaml
jobs:
  run-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: CodeCollection Scoring
        uses: your-org/code-scoring-action@v1
        with:
          only_changed: 'true'
          base_sha: ${{ github.event.pull_request.base.sha }}
          head_sha: ${{ github.event.pull_request.head.sha }}
          # Or let the action auto-default if not provided
```


3) Clone a different repo & branch, analyze, apply suggestions, then commit & open a PR
```
jobs:
  run-analysis-remote:
    runs-on: ubuntu-latest
    steps:
      - name: CodeCollection Scoring
        uses: your-org/code-scoring-action@v1
        with:
          git_url: 'https://github.com/some-other-org/some-other-repo.git'
          branch: 'dev'
          apply_suggestions: 'true'
          commit_changes: 'true'
          open_pr: 'true'
          pr_branch: 'auto-code-updates'
          base_branch: 'main'

```