"""
Execution design checks (E1-E6): Task count, timeouts, script validation.
"""

import os
import re
from scorer.parsers.robot_parser import (
    RobotFileInfo,
    get_bash_file_references,
    has_keyword_with_argument,
)


def check_e1_task_count(robot_info: RobotFileInfo) -> dict:
    count = len(robot_info.tasks)
    passed = 1 <= count <= 15
    feedback = None
    if count == 0:
        feedback = "No tasks found in runbook.robot."
    elif count > 15:
        feedback = f"{count} tasks is too many for a single runbook. Consider splitting."
    return {
        "id": "E1",
        "name": "task_count_reasonable",
        "passed": passed,
        "points": 3 if passed else 0,
        "max_points": 3,
        "feedback": feedback,
    }


def check_e2_timeout_configured(robot_info: RobotFileInfo) -> dict:
    passed = has_keyword_with_argument(robot_info, "Run Bash File", "timeout_seconds")
    return {
        "id": "E2",
        "name": "timeout_configured",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": None if passed else "RW.CLI.Run Bash File calls should include timeout_seconds.",
    }


def check_e3_scripts_exist(robot_info: RobotFileInfo, bundle_dir: str) -> dict:
    bash_files = get_bash_file_references(robot_info)
    if not bash_files:
        # No bash files referenced -- could be using inline commands
        return {
            "id": "E3", "name": "scripts_exist",
            "passed": True, "points": 5, "max_points": 5,
            "feedback": None,
        }
    missing = []
    for bf in bash_files:
        full_path = os.path.join(bundle_dir, bf)
        if not os.path.isfile(full_path):
            missing.append(bf)
    passed = len(missing) == 0
    return {
        "id": "E3",
        "name": "scripts_exist",
        "passed": passed,
        "points": 5 if passed else 0,
        "max_points": 5,
        "feedback": None if passed else f"Missing scripts: {', '.join(missing)}",
    }


def check_e4_json_output_pattern(robot_info: RobotFileInfo, bundle_dir: str) -> dict:
    """
    Check that bash scripts produce JSON output. Looks for common patterns
    like 'json', 'jq', or writing to .json files.
    """
    bash_files = get_bash_file_references(robot_info)
    if not bash_files:
        return {
            "id": "E4", "name": "json_output_pattern",
            "passed": True, "points": 4, "max_points": 4,
            "feedback": None,
        }

    json_patterns = re.compile(r"(\.json|jq\s|json\.dumps|json_output|JSON)", re.IGNORECASE)
    scripts_with_json = 0

    for bf in bash_files:
        full_path = os.path.join(bundle_dir, bf)
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if json_patterns.search(content):
                    scripts_with_json += 1
            except OSError:
                pass

    passed = scripts_with_json > 0
    return {
        "id": "E4",
        "name": "json_output_pattern",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": None if passed else "No bash scripts appear to produce structured JSON output.",
    }


def check_e5_cheatsheet_enabled(robot_info: RobotFileInfo) -> dict:
    passed = has_keyword_with_argument(robot_info, "Run Bash File", "show_in_rwl_cheatsheet")
    return {
        "id": "E5",
        "name": "cheatsheet_enabled",
        "passed": passed,
        "points": 2 if passed else 0,
        "max_points": 2,
        "feedback": None if passed else "No tasks have show_in_rwl_cheatsheet=true.",
    }


def check_e6_cmd_override_present(robot_info: RobotFileInfo) -> dict:
    passed = has_keyword_with_argument(robot_info, "Run Bash File", "cmd_override")
    return {
        "id": "E6",
        "name": "cmd_override_present",
        "passed": passed,
        "points": 2 if passed else 0,
        "max_points": 2,
        "feedback": None if passed else "No tasks provide cmd_override for display purposes.",
    }


def run_all(robot_info: RobotFileInfo, bundle_dir: str) -> list:
    return [
        check_e1_task_count(robot_info),
        check_e2_timeout_configured(robot_info),
        check_e3_scripts_exist(robot_info, bundle_dir),
        check_e4_json_output_pattern(robot_info, bundle_dir),
        check_e5_cheatsheet_enabled(robot_info),
        check_e6_cmd_override_present(robot_info),
    ]
