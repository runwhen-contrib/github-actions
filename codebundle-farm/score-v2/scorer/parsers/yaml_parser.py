"""
Safe YAML loading with error handling for meta.yaml, generation rules,
and template files. Handles Jinja2 template syntax gracefully.
"""

import os
import glob as globmod
import yaml


def load_yaml(filepath: str) -> tuple:
    """
    Load a YAML file. Returns (data, error_message).
    If the file contains Jinja2 templates ({{ }}), attempts a best-effort
    parse by stripping template markers first.
    """
    if not os.path.exists(filepath):
        return None, f"File not found: {filepath}"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return None, f"Cannot read {filepath}: {e}"

    try:
        data = yaml.safe_load(content)
        return data, None
    except yaml.YAMLError:
        pass

    # Jinja2 templates often break YAML parsers; try progressively
    # aggressive cleanup strategies
    strategies = [
        # Strategy 1: Quote template expressions
        lambda c: c.replace("{{", "\"TMPL_").replace("}}", "_TMPL\"")
                   .replace("{%", "# ").replace("%}", ""),
        # Strategy 2: Remove template expressions entirely
        lambda c: _strip_jinja(c),
        # Strategy 3: Replace entire lines containing templates with placeholders
        lambda c: "\n".join(
            f"  placeholder: true" if "{{" in line or "{%" in line else line
            for line in c.splitlines()
        ),
    ]
    for strategy in strategies:
        try:
            cleaned = strategy(content)
            data = yaml.safe_load(cleaned)
            return data, None
        except (yaml.YAMLError, Exception):
            continue

    return None, f"YAML parse error in {filepath}: contains Jinja2 templates that cannot be safely parsed"


def load_yaml_glob(base_dir: str, pattern: str) -> list:
    """
    Find all files matching glob pattern relative to base_dir and load them.
    Returns list of (filepath, data, error_message) tuples.
    """
    full_pattern = os.path.join(base_dir, pattern)
    results = []
    for filepath in sorted(globmod.glob(full_pattern)):
        data, err = load_yaml(filepath)
        results.append((filepath, data, err))
    return results


def navigate_yaml_path(data, key_path: str):
    """
    Navigate a dot-separated key path through a YAML structure.
    Supports array index notation: 'spec.generationRules[0].resourceTypes'
    Returns (value, found) tuple.
    """
    if data is None:
        return None, False

    parts = _parse_key_path(key_path)
    current = data

    for part in parts:
        if isinstance(part, int):
            if isinstance(current, list) and len(current) > part:
                current = current[part]
            else:
                return None, False
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None, False

    return current, True


def _strip_jinja(content: str) -> str:
    """Remove all Jinja2 expressions and blocks from content."""
    import re
    result = re.sub(r'\{\{.*?\}\}', 'PLACEHOLDER', content)
    result = re.sub(r'\{%.*?%\}', '', result)
    return result


def _parse_key_path(key_path: str) -> list:
    """
    Parse 'spec.generationRules[0].slxs[0].qualifiers' into
    ['spec', 'generationRules', 0, 'slxs', 0, 'qualifiers']
    """
    parts = []
    for segment in key_path.split("."):
        if "[" in segment:
            name, rest = segment.split("[", 1)
            parts.append(name)
            idx = int(rest.rstrip("]"))
            parts.append(idx)
        else:
            parts.append(segment)
    return parts
