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
from robot.api.parsing import get_model
from tabulate import tabulate

# --------------------------------------------------------------------------------
# Configuration / Constants
# --------------------------------------------------------------------------------

EXPLAIN_URL = "https://papi.beta.runwhen.com/bow/raw?"
HEADERS = {"Content-Type": "application/json"}

PERSISTENT_FILE = "task_analysis.json"
REFERENCE_FILE = "reference_scores.json"

# --------------------------------------------------------------------------------
# JSON Loading / Saving
# --------------------------------------------------------------------------------

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
    """
    Safely load the persistent data from JSON.
    Ensures we always return a dict with keys:
      'task_results', 'codebundle_results', 'lint_results'
    """
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
                    # If it's a list, wrap it
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


# --------------------------------------------------------------------------------
# Robot File Parsing
# --------------------------------------------------------------------------------

def find_robot_files(directory, pattern="*.robot"):
    """
    Recursively find .robot files matching the pattern in the given directory.
    """
    matches = []
    for root, _, filenames in os.walk(directory):
        for filename in fnmatch.filter(filenames, pattern):
            matches.append(os.path.join(root, filename))
    return matches

def parse_robot_file(filepath):
    """
    Parse a Robot file using robot.api.TestSuite to extract:
      - Settings
      - Imported user variables
      - Tasks with:
          name, doc, tags, whether it calls RW.Core.Add Issue, etc.
    """
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

    # For each test, scan steps to see if they call RW.Core.* keywords
    for test in suite.tests:
        has_issue, issue_is_dynamic, has_add_pre_to_report, has_push_metric = scan_steps_for_keywords(test.body)

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
    Recursively check if we call:
      - RW.Core.Add Issue (is it dynamic?)
      - RW.Core.Push Metric
      - RW.Core.Add Pre To Report
    Returns (has_issue, issue_is_dynamic, has_add_pre_to_report, has_push_metric).
    """
    has_issue = False
    issue_is_dynamic = False
    has_add_pre_to_report = False
    has_push_metric = False

    for step in steps:
        step_name = getattr(step, "name", "") or ""
        step_args = getattr(step, "args", []) or []

        if "RW.Core.Add Issue" in step_name:
            has_issue = True
            if any("${" in arg for arg in step_args):
                issue_is_dynamic = True

        if "RW.Core.Add Pre To Report" in step_name:
            has_add_pre_to_report = True

        if "RW.Core.Push Metric" in step_name:
            has_push_metric = True

        # Recursively scan sub-steps (FOR, IF blocks, etc.)
        sub_steps = getattr(step, "body", None)
        if sub_steps:
            sub_issue, sub_dynamic, sub_pre, sub_push = scan_steps_for_keywords(sub_steps)
            if sub_issue: has_issue = True
            if sub_dynamic: issue_is_dynamic = True
            if sub_pre: has_add_pre_to_report = True
            if sub_push: has_push_metric = True

    return has_issue, issue_is_dynamic, has_add_pre_to_report, has_push_metric

# --------------------------------------------------------------------------------
# LLM Querying
# --------------------------------------------------------------------------------

def query_openai(prompt):
    """
    Generic helper to call your LLM endpoint.
    """
    try:
        response = requests.post(EXPLAIN_URL, json={"prompt": prompt}, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            return response.json().get("explanation", "Response unavailable")
        print(f"Warning: LLM API returned status code {response.status_code}")
    except requests.RequestException as e:
        print(f"Error calling LLM API: {e}")
    return "Response unavailable"


# --------------------------------------------------------------------------------
# Access Tag Suggestion
# --------------------------------------------------------------------------------

def suggest_access_tag(title, doc, tags):
    """
    Use the LLM to suggest either 'access:readonly' or 'access:read-write'
    based on the task's content.
    """
    prompt = f"""
Given the following task data:
- Title: "{title}"
- Documentation: "{doc}"
- Existing tags: {tags}

Decide if this task only reads/collects data (=> "access:readonly")
or modifies/updates resources (=> "access:read-write").

