import os
import sys
import json
import fnmatch
import requests
import argparse
import subprocess
import tempfile
import shutil

from robot.api import TestSuite
from tabulate import tabulate

EXPLAIN_URL = "https://papi.beta.runwhen.com/bow/raw?"
HEADERS = {"Content-Type": "application/json"}
PERSISTENT_FILE = "task_analysis.json"
REFERENCE_FILE = "reference_scores.json"

# ======================================================================
# JSON Loading / Saving
# ======================================================================

def load_json_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not parse JSON from {filepath}. Returning empty list.")
                return []
    return []

def save_json_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_reference_scores():
    return load_json_file(REFERENCE_FILE)

def load_persistent_data():
    default_data = {
        "task_results": [],
        "codebundle_results": [],
        "lint_results": []
    }
    if os.path.exists(PERSISTENT_FILE):
        try:
            with open(PERSISTENT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("task_results", [])
                    data.setdefault("codebundle_results", [])
                    data.setdefault("lint_results", [])
                    return data
                elif isinstance(data, list):
                    return {
                        "task_results": data,
                        "codebundle_results": [],
                        "lint_results": []
                    }
                else:
                    return default_data
        except (OSError, json.JSONDecodeError):
            return default_data
    else:
        return default_data

def save_persistent_data(data):
    save_json_file(PERSISTENT_FILE, data)


# ======================================================================
# Robot File Parsing
# ======================================================================

def find_robot_files(directory, pattern="*.robot"):
    matches = []
    for root, _, filenames in os.walk(directory):
        for filename in fnmatch.filter(filenames, pattern):
            matches.append(os.path.join(root, filename))
    return matches

def parse_robot_file(filepath):
    suite = TestSuite.from_file_system(filepath)

    settings_info = {
        "documentation": suite.doc or "",
        "metadata": suite.metadata or {},
        "suite_setup_name": None
    }
    if suite.setup:
        settings_info["suite_setup_name"] = suite.setup.name

    tasks = []
    imported_variables = {}

    # Identify user variables from Suite Initialization
    for keyword in suite.resource.keywords:
        if "Suite Initialization" in keyword.name:
            for statement in keyword.body:
                try:
                    if "RW.Core.Import User Variable" in statement.name:
                        var_name = statement.args[0]
                        imported_variables[var_name] = var_name
                except Exception:
                    continue

    # --- PARSE TESTS ---
    for test in suite.tests:
        # Recursively check if 'RW.Core.Add Issue', 'RW.Core.Push Metric', etc. appear in test.body
        (has_issue,
         issue_is_dynamic,
         has_add_pre_to_report,
         has_push_metric) = scan_steps_for_keywords(test.body)

        tasks.append({
            "name": test.name.strip(),
            "doc": (test.doc or "").strip(),
            "tags": [tag.strip() for tag in test.tags],
            "imported_variables": imported_variables,
            "has_issue": has_issue,
            "issue_is_dynamic": issue_is_dynamic,
            "has_add_pre_to_report": has_add_pre_to_report,
            "has_push_metric": has_push_metric
        })

    return {
        "settings": settings_info,
        "tasks": tasks
    }

def scan_steps_for_keywords(steps):
    """
    Recursively look at each step (and sub-steps) to see if they contain:
      - RW.Core.Add Issue
      - RW.Core.Push Metric
      - RW.Core.Add Pre To Report
    Also track if the Issue call is dynamic (i.e., has a '${' in its args).
    Returns a tuple: (has_issue, issue_is_dynamic, has_add_pre, has_push_metric)
    """
    has_issue = False
    issue_is_dynamic = False
    has_add_pre_to_report = False
    has_push_metric = False

    for step in steps:
        step_name = getattr(step, "name", "") or ""
        step_args = getattr(step, "args", [])

        # 1) Check for RW.Core.Add Issue
        if "RW.Core.Add Issue" in step_name:
            has_issue = True
            # Check if dynamic
            if any("${" in arg for arg in step_args):
                issue_is_dynamic = True

        # 2) Check for RW.Core.Add Pre To Report
        if "RW.Core.Add Pre To Report" in step_name:
            has_add_pre_to_report = True

        # 3) Check for RW.Core.Push Metric
        if "RW.Core.Push Metric" in step_name:
            has_push_metric = True

        # 4) If this step has sub-steps (for block IF, FOR, etc.), recurse
        sub_steps = getattr(step, "body", None)
        if sub_steps:
            (sub_issue,
             sub_dynamic,
             sub_pre,
             sub_push) = scan_steps_for_keywords(sub_steps)

            # Combine results
            if sub_issue:
                has_issue = True
            if sub_dynamic:
                issue_is_dynamic = True
            if sub_pre:
                has_add_pre_to_report = True
            if sub_push:
                has_push_metric = True

    return has_issue, issue_is_dynamic, has_add_pre_to_report, has_push_metric

# ======================================================================
# LLM Querying
# ======================================================================

def query_openai(prompt):
    try:
        response = requests.post(EXPLAIN_URL, json={"prompt": prompt}, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            return response.json().get("explanation", "Response unavailable")
        print(f"Warning: LLM API returned status code {response.status_code}")
    except requests.RequestException as e:
        print(f"Error calling LLM API: {e}")
    return "Response unavailable"

# ======================================================================
# Scoring Logic
# ======================================================================

def match_reference_score(task_title, reference_data):
    for ref in reference_data:
        if ref["task"].lower() == task_title.lower():
            return ref["score"], ref.get("reasoning", "")
    return None, None

def score_task_title(title, doc, tags, imported_variables, existing_data, reference_data):
    for entry in existing_data["task_results"]:
        if entry["task"] == title:
            return entry["score"], entry.get("reasoning", ""), entry.get("suggested_title", "")

    ref_score, ref_reasoning = match_reference_score(title, reference_data)
    if ref_score is not None:
        return ref_score, ref_reasoning, "No suggestion required"

    where_variable = next((var for var in imported_variables if var in title), None)
    prompt = f"""
Given the task title: "{title}", documentation: "{doc}", tags: "{tags}", and imported user variables: "{imported_variables}", 
provide a score from 1 to 5 based on clarity, human readability, and specificity.

Compare it to the following reference examples: {json.dumps(reference_data)}.
A 1 is vague like 'Check EC2 Health'; a 5 is detailed like 'Check Overutilized EC2 Instances in AWS Region `$${{AWS_REGION}}` in AWS Account `$${{AWS_ACCOUNT_ID}}`'.

Ensure that tasks with both a 'What' (resource type) and a 'Where' (specific scope) score at least a 4.
Assume variables will be substituted at runtime, so do not penalize titles for placeholders like `$${{VAR_NAME}}`.
Ensure that any suggested title sets the \"Where\" variable in backticks & curly braces, such as `$${{VAR_NAME}}`.
If a task lacks a specific 'Where' variable, suggest the most relevant imported variable as a \"Where\" in the reasoning.

Return a JSON object with keys: \"score\", \"reasoning\", \"suggested_title\". 
"""
    response_text = query_openai(prompt)
    if not response_text or response_text == "Response unavailable":
        return 1, "Unable to retrieve response from LLM.", f"Improve: {title}"

    try:
        response_json = json.loads(response_text)
        base_score = response_json.get("score", 1)
        reasoning = response_json.get("reasoning", "")
        suggested_title = response_json.get("suggested_title", f"Improve: {title}")

        if not where_variable and base_score > 3:
            suggested_where = next(iter(imported_variables.values()), "N/A")
            base_score = 3
            reasoning += f" The task lacks a specific 'Where' variable; consider using `{suggested_where}`."

        return base_score, reasoning, suggested_title

    except (ValueError, json.JSONDecodeError):
        return 1, "Unable to parse JSON from LLM response.", f"Improve: {title}"

def apply_runbook_issue_rules(base_score, base_reasoning, has_issue, issue_is_dynamic):
    score = base_score
    reasoning = base_reasoning

    if not has_issue:
        score = max(score - 1, 1)
        reasoning += " [Runbook] No RW.Core.Add Issue found. Possibly data-only? -1 penalty.\n"
    else:
        if issue_is_dynamic:
            score = min(score + 1, 5)
            reasoning += " [Runbook] Issue is dynamic (has variables). +1 bonus.\n"
        else:
            reasoning += " [Runbook] Issue is static (no variables). No bonus.\n"

    return score, reasoning

def compute_runbook_codebundle_score(num_tasks):
    if num_tasks < 3:
        return 2, f"Only {num_tasks} tasks => under recommended minimum (3)."
    elif 3 <= num_tasks <= 6:
        return 3, f"{num_tasks} tasks => basic coverage."
    elif 7 <= num_tasks <= 8:
        return 4, f"{num_tasks} tasks => near ideal sweet spot (7-8)."
    elif 9 <= num_tasks <= 10:
        return 3, f"{num_tasks} tasks => slightly above recommended sweet spot."
    else:
        return 2, f"{num_tasks} tasks => likely too large for a single runbook."

def lint_codebundle(settings_info, tasks, is_runbook, is_sli):
    """
    Checks the parsed "settings_info" and "tasks" data against the
    CodeBundle Development Checklist. Returns a dict:
      {
        "lint_score": int,  # 1..5
        "reasons": [str, ...]  # Explanation of any issues
      }
    """
    score = 5
    reasons = []

    # SETTINGS CHECKS
    doc = settings_info.get("documentation", "")
    if not doc.strip():
        score -= 1
        reasons.append("Missing or empty suite-level Documentation in *** Settings ***.")

    metadata = settings_info.get("metadata", {})
    for key in ["Author", "Display Name", "Supports"]:
        if key not in metadata:
            score -= 1
            reasons.append(f"Missing Metadata '{key}' in *** Settings ***.")

    if not settings_info.get("suite_setup_name"):
        score -= 1
        reasons.append("No Suite Setup found (e.g. 'Suite Initialization').")

    # Collect whether we have any push_metric calls at all
    any_push_metric = False

    for t in tasks:
        # Basic doc check
        if not t["doc"].strip():
            score -= 1
            reasons.append(f"Task '{t['name']}' has no [Documentation].")

        # For runbook tasks: expect issues or add pre to report
        if is_runbook:
            if (not t["has_issue"]) and (not t["has_add_pre_to_report"]):
                score -= 0.5
                reasons.append(f"Runbook task '{t['name']}' neither raises issues nor calls RW.Core.Add Pre To Report.")

        # For SLI: we won't penalize each task for missing push_metric,
        # but we do track if at least one has it
        if t["has_push_metric"]:
            any_push_metric = True

    # If it's an SLI, ensure at least one RW.Core.Push Metric was found across all tasks
    if is_sli and not any_push_metric:
        score -= 1
        reasons.append("No RW.Core.Push Metric call found in this SLI.")

    # Clamp score to [1..5]
    if score < 1:
        score = 1
    elif score > 5:
        score = 5

    return {
        "lint_score": score,
        "reasons": reasons
    }


# ======================================================================
# Analysis Orchestrator
# ======================================================================

def analyze_codebundles(directory, cloned_dir=None):
    """
    Analyzes .robot files and adjusts file paths based on cloned repo.
    If `cloned_dir` is provided, ensures file paths are correct.
    """
    robot_files = find_robot_files(directory, "*.robot")
    existing_data = load_persistent_data()
    reference_data = load_reference_scores()

    all_task_results = []

    for filepath in robot_files:
        bundle_name = os.path.basename(os.path.dirname(filepath))
        file_name = os.path.basename(filepath)

        relative_path = os.path.relpath(filepath, cloned_dir or directory)

        parsed_data = parse_robot_file(filepath)

        for t in parsed_data["tasks"]:
            base_score, base_reasoning, suggested_title = score_task_title(
                title=t["name"],
                doc=t["doc"],
                tags=t["tags"],
                imported_variables=t["imported_variables"],
                existing_data=existing_data,
                reference_data=reference_data
            )

            all_task_results.append({
                "codebundle": bundle_name,
                "file": file_name,
                "filepath": relative_path,  
                "task": t["name"],
                "score": base_score,  # ✅ Ensure score is always included
                "reasoning": base_reasoning,
                "suggested_title": suggested_title
            })

    save_persistent_data({"task_results": all_task_results})
    return all_task_results




def print_analysis_report(task_results, codebundle_results, lint_results):
    # (As before) prints out your fancy tables
    # ...
    headers = ["Codebundle", "File", "Task", "Score"]
    table_data = []
    low_score_entries = []

    for entry in task_results:
        table_data.append([
            entry["codebundle"],
            entry["file"],
            entry["task"],
            f"{entry['score']}/5"
        ])
        if entry["score"] <= 3:
            low_score_entries.append(entry)

    print("\n=== Task-Level Analysis ===\n")
    print(tabulate(table_data, headers=headers, tablefmt="fancy_grid"))

    if low_score_entries:
        print("\n--- Detailed Explanations for Task Scores <= 3 ---\n")
        for entry in low_score_entries:
            print(f"• Codebundle: {entry['codebundle']}")
            print(f"  File: {entry['file']}")
            print(f"  Task: {entry['task']}")
            print(f"  Score: {entry['score']}/5")
            print(f"  Reasoning:\n    {entry['reasoning']}")
            print(f"  Suggested Title:\n    {entry['suggested_title']}")
            print("-" * 60)

    if codebundle_results:
        headers_cb = ["Codebundle", "File", "Num Tasks", "Codebundle Score", "Reasoning"]
        table_data_cb = []
        for c in codebundle_results:
            table_data_cb.append([
                c["codebundle"],
                c["file"],
                str(c["num_tasks"]),
                f"{c['codebundle_score']}/5",
                c["reasoning"]
            ])

        print("\n=== Codebundle-Level Analysis (Runbooks) ===\n")
        print(tabulate(table_data_cb, headers=headers_cb, tablefmt="fancy_grid"))

    if lint_results:
        headers_lint = ["Codebundle", "File", "Lint Score", "Reasons"]
        table_data_lint = []
        for lr in lint_results:
            reason_text = "\n".join([f"- {r}" for r in lr["reasons"]]) if lr["reasons"] else ""
            table_data_lint.append([
                lr["codebundle"],
                lr["file"],
                f"{lr['lint_score']}/5",
                reason_text
            ])

        print("\n=== Codebundle Linting ===\n")
        print(tabulate(table_data_lint, headers=headers_lint, tablefmt="fancy_grid"))

    print()

# ======================================================================
# Git commit logic
# ======================================================================
def apply_suggested_titles(task_results, repo_root="."):
    """
    Applies suggested task title changes in the correct file locations.
    If `repo_root` is set, it applies them inside the cloned repo.
    """
    for entry in task_results:
        relative_filepath = entry["filepath"]
        full_path = os.path.join(repo_root, relative_filepath)  # Ensure correct path

        if not os.path.exists(full_path):
            print(f"⚠️ Skipping {full_path}: File does not exist.")
            continue

        # Read file, apply changes, and save it back
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if entry["suggested_title"] and entry["task"] != entry["suggested_title"]: 
            updated_content = content.replace(entry["task"], entry["suggested_title"])

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(updated_content)

            print(f"✅ Applied change in {full_path}: '{entry["task"]}' -> '{entry['suggested_title']}'")


def commit_local(use_pr_flow=False, pr_branch_name="auto-task-analysis", open_pr=False, base_branch="main"):
    """
    Stage, commit, and push the updated 'task_analysis.json'.
    If use_pr_flow=True, create a new local branch and push it.
    If open_pr=True, run 'gh pr create' after pushing.
    """
    PERSISTENT_FILE = "task_analysis.json"

    if not os.path.exists(PERSISTENT_FILE):
        print(f"{PERSISTENT_FILE} does not exist; skipping commit.")
        return

    try:
        subprocess.run(["git", "add", PERSISTENT_FILE], check=True)
        subprocess.run(["git", "commit", "-m", "Update scoring data"], check=True)

        if use_pr_flow:
            subprocess.run(["git", "checkout", "-b", pr_branch_name], check=True)
            subprocess.run(["git", "push", "origin", pr_branch_name], check=True)
            print(f"Committed/pushed changes to new branch '{pr_branch_name}'.")

            if open_pr:
                # Attempt to create a PR using GH CLI
                title = "Automated Title Updates"
                body = "Applied suggestions from analysis."
                subprocess.run([
                    "gh", "pr", "create",
                    "--title", title,
                    "--body", body,
                    "--base", base_branch,
                    "--head", pr_branch_name
                ], check=True)
                print("Opened pull request via GH CLI.")
        else:
            # Normal push
            subprocess.run(["git", "push"], check=True)
            print("Committed/pushed changes on existing branch.")
            if open_pr:
                print("open_pr was requested, but use_pr_flow=False. Need a branch to open a PR from!")
    except subprocess.CalledProcessError as e:
        print("Git commit/push or PR creation failed:", e)

def clone_and_run_analysis(remote_repo, branch="main"):
    """
    1. Clone remote_repo@branch into a temp dir
    2. Run analysis there
    3. If --commit-results, commit/push to remote
    4. Return to original location
    """
    tempdir = tempfile.mkdtemp(prefix="score-")
    old_cwd = os.getcwd()
    try:
        print(f"Cloning {remote_repo} (branch: {branch}) -> {tempdir}")
        subprocess.run(["git", "clone", "--branch", branch, "--depth=1", remote_repo, tempdir], check=True)
        os.chdir(tempdir)

        # Run analysis with correct file path adjustments
        task_results = analyze_codebundles(directory=".", cloned_dir=tempdir)

    finally:
        os.chdir(old_cwd)

    return tempdir

def commit_in_cloned_repo_with_pr(cloned_dir, base_branch="main", pr_branch="auto-task-analysis"):
    """
    Push changes from the cloned repo using a PR workflow.
    - Creates a new branch (`pr_branch`) if it doesn’t exist.
    - Commits changes to the new branch.
    - Pushes to remote.
    - Opens a PR via GitHub CLI.
    """
    persistent_file_path = os.path.join(cloned_dir, PERSISTENT_FILE)
    
    if not os.path.exists(persistent_file_path):
        print("❌ No task_analysis.json found in cloned repo; skipping commit.")
        return

    old_cwd = os.getcwd()
    try:
        os.chdir(cloned_dir)

        # Ensure we fetch the latest from the base branch
        subprocess.run(["git", "fetch", "origin", base_branch], check=True)

        # Create and checkout a new branch
        subprocess.run(["git", "checkout", "-b", pr_branch], check=True)

        # Stage and commit changes
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "Automated scoring update"], check=True)

        # Push the branch to origin
        subprocess.run(["git", "push", "-u", "origin", pr_branch], check=True)
        print(f"✅ Pushed changes to {pr_branch} on remote.")

        # Open a pull request using GitHub CLI (gh)
        pr_title = "CodeCollection Task Analysis Updates"
        pr_body = "This PR updates the content with the latest analysis results."
        subprocess.run([
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", pr_branch,
            "--title", pr_title,
            "--body", pr_body
        ], check=True)
        print(f"✅ Pull request created for {pr_branch} -> {base_branch}")

    except subprocess.CalledProcessError as e:
        print("❌ Git operation failed:", e)

    finally:
        os.chdir(old_cwd)


