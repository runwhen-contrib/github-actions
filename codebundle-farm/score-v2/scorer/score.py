#!/usr/bin/env python3
"""
CodeBundle Scorer CLI.

Evaluates CodeBundle quality against a 100-point rubric.

Usage:
    python -m scorer.score /path/to/codebundle
    python -m scorer.score --batch /path/to/codebundles/
    python -m scorer.score /path/to/codebundle --format markdown
"""

import argparse
import os
import sys

from scorer.parsers.robot_parser import parse_robot_file
from scorer.checks import structure, robot_quality, execution, generation_rules, documentation
from scorer.report import build_report, report_to_yaml, report_to_markdown, DEFAULT_THRESHOLD


def score_codebundle(bundle_dir: str, threshold: int = DEFAULT_THRESHOLD, output_format: str = "yaml") -> dict:
    """
    Score a single CodeBundle directory.
    Returns the report dict and prints output.
    """
    bundle_dir = os.path.abspath(bundle_dir)

    if not os.path.isdir(bundle_dir):
        print(f"Error: {bundle_dir} is not a directory.", file=sys.stderr)
        sys.exit(2)

    # Phase 1: Structure checks (no robot parsing needed)
    structure_results = structure.run_all(bundle_dir)

    # Only block robot parsing if runbook.robot itself is missing
    runbook_missing = not any(
        c["id"] == "S1" and c["passed"] for c in structure_results
    )

    # Phase 2: Robot parsing and robot-dependent checks
    robot_info = None
    robot_results = []
    execution_results = []
    doc_results = []

    runbook_path = os.path.join(bundle_dir, "runbook.robot")
    if os.path.isfile(runbook_path) and not runbook_missing:
        try:
            robot_info = parse_robot_file(runbook_path)
            robot_results = robot_quality.run_all(robot_info)
            execution_results = execution.run_all(robot_info, bundle_dir)
            doc_results = documentation.run_all(bundle_dir, robot_info)
        except Exception as e:
            print(f"Warning: Robot parsing failed: {e}", file=sys.stderr)
            robot_results = _empty_robot_results()
            execution_results = _empty_execution_results()
            doc_results = _empty_doc_results(bundle_dir)
    else:
        robot_results = _empty_robot_results()
        execution_results = _empty_execution_results()
        doc_results = _empty_doc_results(bundle_dir)

    # Phase 3: Generation rules (independent of robot parsing)
    gen_results = generation_rules.run_all(bundle_dir)

    # Build report
    category_results = {
        "structure": structure_results,
        "robot_framework_quality": robot_results,
        "execution_design": execution_results,
        "generation_rules_and_templates": gen_results,
        "documentation": doc_results,
    }

    report = build_report(bundle_dir, category_results, threshold)

    if output_format == "markdown":
        print(report_to_markdown(report))
    elif output_format == "yaml":
        print(report_to_yaml(report))

    return report


def _empty_robot_results():
    """Return zeroed-out robot quality results when parsing isn't possible."""
    checks = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]
    names = [
        "metadata_complete", "documentation_present", "force_tags_present",
        "rw_libraries_imported", "tasks_have_documentation", "tasks_have_tags",
        "issue_reporting_quality", "report_data_added", "error_handling",
        "suite_setup_exists",
    ]
    points = [4, 2, 2, 3, 4, 3, 5, 2, 3, 2]
    return [
        {"id": cid, "name": name, "passed": False, "points": 0,
         "max_points": mp, "feedback": "Could not parse runbook.robot."}
        for cid, name, mp in zip(checks, names, points)
    ]


def _empty_execution_results():
    checks = ["E1", "E2", "E3", "E4", "E5", "E6"]
    names = [
        "task_count_reasonable", "timeout_configured", "scripts_exist",
        "json_output_pattern", "cheatsheet_enabled", "cmd_override_present",
    ]
    points = [3, 4, 5, 4, 2, 2]
    return [
        {"id": cid, "name": name, "passed": False, "points": 0,
         "max_points": mp, "feedback": "Could not parse runbook.robot."}
        for cid, name, mp in zip(checks, names, points)
    ]


def _empty_doc_results(bundle_dir):
    """D1 can run without robot, D2 needs robot info for variable list."""
    return [
        documentation.check_d1_readme_has_sections(bundle_dir),
        {"id": "D2", "name": "readme_documents_variables", "passed": False,
         "points": 0, "max_points": 6, "feedback": "Could not parse runbook.robot."},
    ]


def batch_score(codebundles_dir: str, threshold: int = DEFAULT_THRESHOLD, output_format: str = "yaml"):
    """Score all CodeBundles in a directory."""
    if not os.path.isdir(codebundles_dir):
        print(f"Error: {codebundles_dir} is not a directory.", file=sys.stderr)
        sys.exit(2)

    results = []
    for entry in sorted(os.listdir(codebundles_dir)):
        bundle_dir = os.path.join(codebundles_dir, entry)
        runbook = os.path.join(bundle_dir, "runbook.robot")
        if os.path.isdir(bundle_dir) and os.path.isfile(runbook):
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"Scoring: {entry}", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)
            report = score_codebundle(bundle_dir, threshold, output_format="none")
            results.append(report)

    # Print batch summary
    print(f"\n{'='*60}")
    print("BATCH SCORING SUMMARY")
    print(f"{'='*60}")
    print(f"\n{'Codebundle':<50} {'Score':>6} {'Status':>8}")
    print("-" * 66)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['codebundle']:<50} {r['score']:>3}/{r['max_score']:<3} {status:>8}")

    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} CodeBundles passed (threshold: {threshold})")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Score CodeBundle quality against a 100-point rubric.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scorer.score ./codebundles/azure-devops-repository-health
  python -m scorer.score --batch ./codebundles/
  python -m scorer.score ./codebundles/k8s-deployment-healthcheck --format markdown
        """,
    )
    parser.add_argument("path", help="Path to CodeBundle directory (or parent dir with --batch)")
    parser.add_argument("--batch", action="store_true", help="Score all CodeBundles in directory")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help=f"Passing score (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--format", choices=["yaml", "markdown"], default="yaml", help="Output format (default: yaml)")

    args = parser.parse_args()

    if args.batch:
        results = batch_score(args.path, args.threshold, args.format)
        any_failed = any(not r["passed"] for r in results)
        sys.exit(1 if any_failed else 0)
    else:
        report = score_codebundle(args.path, args.threshold, args.format)
        sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
