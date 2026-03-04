"""
Robot Framework quality checks (R1-R10).
Evolved from the lint_codebundle() function in the existing scorer.
"""

import re
from scorer.parsers.robot_parser import (
    RobotFileInfo,
    get_issue_call_arguments,
    has_keyword_usage,
    has_try_except,
)


def check_r1_metadata_complete(robot_info: RobotFileInfo) -> dict:
    required = ["Author", "Display Name", "Supports"]
    missing = [k for k in required if k not in robot_info.metadata]
    passed = len(missing) == 0
    return {
        "id": "R1",
        "name": "metadata_complete",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": None if passed else f"Missing metadata: {', '.join(missing)}",
    }


def check_r2_documentation_present(robot_info: RobotFileInfo) -> dict:
    passed = bool(robot_info.documentation.strip())
    return {
        "id": "R2",
        "name": "documentation_present",
        "passed": passed,
        "points": 2 if passed else 0,
        "max_points": 2,
        "feedback": None if passed else "No suite-level Documentation in Settings.",
    }


def check_r3_force_tags_present(robot_info: RobotFileInfo) -> dict:
    passed = len(robot_info.force_tags) > 0
    return {
        "id": "R3",
        "name": "force_tags_present",
        "passed": passed,
        "points": 2 if passed else 0,
        "max_points": 2,
        "feedback": None if passed else "No Force Tags defined in Settings.",
    }


def check_r4_rw_libraries_imported(robot_info: RobotFileInfo) -> dict:
    required = ["RW.Core", "RW.CLI"]
    missing = [lib for lib in required if lib not in robot_info.libraries]
    passed = len(missing) == 0
    return {
        "id": "R4",
        "name": "rw_libraries_imported",
        "passed": passed,
        "points": 3 if passed else 0,
        "max_points": 3,
        "feedback": None if passed else f"Missing library imports: {', '.join(missing)}",
    }


def check_r5_tasks_have_documentation(robot_info: RobotFileInfo) -> dict:
    if not robot_info.tasks:
        return {
            "id": "R5", "name": "tasks_have_documentation",
            "passed": False, "points": 0, "max_points": 4,
            "feedback": "No tasks found.",
        }
    missing = [t.name for t in robot_info.tasks if not t.doc.strip()]
    passed = len(missing) == 0
    return {
        "id": "R5",
        "name": "tasks_have_documentation",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": None if passed else f"Tasks missing [Documentation]: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}",
    }


def check_r6_tasks_have_tags(robot_info: RobotFileInfo) -> dict:
    if not robot_info.tasks:
        return {
            "id": "R6", "name": "tasks_have_tags",
            "passed": False, "points": 0, "max_points": 3,
            "feedback": "No tasks found.",
        }
    access_pattern = re.compile(r"access:(read-only|read-write)")
    missing_tags = []
    missing_access = []
    for task in robot_info.tasks:
        if not task.tags:
            missing_tags.append(task.name)
        elif not any(access_pattern.search(tag) for tag in task.tags):
            missing_access.append(task.name)

    passed = len(missing_tags) == 0 and len(missing_access) == 0
    feedback = None
    if missing_tags:
        feedback = f"Tasks missing [Tags]: {', '.join(missing_tags[:3])}"
    elif missing_access:
        feedback = f"Tasks missing access:read-only/read-write tag: {', '.join(missing_access[:3])}"
    return {
        "id": "R6",
        "name": "tasks_have_tags",
        "passed": passed,
        "points": 3 if passed else 0,
        "max_points": 3,
        "feedback": feedback,
    }


def check_r7_issue_reporting_quality(robot_info: RobotFileInfo) -> dict:
    required_args = {"severity", "expected", "actual", "title", "details", "next_steps"}
    issue_arg_sets = get_issue_call_arguments(robot_info)
    if not issue_arg_sets:
        return {
            "id": "R7", "name": "issue_reporting_quality",
            "passed": False, "points": 0, "max_points": 5,
            "feedback": "No RW.Core.Add Issue calls found. Runbook tasks should report issues.",
        }
    all_complete = all(required_args.issubset(arg_set) for arg_set in issue_arg_sets)
    if all_complete:
        return {
            "id": "R7", "name": "issue_reporting_quality",
            "passed": True, "points": 5, "max_points": 5, "feedback": None,
        }
    for arg_set in issue_arg_sets:
        missing = required_args - arg_set
        if missing:
            return {
                "id": "R7", "name": "issue_reporting_quality",
                "passed": False, "points": 2, "max_points": 5,
                "feedback": f"RW.Core.Add Issue calls missing arguments: {', '.join(sorted(missing))}",
            }


def check_r8_report_data_added(robot_info: RobotFileInfo) -> dict:
    passed = has_keyword_usage(robot_info, "RW.Core.Add Pre To Report")
    return {
        "id": "R8",
        "name": "report_data_added",
        "passed": passed,
        "points": 2 if passed else 0,
        "max_points": 2,
        "feedback": None if passed else "No RW.Core.Add Pre To Report calls found.",
    }


def check_r9_error_handling(robot_info: RobotFileInfo) -> dict:
    passed = has_try_except(robot_info)
    return {
        "id": "R9",
        "name": "error_handling",
        "passed": passed,
        "points": 3 if passed else 0,
        "max_points": 3,
        "feedback": None if passed else "No TRY/EXCEPT blocks found. Use TRY/EXCEPT for JSON parsing and external calls.",
    }


def check_r10_suite_setup_exists(robot_info: RobotFileInfo) -> dict:
    passed = bool(robot_info.suite_setup_name)
    return {
        "id": "R10",
        "name": "suite_setup_exists",
        "passed": passed,
        "points": 2 if passed else 0,
        "max_points": 2,
        "feedback": None if passed else "No Suite Setup defined. Use Suite Initialization for variable imports.",
    }


def run_all(robot_info: RobotFileInfo) -> list:
    return [
        check_r1_metadata_complete(robot_info),
        check_r2_documentation_present(robot_info),
        check_r3_force_tags_present(robot_info),
        check_r4_rw_libraries_imported(robot_info),
        check_r5_tasks_have_documentation(robot_info),
        check_r6_tasks_have_tags(robot_info),
        check_r7_issue_reporting_quality(robot_info),
        check_r8_report_data_added(robot_info),
        check_r9_error_handling(robot_info),
        check_r10_suite_setup_exists(robot_info),
    ]
