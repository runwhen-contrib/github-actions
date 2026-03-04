"""
Generation rules and template checks (G1-G6).
Validates .runwhen/ directory contents.
"""

import os
from scorer.parsers.yaml_parser import load_yaml_glob, navigate_yaml_path


def check_g1_generation_rules_valid_yaml(bundle_dir: str) -> dict:
    results = load_yaml_glob(bundle_dir, ".runwhen/generation-rules/*.yaml")
    if not results:
        return {
            "id": "G1", "name": "generation_rules_valid_yaml",
            "passed": False, "points": 0, "max_points": 3,
            "feedback": "No generation rules files found.",
        }
    required_keys = ["apiVersion", "kind", "spec"]
    for filepath, data, err in results:
        if err:
            return {
                "id": "G1", "name": "generation_rules_valid_yaml",
                "passed": False, "points": 0, "max_points": 3,
                "feedback": f"Invalid YAML: {err}",
            }
        if data and isinstance(data, dict):
            missing = [k for k in required_keys if k not in data]
            if missing:
                return {
                    "id": "G1", "name": "generation_rules_valid_yaml",
                    "passed": False, "points": 0, "max_points": 3,
                    "feedback": f"Missing required keys in {os.path.basename(filepath)}: {', '.join(missing)}",
                }
    return {
        "id": "G1", "name": "generation_rules_valid_yaml",
        "passed": True, "points": 3, "max_points": 3, "feedback": None,
    }


def check_g2_has_resource_types(bundle_dir: str) -> dict:
    results = load_yaml_glob(bundle_dir, ".runwhen/generation-rules/*.yaml")
    for _, data, _ in results:
        if data:
            val, found = navigate_yaml_path(data, "spec.generationRules[0].resourceTypes")
            if found and val:
                return {
                    "id": "G2", "name": "generation_rules_has_resource_types",
                    "passed": True, "points": 3, "max_points": 3, "feedback": None,
                }
    return {
        "id": "G2", "name": "generation_rules_has_resource_types",
        "passed": False, "points": 0, "max_points": 3,
        "feedback": "Generation rules do not define resourceTypes.",
    }


def check_g3_has_qualifiers(bundle_dir: str) -> dict:
    results = load_yaml_glob(bundle_dir, ".runwhen/generation-rules/*.yaml")
    for _, data, _ in results:
        if data:
            val, found = navigate_yaml_path(data, "spec.generationRules[0].slxs[0].qualifiers")
            if found and val:
                return {
                    "id": "G3", "name": "generation_rules_has_qualifiers",
                    "passed": True, "points": 2, "max_points": 2, "feedback": None,
                }
    return {
        "id": "G3", "name": "generation_rules_has_qualifiers",
        "passed": False, "points": 0, "max_points": 2,
        "feedback": "SLX definitions do not include qualifiers.",
    }


def check_g4_has_output_items(bundle_dir: str) -> dict:
    results = load_yaml_glob(bundle_dir, ".runwhen/generation-rules/*.yaml")
    for _, data, _ in results:
        if data:
            val, found = navigate_yaml_path(data, "spec.generationRules[0].slxs[0].outputItems")
            if found and val:
                return {
                    "id": "G4", "name": "generation_rules_has_output_items",
                    "passed": True, "points": 2, "max_points": 2, "feedback": None,
                }
    return {
        "id": "G4", "name": "generation_rules_has_output_items",
        "passed": False, "points": 0, "max_points": 2,
        "feedback": "SLX definitions do not include outputItems.",
    }


def check_g5_slx_template_valid(bundle_dir: str) -> dict:
    results = load_yaml_glob(bundle_dir, ".runwhen/templates/*-slx.yaml")
    if not results:
        return {
            "id": "G5", "name": "slx_template_valid",
            "passed": False, "points": 0, "max_points": 2,
            "feedback": "No SLX template found.",
        }
    required_keys = ["apiVersion", "kind", "metadata", "spec"]
    for filepath, data, err in results:
        if err:
            return {
                "id": "G5", "name": "slx_template_valid",
                "passed": False, "points": 0, "max_points": 2,
                "feedback": f"SLX template parse error: {err}",
            }
        if data and isinstance(data, dict):
            missing = [k for k in required_keys if k not in data]
            if missing:
                return {
                    "id": "G5", "name": "slx_template_valid",
                    "passed": False, "points": 0, "max_points": 2,
                    "feedback": f"SLX template missing keys: {', '.join(missing)}",
                }
    return {
        "id": "G5", "name": "slx_template_valid",
        "passed": True, "points": 2, "max_points": 2, "feedback": None,
    }


def check_g6_taskset_template_has_config(bundle_dir: str) -> dict:
    results = load_yaml_glob(bundle_dir, ".runwhen/templates/*-taskset.yaml")
    if not results:
        return {
            "id": "G6", "name": "taskset_template_has_config",
            "passed": False, "points": 0, "max_points": 3,
            "feedback": "No taskset template found.",
        }
    for filepath, data, err in results:
        if err or not data:
            continue
        has_config, _ = navigate_yaml_path(data, "spec.configProvided")
        has_secrets, _ = navigate_yaml_path(data, "spec.secretsProvided")
        if has_config:
            return {
                "id": "G6", "name": "taskset_template_has_config",
                "passed": True, "points": 3, "max_points": 3, "feedback": None,
            }
    return {
        "id": "G6", "name": "taskset_template_has_config",
        "passed": False, "points": 0, "max_points": 3,
        "feedback": "Taskset template missing spec.configProvided.",
    }


def run_all(bundle_dir: str) -> list:
    return [
        check_g1_generation_rules_valid_yaml(bundle_dir),
        check_g2_has_resource_types(bundle_dir),
        check_g3_has_qualifiers(bundle_dir),
        check_g4_has_output_items(bundle_dir),
        check_g5_slx_template_valid(bundle_dir),
        check_g6_taskset_template_has_config(bundle_dir),
    ]
