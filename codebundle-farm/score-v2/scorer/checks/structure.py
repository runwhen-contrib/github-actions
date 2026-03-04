"""
Structure checks (S1-S5): File existence, naming convention, directory layout.

NOTE: meta.yaml is deprecated and no longer used by the RunWhen platform.
The former S2 (meta.yaml exists) check has been removed.
"""

import os
import re
import glob as globmod


def check_s1_runbook_exists(bundle_dir: str) -> dict:
    path = os.path.join(bundle_dir, "runbook.robot")
    exists = os.path.isfile(path)
    return {
        "id": "S1",
        "name": "runbook_robot_exists",
        "passed": exists,
        "points": 5 if exists else 0,
        "max_points": 5,
        "severity": "critical",
        "feedback": None if exists else "runbook.robot is missing. This is required for every CodeBundle.",
    }


def check_s2_readme_exists(bundle_dir: str) -> dict:
    path = os.path.join(bundle_dir, "README.md")
    exists = os.path.isfile(path)
    return {
        "id": "S2",
        "name": "readme_exists",
        "passed": exists,
        "points": 3 if exists else 0,
        "max_points": 3,
        "feedback": None if exists else "README.md is missing.",
    }


def check_s3_generation_rules_exist(bundle_dir: str) -> dict:
    pattern = os.path.join(bundle_dir, ".runwhen", "generation-rules", "*.yaml")
    matches = globmod.glob(pattern)
    passed = len(matches) >= 1
    return {
        "id": "S3",
        "name": "generation_rules_exist",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": None if passed else "No generation rules YAML found in .runwhen/generation-rules/.",
    }


def check_s4_templates_exist(bundle_dir: str) -> dict:
    slx_pattern = os.path.join(bundle_dir, ".runwhen", "templates", "*-slx.yaml")
    taskset_pattern = os.path.join(bundle_dir, ".runwhen", "templates", "*-taskset.yaml")
    has_slx = len(globmod.glob(slx_pattern)) >= 1
    has_taskset = len(globmod.glob(taskset_pattern)) >= 1
    passed = has_slx and has_taskset
    feedback = None
    if not passed:
        missing = []
        if not has_slx:
            missing.append("*-slx.yaml")
        if not has_taskset:
            missing.append("*-taskset.yaml")
        feedback = f"Missing templates in .runwhen/templates/: {', '.join(missing)}"
    return {
        "id": "S4",
        "name": "templates_exist",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": feedback,
    }


def check_s5_naming_convention(bundle_dir: str) -> dict:
    dirname = os.path.basename(os.path.normpath(bundle_dir))
    pattern = r"^[a-z][a-z0-9]+-[a-z][a-z0-9]+-[a-z][a-z0-9-]+$"
    passed = bool(re.match(pattern, dirname))
    return {
        "id": "S5",
        "name": "naming_convention",
        "passed": passed,
        "points": 4 if passed else 0,
        "max_points": 4,
        "feedback": None if passed else (
            f"Directory name '{dirname}' does not follow "
            f"{{platform}}-{{resource}}-{{purpose}} pattern. "
            f"Use lowercase with hyphens, e.g. azure-devops-project-health."
        ),
    }


def run_all(bundle_dir: str) -> list:
    return [
        check_s1_runbook_exists(bundle_dir),
        check_s2_readme_exists(bundle_dir),
        check_s3_generation_rules_exist(bundle_dir),
        check_s4_templates_exist(bundle_dir),
        check_s5_naming_convention(bundle_dir),
    ]