# ======================================================================
# Main
# ======================================================================
def main():
    parser = argparse.ArgumentParser(description="Run Lint & Scoring on .robot files.")
    parser.add_argument("--dir", default=".", help="Directory of .robot files (for local usage).")
    parser.add_argument("--commit-results", action="store_true", help="Commit changes to the respective repo after scoring.")
    parser.add_argument("--apply-suggestions", action="store_true", help="Apply suggested titles to .robot files.")
    parser.add_argument("--open-pr", action="store_true", help="Open a Pull Request after committing changes.")
    parser.add_argument("--pr-branch", default="auto-task-analysis", help="Branch to create if --open-pr or use_pr_flow is set.")
    parser.add_argument("--base-branch", default="main", help="Base branch for the PR if --open-pr is set.")
    parser.add_argument("--destination-repo", type=str, default="", help="If provided, clone this remote repo first and run analysis inside it.")
    parser.add_argument("--branch", type=str, default="main", help="Branch to use when cloning/pushing remote.")
    args = parser.parse_args()

    if args.destination_repo:
        # 1) Clone the remote
        cloned_dir = clone_and_run_analysis(args.destination_repo, branch=args.branch)
        # 2) Print the analysis report from the data in that cloned dir
        #    But note that analyzing inside `clone_and_run_analysis` saved task_analysis.json in the cloned dir
        #    We can read it from there or do it inside that function
        #    For simplicity, let's read from the cloned_dir
        old_cwd = os.getcwd()
        os.chdir(cloned_dir)
        # re-load the results
        data = load_persistent_data()
        task_results = data["task_results"]
        codebundle_results = data["codebundle_results"]
        lint_results = data["lint_results"]
        print_analysis_report(task_results, codebundle_results, lint_results)
        if args.apply_suggestions:
            apply_suggested_titles(task_results)
        # 3) If commit-results is set, push changes
        if args.commit_results:
            commit_in_cloned_repo_with_pr(cloned_dir, base_branch=args.branch)

        # 4) Cleanup
        os.chdir(old_cwd)
        shutil.rmtree(cloned_dir, ignore_errors=True)

    else:
        # Local usage
        task_results, codebundle_results, lint_results = analyze_codebundles(args.dir)
        print_analysis_report(task_results, codebundle_results, lint_results)

        if args.apply_suggestions:
            apply_suggested_titles(task_results)

        if args.commit_results:
            event_name = os.environ.get("GITHUB_EVENT_NAME", "")
            if event_name == "pull_request":
                commit_local(use_pr_flow=True)
            else:
                commit_local(use_pr_flow=False)


if __name__ == "__main__":
    main()