Return JSON: {{ "suggested_access_tag": "access:readonly" }} or "access:read-write".
"""
    response_text = query_openai(prompt)
    if not response_text or response_text == "Response unavailable":
        return "access:readonly"  # fallback

    try:
        parsed = json.loads(response_text)
        return parsed.get("suggested_access_tag", "access:readonly")
    except (ValueError, json.JSONDecodeError):
        return "access:readonly"


# --------------------------------------------------------------------------------
# Scoring Logic (Task-Level)
# --------------------------------------------------------------------------------

def match_reference_score(task_title, reference_data):
    for ref in reference_data:
        if ref["task"].lower() == task_title.lower():
            return ref["score"], ref.get("reasoning", "")
    return None, None

def score_task_title(title, doc, tags, imported_variables, existing_data, reference_data):
    """
    If we've scored this task before (in persistent data), reuse that.
    Otherwise, ask LLM or match known reference scores.
    """
    # Check existing data first
    for entry in existing_data["task_results"]:
        if entry["task"] == title:
            return entry["score"], entry.get("reasoning", ""), entry.get("suggested_title", "")

    # Check reference data
    ref_score, ref_reasoning = match_reference_score(title, reference_data)
    if ref_score is not None:
        return ref_score, ref_reasoning, "No suggestion required"

    # Otherwise, call LLM
    where_variable = next((var for var in imported_variables if var in title), None)
    prompt = f"""
Given the task title: "{title}", documentation: "{doc}", tags: "{tags}", and imported user variables: "{imported_variables}", 
provide a score from 1 to 5 based on clarity, human readability, and specificity.

Compare it to the following reference examples: {json.dumps(reference_data)}.
A 1 is vague like 'Check EC2 Health'; a 5 is detailed like 'Check Overutilized EC2 Instances in AWS Region `$${{AWS_REGION}}` in AWS Account `$${{AWS_ACCOUNT_ID}}`'.

