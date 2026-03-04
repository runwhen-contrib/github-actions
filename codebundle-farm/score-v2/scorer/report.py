"""
Score report generation. Produces structured YAML output from check results.
"""

import yaml
from datetime import datetime, timezone


RUBRIC_VERSION = 2
DEFAULT_THRESHOLD = 70


def build_report(bundle_dir: str, category_results: dict, threshold: int = DEFAULT_THRESHOLD) -> dict:
    """
    Build a structured score report from category check results.

    category_results: {
        "structure": [check_results...],
        "robot_framework_quality": [...],
        "execution_design": [...],
        "generation_rules_and_templates": [...],
        "documentation": [...],
    }
    """
    categories = []
    total_score = 0
    total_max = 0
    critical_failures = []
    failed_checks = []

    for cat_name, checks in category_results.items():
        cat_score = sum(c.get("points", 0) for c in checks)
        cat_max = sum(c.get("max_points", 0) for c in checks)
        total_score += cat_score
        total_max += cat_max

        check_reports = []
        for c in checks:
            entry = {
                "id": c["id"],
                "name": c["name"],
                "passed": c["passed"],
                "points": c["points"],
            }
            if not c["passed"]:
                entry["max_points"] = c["max_points"]
                if c.get("feedback"):
                    entry["feedback"] = c["feedback"]
                if c.get("severity") == "critical":
                    critical_failures.append(c["id"])
                failed_checks.append(c)

            check_reports.append(entry)

        categories.append({
            "name": cat_name,
            "score": cat_score,
            "max": cat_max,
            "checks": check_reports,
        })

    passed = total_score >= threshold and len(critical_failures) == 0

    top_improvements = sorted(
        failed_checks,
        key=lambda c: c.get("max_points", 0) - c.get("points", 0),
        reverse=True,
    )[:5]

    import os
    report = {
        "codebundle": os.path.basename(os.path.normpath(bundle_dir)),
        "path": os.path.abspath(bundle_dir),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "rubric_version": RUBRIC_VERSION,
        "score": total_score,
        "max_score": total_max,
        "threshold": threshold,
        "passed": passed,
        "categories": categories,
        "summary": {
            "critical_failures": critical_failures,
            "top_improvements": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "points_available": c.get("max_points", 0) - c.get("points", 0),
                    "feedback": c.get("feedback", ""),
                }
                for c in top_improvements
                if c.get("max_points", 0) - c.get("points", 0) > 0
            ],
        },
    }

    return report


def report_to_yaml(report: dict) -> str:
    return yaml.dump(report, default_flow_style=False, sort_keys=False, allow_unicode=True)


def report_to_markdown(report: dict) -> str:
    """Generate a human-readable markdown summary."""
    lines = []
    status = "PASS" if report["passed"] else "FAIL"
    lines.append(f"# CodeBundle Score: {report['score']}/{report['max_score']} ({status})")
    lines.append("")
    lines.append(f"**CodeBundle**: `{report['codebundle']}`")
    lines.append(f"**Threshold**: {report['threshold']}")
    lines.append(f"**Scored at**: {report['scored_at']}")
    lines.append("")

    if report["summary"]["critical_failures"]:
        lines.append("## Critical Failures")
        lines.append("")
        for cid in report["summary"]["critical_failures"]:
            lines.append(f"- **{cid}**: Critical check failed. Evaluation may be incomplete.")
        lines.append("")

    lines.append("## Category Breakdown")
    lines.append("")
    lines.append("| Category | Score | Max |")
    lines.append("|----------|-------|-----|")
    for cat in report["categories"]:
        lines.append(f"| {cat['name']} | {cat['score']} | {cat['max']} |")
    lines.append("")

    failed = [
        c for cat in report["categories"]
        for c in cat["checks"]
        if not c["passed"]
    ]
    if failed:
        lines.append("## Failed Checks")
        lines.append("")
        for c in failed:
            fb = c.get("feedback", "")
            lines.append(f"- **{c['id']}** ({c['name']}): {fb}")
        lines.append("")

    improvements = report["summary"].get("top_improvements", [])
    if improvements:
        lines.append("## Top Improvements")
        lines.append("")
        for imp in improvements:
            lines.append(f"- **{imp['id']}** (+{imp['points_available']} pts): {imp['feedback']}")
        lines.append("")

    return "\n".join(lines)
