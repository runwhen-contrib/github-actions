"""
Documentation checks (D1-D2). Static checks on README.
D3 (LLM-based task description quality) is in llm_checks/task_descriptions.py.

NOTE: meta.yaml is deprecated and no longer used in the RunWhen platform.
      All meta.yaml-related checks (former D2, D3) have been removed.
      CodeBundles that still contain meta.yaml should remove it.
"""

import os
import re
from scorer.parsers.robot_parser import RobotFileInfo


def check_d1_readme_has_sections(bundle_dir: str) -> dict:
    readme_path = os.path.join(bundle_dir, "README.md")
    if not os.path.isfile(readme_path):
        return {
            "id": "D1", "name": "readme_has_sections",
            "passed": False, "points": 0, "max_points": 5,
            "feedback": "README.md not found.",
        }
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return {
            "id": "D1", "name": "readme_has_sections",
            "passed": False, "points": 0, "max_points": 5,
            "feedback": "Cannot read README.md.",
        }

    patterns = {
        "Overview": r"(?i)##.*(?:overview|about|description)",
        "Configuration": r"(?i)##.*(?:config|setup|variables)",
        "Tasks": r"(?i)##.*(?:tasks|capabilities|features)",
    }
    missing = [name for name, pat in patterns.items() if not re.search(pat, content)]
    passed = len(missing) == 0
    return {
        "id": "D1",
        "name": "readme_has_sections",
        "passed": passed,
        "points": 5 if passed else max(0, 5 - (len(missing) * 2)),
        "max_points": 5,
        "feedback": None if passed else f"README.md missing sections: {', '.join(missing)}",
    }


def check_d2_readme_documents_variables(bundle_dir: str, robot_info: RobotFileInfo) -> dict:
    """
    Check that README documents the environment variables used by the CodeBundle.
    This replaces the former meta.yaml parameter documentation check.
    """
    readme_path = os.path.join(bundle_dir, "README.md")
    if not os.path.isfile(readme_path):
        return {
            "id": "D2", "name": "readme_documents_variables",
            "passed": False, "points": 0, "max_points": 6,
            "feedback": "README.md not found.",
        }

    if not robot_info.imported_variables:
        return {
            "id": "D2", "name": "readme_documents_variables",
            "passed": True, "points": 6, "max_points": 6,
            "feedback": None,
        }

    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return {
            "id": "D2", "name": "readme_documents_variables",
            "passed": False, "points": 0, "max_points": 6,
            "feedback": "Cannot read README.md.",
        }

    undocumented = [
        var for var in robot_info.imported_variables
        if var not in content
    ]
    passed = len(undocumented) == 0
    if passed:
        return {
            "id": "D2", "name": "readme_documents_variables",
            "passed": True, "points": 6, "max_points": 6, "feedback": None,
        }

    documented_count = len(robot_info.imported_variables) - len(undocumented)
    total = len(robot_info.imported_variables)
    partial_points = min(4, int(6 * documented_count / total)) if total > 0 else 0
    return {
        "id": "D2",
        "name": "readme_documents_variables",
        "passed": False,
        "points": partial_points,
        "max_points": 6,
        "feedback": f"Variables not mentioned in README: {', '.join(undocumented[:5])}{'...' if len(undocumented) > 5 else ''}",
    }


def run_all(bundle_dir: str, robot_info: RobotFileInfo) -> list:
    return [
        check_d1_readme_has_sections(bundle_dir),
        check_d2_readme_documents_variables(bundle_dir, robot_info),
    ]
