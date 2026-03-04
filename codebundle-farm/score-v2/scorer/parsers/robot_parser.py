"""
Robot Framework file parser wrapping robot.api.TestSuite.

Evolved from runwhen-contrib/github-actions/codecollection-score/score.py.
Extracts structural information needed by the scoring rubric.
"""

import os
from dataclasses import dataclass, field
from robot.api import TestSuite


@dataclass
class KeywordCall:
    name: str
    args: list = field(default_factory=list)
    named_args: dict = field(default_factory=dict)


@dataclass
class TaskInfo:
    name: str
    doc: str = ""
    tags: list = field(default_factory=list)
    keyword_calls: list = field(default_factory=list)
    has_try_except: bool = False


@dataclass
class RobotFileInfo:
    filepath: str
    documentation: str = ""
    metadata: dict = field(default_factory=dict)
    suite_setup_name: str = ""
    libraries: list = field(default_factory=list)
    force_tags: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    imported_variables: dict = field(default_factory=dict)
    imported_secrets: list = field(default_factory=list)


def parse_robot_file(filepath: str) -> RobotFileInfo:
    """
    Parse a .robot file and extract all information the scorer needs.
    Returns a RobotFileInfo dataclass.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Robot file not found: {filepath}")

    suite = TestSuite.from_file_system(filepath)

    info = RobotFileInfo(filepath=filepath)
    info.documentation = suite.doc or ""
    info.metadata = dict(suite.metadata) if suite.metadata else {}

    if suite.setup:
        info.suite_setup_name = suite.setup.name or ""

    _extract_libraries_and_force_tags(filepath, info)
    _extract_keyword_data(suite, info)
    _extract_tasks(suite, info)

    return info


def _extract_libraries_and_force_tags(filepath: str, info: RobotFileInfo):
    """
    Extract Library imports and Force Tags from the raw file.
    robot.api.TestSuite doesn't directly expose library names, so we
    parse the model for these.
    """
    try:
        from robot.api.parsing import get_model
        model = get_model(filepath)
        for section in model.sections:
            section_type = type(section).__name__
            if "Setting" in section_type:
                for item in section.body:
                    item_type = type(item).__name__
                    if item_type == "LibraryImport":
                        lib_name = item.name or ""
                        if lib_name:
                            info.libraries.append(lib_name.strip())
                    elif item_type in ("ForceTags", "TestTags"):
                        for token in item.tokens:
                            if token.type in ("ARGUMENT", token.ARGUMENT):
                                info.force_tags.append(token.value.strip())
    except Exception:
        pass


def _extract_keyword_data(suite: TestSuite, info: RobotFileInfo):
    """
    Scan Keywords section for Suite Initialization to extract
    imported variables and secrets.
    """
    try:
        keywords = suite.resource.keywords
    except AttributeError:
        return

    for keyword in keywords:
        if "Suite Initialization" not in (keyword.name or ""):
            continue
        for statement in keyword.body:
            step_name = getattr(statement, "name", "") or ""
            step_args = list(getattr(statement, "args", []) or [])

            if "RW.Core.Import User Variable" in step_name and step_args:
                var_name = step_args[0]
                info.imported_variables[var_name] = var_name

            if "RW.Core.Import Secret" in step_name and step_args:
                secret_name = step_args[0]
                info.imported_secrets.append(secret_name)

            sub_body = getattr(statement, "body", None)
            if sub_body:
                _scan_keyword_body_for_imports(sub_body, info)


def _scan_keyword_body_for_imports(steps, info: RobotFileInfo):
    """Recursively scan nested keyword body for import statements."""
    for step in steps:
        step_name = getattr(step, "name", "") or ""
        step_args = list(getattr(step, "args", []) or [])

        if "RW.Core.Import User Variable" in step_name and step_args:
            info.imported_variables[step_args[0]] = step_args[0]
        if "RW.Core.Import Secret" in step_name and step_args:
            info.imported_secrets.append(step_args[0])

        sub_body = getattr(step, "body", None)
        if sub_body:
            _scan_keyword_body_for_imports(sub_body, info)


def _extract_tasks(suite: TestSuite, info: RobotFileInfo):
    """Extract task information from all tests in the suite."""
    for test in suite.tests:
        task = TaskInfo(
            name=test.name.strip(),
            doc=(test.doc or "").strip(),
            tags=[tag.strip() for tag in test.tags],
        )
        task.keyword_calls, task.has_try_except = _scan_steps(test.body)
        info.tasks.append(task)


def _scan_steps(steps) -> tuple:
    """
    Recursively scan steps extracting keyword calls and TRY/EXCEPT presence.
    Returns (keyword_calls, has_try_except).
    """
    calls = []
    has_try = False

    for step in steps:
        step_name = getattr(step, "name", "") or ""
        step_args = list(getattr(step, "args", []) or [])
        step_type = type(step).__name__

        if step_type in ("Try", "TryBranch") or "TRY" in step_type.upper():
            has_try = True

        if step_name:
            named_args = {}
            positional_args = []
            for arg in step_args:
                if "=" in arg and not arg.startswith("$"):
                    key, _, val = arg.partition("=")
                    named_args[key.strip()] = val.strip()
                else:
                    positional_args.append(arg)

            calls.append(KeywordCall(
                name=step_name,
                args=positional_args,
                named_args=named_args,
            ))

        sub_body = getattr(step, "body", None)
        if sub_body:
            sub_calls, sub_try = _scan_steps(sub_body)
            calls.extend(sub_calls)
            if sub_try:
                has_try = True

    return calls, has_try


def get_bash_file_references(robot_info: RobotFileInfo) -> list:
    """
    Extract all bash_file= references from RW.CLI.Run Bash File calls.
    Returns list of filenames referenced.
    """
    bash_files = []
    for task in robot_info.tasks:
        for call in task.keyword_calls:
            if "Run Bash File" in call.name:
                bf = call.named_args.get("bash_file", "")
                if bf:
                    bash_files.append(bf)
    return bash_files


def has_keyword_with_argument(robot_info: RobotFileInfo, keyword_pattern: str, argument_name: str) -> bool:
    """
    Check if any task calls a keyword matching keyword_pattern with
    the given named argument.
    """
    for task in robot_info.tasks:
        for call in task.keyword_calls:
            if keyword_pattern in call.name and argument_name in call.named_args:
                return True
    return False


def get_issue_call_arguments(robot_info: RobotFileInfo) -> list:
    """
    Return the named argument keys used in RW.Core.Add Issue calls.
    Returns a list of sets, one per call found.
    """
    issue_arg_sets = []
    for task in robot_info.tasks:
        for call in task.keyword_calls:
            if "RW.Core.Add Issue" in call.name:
                issue_arg_sets.append(set(call.named_args.keys()))
    return issue_arg_sets


def has_keyword_usage(robot_info: RobotFileInfo, keyword_name: str) -> bool:
    """Check if any task uses a keyword containing keyword_name."""
    for task in robot_info.tasks:
        for call in task.keyword_calls:
            if keyword_name in call.name:
                return True
    return False


def has_try_except(robot_info: RobotFileInfo) -> bool:
    """Check if any task uses TRY/EXCEPT blocks."""
    return any(task.has_try_except for task in robot_info.tasks)