If a task lacks a 'What' or a 'Where', it might be less specific. 
Return JSON: {{ "score": ..., "reasoning": "...", "suggested_title": "..." }}.
"""
    response_text = query_openai(prompt)
    if not response_text or response_text == "Response unavailable":
        return 1, "Unable to retrieve response from LLM.", f"Improve: {title}"

    try:
        parsed = json.loads(response_text)
        base_score = parsed.get("score", 1)
        reasoning = parsed.get("reasoning", "")
        suggested_title = parsed.get("suggested_title", f"Improve: {title}")

        # If no 'where' variable but LLM gave >3, reduce it a bit
        if not where_variable and base_score > 3:
            base_score = 3
            reasoning += " (Reduced for missing 'Where' variable.)"

        return base_score, reasoning, suggested_title

    except (ValueError, json.JSONDecodeError):
        return 1, "Unable to parse JSON from LLM response.", f"Improve: {title}"

def apply_runbook_issue_rules(base_score, base_reasoning, has_issue, issue_is_dynamic):
    """
    If it's a runbook, penalize tasks not raising an issue, or reward dynamic issues.
    """
    final_score = base_score
    final_reasoning = base_reasoning

    if not has_issue:
        final_score = max(final_score - 1, 1)
        final_reasoning += " [Runbook] No RW.Core.Add Issue => -1.\n"
    else:
        if issue_is_dynamic:
            final_score = min(final_score + 1, 5)
            final_reasoning += " [Runbook] Issue is dynamic => +1.\n"

    return final_score, final_reasoning


# --------------------------------------------------------------------------------
# Codebundle-Level Checks
# --------------------------------------------------------------------------------

def compute_runbook_codebundle_score(num_tasks):
    """
    A simple scoring heuristic for runbooks based on # tasks.
    """
    if num_tasks < 3:
        return 2, f"Only {num_tasks} tasks => under recommended minimum (3)."
    elif 3 <= num_tasks <= 6:
        return 3, f"{num_tasks} tasks => basic coverage."
    elif 7 <= num_tasks <= 8:
        return 4, f"{num_tasks} tasks => near ideal sweet spot (7-8)."
    elif 9 <= num_tasks <= 10:
        return 3, f"{num_tasks} tasks => slightly above recommended sweet spot."
    else:  # >10
        return 2, f"{num_tasks} tasks => likely too large for a single runbook."


# --------------------------------------------------------------------------------
# Lint Checks
# --------------------------------------------------------------------------------

def lint_codebundle(settings_info, tasks, is_runbook, is_sli):
    """
    Check codebundle for:
      - Suite-level doc, metadata, suite setup
      - For runbook tasks: either add issue or add to report
      - For SLI tasks: at least one push metric
      - For each task: doc, plus we require an access:* tag
    """
    score = 5
    reasons = []

    # Suite checks
    doc = settings_info.get("documentation", "")
    if not doc.strip():
        score -= 1
        reasons.append("Missing or empty suite-level documentation.")

    metadata = settings_info.get("metadata", {})
    for key in ["Author", "Display Name", "Supports"]:
        if key not in metadata:
            score -= 1
            reasons.append(f"Missing Metadata key '{key}' in *** Settings ***.")

    if not settings_info.get("suite_setup_name"):
        score -= 1
        reasons.append("No Suite Setup found (e.g. 'Suite Initialization').")

    # SLI check: at least one push metric across tasks
    found_push_metric = any(t["has_push_metric"] for t in tasks) if tasks else False

    # Task-level checks
    for t in tasks:
        # Documentation
        if not t["doc"].strip():
            score -= 1
            reasons.append(f"Task '{t['name']}' has no [Documentation].")

        # Runbook: expect either issue or pre-report
        if is_runbook:
            if not t["has_issue"] and not t["has_add_pre_to_report"]:
                score -= 0.5
                reasons.append(f"Runbook task '{t['name']}' neither adds an issue nor a pre-report.")

        # Access tag check
        if not any(tag.lower() in ("access:readonly", "access:read-write") for tag in t["tags"]):
            score -= 1
            reasons.append(f"Task '{t['name']}' missing required 'access:...' tag.")

    if is_sli and not found_push_metric:
        score -= 1
        reasons.append("No tasks called RW.Core.Push Metric in this SLI codebundle.")

    # clamp score 1..5
    score = max(1, min(score, 5))
    return {
        "lint_score": score,
        "reasons": reasons
    }


# --------------------------------------------------------------------------------
# Git / Changed Files
# --------------------------------------------------------------------------------

def get_changed_robot_files(repo_dir, base_sha, head_sha):
    """
    Return a list of changed *.robot files between base_sha and head_sha in repo_dir.
    """
    try:
        # Attempt to fetch these SHAs
        subprocess.run(["git", "fetch", "origin", base_sha, head_sha], cwd=repo_dir, check=True)
    except subprocess.CalledProcessError:
        print("Warning: failed to fetch base/head. Diff might be incomplete.")

    cmd = ["git", "diff", "--name-only", base_sha, head_sha]
    result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, check=True)
    changed = [line.lstrip() for line in result.stdout.splitlines() if line.lstrip().endswith(".robot")]
    return [os.path.join(repo_dir, c) for c in changed]


# --------------------------------------------------------------------------------
# Main Analysis (combining all checks)
# --------------------------------------------------------------------------------

def analyze_codebundles(robot_files):
    """
    1) Parse each .robot file => gather tasks
    2) Score tasks
    3) If runbook => apply runbook logic
    4) For each codebundle => lint & codebundle scoring
    5) Return (task_results, codebundle_results, lint_results) and also persist
    """
    existing_data = load_persistent_data()
    reference_data = load_reference_scores()

    codebundle_map = {}  
    # (bundle_name, file_name) -> {
    #   "filepath": ...,
    #   "settings": ...,
    #   "tasks": [...]
    # }

    for filepath in robot_files:
        if not os.path.exists(filepath):
            print(f"Skipping missing file: {filepath}")
            continue
        bundle_name = os.path.basename(os.path.dirname(filepath))
        file_name = os.path.basename(filepath)

        parsed = parse_robot_file(filepath)
        codebundle_map[(bundle_name, file_name)] = {
            "filepath": filepath,
            "settings": parsed["settings"],
            "tasks": parsed["tasks"]
        }

    all_task_results = []
    codebundle_results = []
    lint_results = []

    for (bundle_name, file_name), data in codebundle_map.items():
        filepath = data["filepath"]
        settings_info = data["settings"]
        tasks = data["tasks"]

        is_runbook = "runbook.robot" in file_name.lower()
        is_sli = "sli.robot" in file_name.lower()

        # 1) Score tasks (title clarity)
        for t in tasks:
            base_score, base_reasoning, suggested_title = score_task_title(
                title=t["name"],
                doc=t["doc"],
                tags=t["tags"],
                imported_variables=t["imported_variables"],
                existing_data=existing_data,
                reference_data=reference_data
            )

            final_score = base_score
            final_reasoning = base_reasoning

            # If runbook => apply runbook issue logic
            if is_runbook:
                final_score, final_reasoning = apply_runbook_issue_rules(
                    final_score, final_reasoning, t["has_issue"], t["issue_is_dynamic"]
                )

            # If missing an access tag, suggest one
            has_access_tag = any(tag.lower() in ("access:readonly", "access:read-write") for tag in t["tags"])
            suggested_access_tag = ""
            if not has_access_tag:
                suggested_access_tag = suggest_access_tag(t["name"], t["doc"], t["tags"])

            all_task_results.append({
                "codebundle": bundle_name,
                "file": file_name,
                "filepath": filepath,
                "task": t["name"],
                "score": final_score,
                "reasoning": final_reasoning,
                "suggested_title": suggested_title,
                "missing_access_tag": not has_access_tag,
                "suggested_access_tag": suggested_access_tag
            })

        # 2) Codebundle-level scoring (Runbooks only)
        if is_runbook:
            num_tasks = len(tasks)
            cb_score, cb_reasoning = compute_runbook_codebundle_score(num_tasks)
            codebundle_results.append({
                "codebundle": bundle_name,
                "file": file_name,
                "num_tasks": num_tasks,
                "codebundle_score": cb_score,
                "reasoning": cb_reasoning
            })

        # 3) Lint checks
        lint_res = lint_codebundle(settings_info, tasks, is_runbook, is_sli)
        lint_results.append({
            "codebundle": bundle_name,
            "file": file_name,
            "lint_score": lint_res["lint_score"],
            "reasons": lint_res["reasons"]
        })

    combined_data = {
        "task_results": all_task_results,
        "codebundle_results": codebundle_results,
        "lint_results": lint_results
    }
    save_persistent_data(combined_data)

    return all_task_results, codebundle_results, lint_results


# --------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------

def print_analysis_report(task_results, codebundle_results, lint_results):
    """
    Print tables for:
      1) Task-Level Analysis
      2) Codebundle-Level Analysis (Runbooks)
      3) Lint Results
    """
    # 1) Task-Level
    headers = ["Codebundle", "File", "Task", "Score", "Access Missing?"]
    table_data = []
    low_score_entries = []

    for t in task_results:
        table_data.append([
            t["codebundle"],
            t["file"],
            t["task"],
            f"{t['score']}/5",
            "YES" if t["missing_access_tag"] else "NO"
        ])
        if t["score"] <= 3:
            low_score_entries.append(t)

    print("\n=== Task-Level Analysis ===\n")
    print(tabulate(table_data, headers=headers, tablefmt="fancy_grid"))

    if low_score_entries:
        print("\n--- Detailed Explanations for Tasks <= 3 ---\n")
        for entry in low_score_entries:
            print(f"• Codebundle: {entry['codebundle']} | File: {entry['file']}")
            print(f"  Task: {entry['task']} | Score: {entry['score']}/5")
            print(f"  Reasoning:\n    {entry['reasoning']}")
            if entry.get("suggested_title"):
                print(f"  Suggested Title: {entry['suggested_title']}")
            if entry["missing_access_tag"]:
                print(f"  Suggested Access Tag: {entry['suggested_access_tag']}")
            print("-"*60)

    # 2) Codebundle-Level (Runbooks)
    if codebundle_results:
        headers_cb = ["Codebundle", "File", "Num Tasks", "Score", "Reasoning"]
        table_data_cb = []
        for c in codebundle_results:
            table_data_cb.append([
                c["codebundle"],
                c["file"],
                c["num_tasks"],
                f"{c['codebundle_score']}/5",
                c["reasoning"]
            ])
        print("\n=== Codebundle-Level Analysis (Runbooks) ===\n")
        print(tabulate(table_data_cb, headers=headers_cb, tablefmt="fancy_grid"))

    # 3) Lint
    if lint_results:
        headers_lint = ["Codebundle", "File", "Lint Score", "Reasons"]
        table_data_lint = []
        for lr in lint_results:
            reason_text = "\n".join(f"- {r}" for r in lr["reasons"])
            table_data_lint.append([
                lr["codebundle"],
                lr["file"],
                f"{lr['lint_score']}/5",
                reason_text
            ])
        print("\n=== Codebundle Linting ===\n")
        print(tabulate(table_data_lint, headers=headers_lint, tablefmt="fancy_grid"))
    print()


# --------------------------------------------------------------------------------
# Applying Suggestions Locally
# --------------------------------------------------------------------------------

def apply_suggestions_with_parser(task_results):
    """
    Parser-based approach to rename tasks and append missing access tags
    in .robot files using `get_model` and `model.serialize(...)`.

    We'll gather each file's tasks from `task_results`, parse it, then:
      - For each test matching the old name, rename it to `suggested_title`
      - If missing_access_tag is True, append the suggested_access_tag to [Tags]
      - Then serialize the updated AST back to the file.
    """

    # 1) Organize task_results by filepath
    file_map = {}
    for entry in task_results:
        fp = entry["filepath"]
        file_map.setdefault(fp, []).append(entry)

    for filepath, entries in file_map.items():
        if not os.path.exists(filepath):
            print(f"Skipping missing file: {filepath}")
            continue

        print(f"\nParsing {filepath} with Robot parser...")

        model = get_model(filepath)
        changed_something = False

        # We'll build a quick lookup:
        # old_name -> (new_name, missing_access, suggested_access)
        tasks_map = {}
        for e in entries:
            old_name = e["task"]
            new_name = e.get("suggested_title") or old_name
            missing = e.get("missing_access_tag", False)
            suggested_tag = e.get("suggested_access_tag", "")
            tasks_map[old_name] = (new_name, missing, suggested_tag)

        # 2) Walk model.sections to find TestCaseSection
        for section in model.sections:
            if section.type == 'TESTCASE':  # A TestCaseSection
                for testcase in section.body:
                    old_name = testcase.name
                    if old_name in tasks_map:
                        new_name, missing_access, sug_access = tasks_map[old_name]

                        # (A) Rename the test
                        if new_name and new_name != old_name:
                            testcase.name = new_name
                            changed_something = True
                            print(f"  Renamed test '{old_name}' -> '{new_name}'")

                        # (B) If missing an access tag, append sug_access
                        if missing_access and sug_access:
                            # We'll see if there's an existing [Tags] statement
                            tags_stmt = None
                            for stmt in testcase.body:
                                if stmt.type == 'TAGS':
                                    tags_stmt = stmt
                                    break
                            if tags_stmt:
                                # Check if it already has "access:"
                                # Typically tokens for arguments might be: tags_stmt.tokens
                                token_values = [t.value for t in tags_stmt.tokens if t.type == t.ARG]
                                has_access = any(val.lower().startswith("access:") for val in token_values)
                                if not has_access:
                                    # Insert new token
                                    tags_stmt.tokens.append(tags_stmt.tokens[0].clone(value='    '))
                                    tags_stmt.tokens.append(tags_stmt.tokens[0].clone(value=sug_access, type=t.ARG))
                                    changed_something = True
                                    print(f"  Appended '{sug_access}' to existing [Tags] for '{new_name}'")
                            else:
                                # No [Tags], create one
                                from robot.api.parsing import Statement, Token
                                new_stmt = Statement.from_tokens([
                                    Token(Token.TAGS, '[Tags]'),
                                    Token(Token.SEPARATOR, '    '),
                                    Token(Token.ARG, sug_access)
                                ])
                                testcase.body.insert(0, new_stmt)
                                changed_something = True
                                print(f"  Created [Tags] with '{sug_access}' for '{new_name}'")

        if changed_something:
            # (C) Serialize back to the file
            with open(filepath, "w", encoding="utf-8") as out:
                model.serialize(out)
            print(f"Saved updates to {filepath}")
        else:
            print(f"No changes needed for {filepath}")

def apply_suggestions_locally(task_results):
    """
    Improved naive approach:
      1. Replace old task name with suggested title anywhere the old name appears in a line.
      2. Track test names (even if indented).
      3. Capture multi-line [Tags] blocks (with lines starting '...') until next non-'...' line.
      4. If a test is missing an 'access:...' tag, we append the suggested tag to the last line of that [Tags] block.
    """

    # Group entries by file
    file_map = {}
    for entry in task_results:
        file_map.setdefault(entry["filepath"], []).append(entry)

    for filepath, entries in file_map.items():
        if not os.path.exists(filepath):
            print(f"Skipping missing file: {filepath}")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Step 1: Replace old test name => new test name
        updated_lines = []
        for line in lines:
            new_line = line
            for e in entries:
                old_name = e["task"]
                new_name = e["suggested_title"]
                if new_name and new_name != old_name and old_name in new_line:
                    new_line = new_line.replace(old_name, new_name)
            updated_lines.append(new_line)

        # Step 2: Append missing access tags
        #   We'll assume each "test name" line is any non-empty line that
        #   does NOT start with [ or # or ...
        #   That sets current_test_name. Then if we see a [Tags] block, we
        #   gather lines until next non-'...' line. At flush, we see if this test is missing an access tag.

        final_lines = []
        current_test_name = None
        inside_tags_block = False
        tags_block_lines = []
        i = 0

        def flush_tags_block():
            nonlocal tags_block_lines
            joined = "".join(tags_block_lines)

            # We'll find the entry whose old or new name matches current_test_name
            for e in entries:
                old_n = e["task"]
                new_n = e["suggested_title"]
                if current_test_name in [old_n, new_n]:
                    if e["missing_access_tag"] and e["suggested_access_tag"]:
                        # If this block is missing, let's append it
                        if e["suggested_access_tag"] not in joined:
                            # Append to last line
                            if tags_block_lines and tags_block_lines[-1].lstrip().startswith("..."):
                                tags_block_lines[-1] = tags_block_lines[-1].rstrip("\n") + f"    {e['suggested_access_tag']}\n"
                            else:
                                tags_block_lines[-1] = tags_block_lines[-1].rstrip("\n") + f"    {e['suggested_access_tag']}\n"
                            print(f"Appending {e['suggested_access_tag']} to test '{current_test_name}' in {filepath}")

            for block_line in tags_block_lines:
                final_lines.append(block_line)
            tags_block_lines = []

        while i < len(updated_lines):
            line = updated_lines[i]
            stripped = line.strip()

            # If we see a line that's a potential test name
            # (not empty, doesn't start with [ or # or ...)
            if stripped and not stripped.startswith("[") and not stripped.startswith("#") and not stripped.startswith("..."):
                current_test_name = stripped

            if not inside_tags_block:
                if "[Tags]" in stripped:
                    inside_tags_block = True
                    tags_block_lines = [line]
                else:
                    final_lines.append(line)
            else:
                # We're inside a [Tags] block
                if stripped.startswith("..."):
                    tags_block_lines.append(line)
                else:
                    # End of this block
                    flush_tags_block()
                    inside_tags_block = False
                    final_lines.append(line)
            i += 1

        # If we ended still in a tags block, flush
        if inside_tags_block:
            flush_tags_block()

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(final_lines)

        print(f"✅ Possibly updated titles/tags in: {filepath}")



# --------------------------------------------------------------------------------
# Git / PR Logic
# --------------------------------------------------------------------------------

def commit_local_changes(message="Update scoring data"):
    """
    Stage and commit the changes in the local repo (including task_analysis.json, 
    and any .robot files).
    """
    try:
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        print("Committed local changes.")
    except subprocess.CalledProcessError as e:
        print("No changes to commit or commit failed:", e)

def push_current_branch():
    """
    Push current branch to origin
    """
    try:
        subprocess.run(["git", "push"], check=True)
        print("Pushed current branch to origin.")
    except subprocess.CalledProcessError as e:
        print("Push failed:", e)

def create_pr(base_branch, pr_branch, title, body):
    """
    Create a PR using GitHub CLI from pr_branch => base_branch
    """
    try:
        subprocess.run([
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", pr_branch,
            "--title", title,
            "--body", body
        ], check=True)
        print("Pull request created.")
    except subprocess.CalledProcessError as e:
        print("Failed to create PR:", e)

def create_or_update_branch(pr_branch):
    """
    If pr_branch doesn't exist, create it from current HEAD, push it.
    If it does exist, just checkout it and push.
    """
    # Check if local branch pr_branch already exists
    try:
        subprocess.run(["git", "rev-parse", "--verify", pr_branch], check=True, capture_output=True)
        # Branch already exists locally
        subprocess.run(["git", "checkout", pr_branch], check=True)
        print(f"Checked out existing branch {pr_branch}.")
    except subprocess.CalledProcessError:
        # Branch doesn't exist => create it
        subprocess.run(["git", "checkout", "-b", pr_branch], check=True)
        print(f"Created new branch {pr_branch}.")

    # Push
    try:
        subprocess.run(["git", "push", "-u", "origin", pr_branch], check=True)
        print(f"Pushed branch {pr_branch} to remote.")
    except subprocess.CalledProcessError as e:
        print("Failed to push branch:", e)


# --------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run Lint & Scoring on .robot files, optionally open a PR.")
    parser.add_argument("--dir", default=".", help="Directory with .robot files (ignored if we clone a remote).")

    # If analyzing only changed files in a local or cloned repo
    parser.add_argument("--only-changed", action="store_true", help="Analyze only changed .robot files.")
    parser.add_argument("--base-sha", default="", help="Base SHA for diff if only-changed is used.")
    parser.add_argument("--head-sha", default="", help="Head SHA for diff if only-changed is used.")

    # Remote repo logic
    parser.add_argument("--git-url", help="Remote repo to clone for analysis", default=None)
    parser.add_argument("--branch", help="Branch to checkout after cloning", default="main")

    # Committing / PR
    parser.add_argument("--commit-changes", action="store_true", help="Commit changes (task_analysis.json, .robot) back to the repo.")
    parser.add_argument("--open-pr", action="store_true", help="Open a PR after committing (requires gh CLI).")
    parser.add_argument("--pr-branch", default="auto-task-analysis", help="Branch name to push changes to.")
    parser.add_argument("--base-branch", default="main", help="PR base branch.")

    # Apply suggestions
    parser.add_argument("--apply-suggestions", action="store_true", 
                        help="If set, automatically modify .robot files with suggested titles + tags.")


    args = parser.parse_args()

    # 1) Possibly clone the repo
    if args.git_url:
        temp_dir = tempfile.mkdtemp(prefix="repo_clone_")
        print(f"Cloning {args.git_url} into {temp_dir}")
        try:
            subprocess.run(["git", "clone", "--depth", "1", "-b", args.branch, args.git_url, temp_dir], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error cloning {args.git_url}: {e}")
            sys.exit(1)
        repo_dir = temp_dir
    else:
        repo_dir = args.dir

    # 2) Possibly gather only changed .robot files
    if args.only_changed and args.base_sha and args.head_sha:
        changed_files = get_changed_robot_files(repo_dir, args.base_sha, args.head_sha)
        robot_files = changed_files
        print(f"Analyzing only changed files between {args.base_sha}..{args.head_sha}")
    else:
        robot_files = find_robot_files(repo_dir, "*.robot")
        print(f"Analyzing all .robot files under {repo_dir}")

    # 3) Run analysis
    task_results, codebundle_results, lint_results = analyze_codebundles(robot_files)

    # 4) Print results
    print_analysis_report(task_results, codebundle_results, lint_results)

    # 5) Optionally apply suggested changes in-place
    if args.apply_suggestions:
        apply_suggestions_with_parser(task_results)

    # 6) If commit-changes is set, commit/push in the current or cloned repo
    if args.commit_changes:
        old_cwd = os.getcwd()
        os.chdir(repo_dir)

        # If we want to create or switch to a new branch
        if args.open_pr:
            create_or_update_branch(args.pr_branch)

        # Stage and commit
        commit_local_changes(message="Automated code collection scoring updates")

        if args.open_pr:
            # We are presumably on pr_branch now
            push_current_branch()
            create_pr(args.base_branch, args.pr_branch, 
                      title="Automated Scoring Updates",
                      body="Applying LLM-based suggestions for titles and access tags.")
        else:
            # Just push to the current branch
            push_current_branch()

        os.chdir(old_cwd)

    # 7) Cleanup if cloned
    if args.git_url:
        shutil.rmtree(repo_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
