"""Tests for SHA-232: `action.yml` and the workflow in docs/github-action.md.

These read the files only. Running the action on GitHub is SHA-234's end-to-end test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION = REPO_ROOT / "action.yml"
DOC = REPO_ROOT / "docs" / "github-action.md"

EXPECTED_INPUTS = {
    "settings-module": None,
    "lockfile": "authz.lock",
    "python-version": "3.12",
    "fail-on-loosened": "true",
    "comment": "true",
    "working-directory": ".",
    "base-ref": "",
}


@pytest.fixture(scope="module")
def action_text() -> str:
    assert ACTION.is_file(), "action.yml is missing at the repository root"
    return ACTION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def action(action_text: str) -> dict[str, Any]:
    loaded = yaml.safe_load(action_text)
    assert isinstance(loaded, dict)
    return loaded


def _steps(action: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = action["runs"]["steps"]
    return steps


def _step(action: dict[str, Any], step_id: str) -> dict[str, Any]:
    matches = [step for step in _steps(action) if step.get("id") == step_id]
    assert len(matches) == 1, f"action.yml needs exactly one step with id {step_id!r}"
    return matches[0]


def test_t1_action_yml_inputs_defaults_and_no_secrets(
    action: dict[str, Any], action_text: str
) -> None:
    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert set(inputs) == set(EXPECTED_INPUTS)
    assert inputs["settings-module"]["required"] is True
    assert "default" not in inputs["settings-module"]
    for name, default in EXPECTED_INPUTS.items():
        assert inputs[name].get("description"), f"input {name} needs a description"
        if default is not None:
            assert inputs[name]["required"] is False, name
            assert str(inputs[name]["default"]) == default, name

    assert "secrets." not in action_text
    expressions = re.findall(r"\$\{\{(.*?)\}\}", action_text)
    tokens = {expr.strip() for expr in expressions if "token" in expr.lower()}
    assert tokens == {"github.token"}, "the only credential used is github.token"
    for step in _steps(action):
        if "uses" in step:
            assert "token" not in step.get("with", {}), step


def test_extra_run_steps_take_inputs_through_env_only(action: dict[str, Any]) -> None:
    """Expressions are never pasted into shell scripts, so input values cannot inject code."""
    run_steps = [step for step in _steps(action) if "run" in step]
    assert run_steps
    for step in run_steps:
        assert step.get("shell") == "bash", step.get("name")
        assert "${{" not in step["run"], f"step {step.get('name')!r} must use env, not ${{{{ }}}}"


def test_extra_comment_step_is_conditional_and_report_is_logged(action: dict[str, Any]) -> None:
    """AC5 at the file level: `comment: false` skips the comment; the diff is always logged."""
    diff = _step(action, "diff")
    assert "--format markdown" in diff["run"]
    assert '--base "$base"' in diff["run"]
    assert re.search(r'^\s*cat "\$report"\s*$', diff["run"], re.MULTILINE), "diff goes to the log"

    comment = _step(action, "comment")
    assert comment["if"].replace(" ", "") == "inputs.comment=='true'"
    assert comment["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "upsert-comment" in comment["run"]

    gate = _step(action, "gate")
    assert "if" not in gate, "the gate runs whether or not a comment is posted"
    assert gate["env"]["FAIL_ON_LOOSENED"] == "${{ inputs.fail-on-loosened }}"
    assert _steps(action)[-1] is gate

    outputs = action["outputs"]
    assert set(outputs) == {"report-path", "summary", "loosened"}


def _doc_yaml_blocks() -> list[Any]:
    text = DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"^```yaml\n(.*?)^```$", text, re.MULTILINE | re.DOTALL)
    return [yaml.safe_load(block) for block in blocks]


def test_extra_docs_workflow_snippet_uses_declared_inputs(action: dict[str, Any]) -> None:
    workflows = [
        block for block in _doc_yaml_blocks() if isinstance(block, dict) and "jobs" in block
    ]
    assert workflows, "docs/github-action.md needs a complete workflow example"
    workflow = workflows[0]

    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML parses `on` as True
    assert "pull_request" in triggers
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "write"}

    (job,) = workflow["jobs"].values()
    uses = [step for step in job["steps"] if "smhasan94/authzlock@" in step.get("uses", "")]
    assert len(uses) == 1
    with_inputs = uses[0]["with"]
    assert set(with_inputs) <= set(action["inputs"])
    assert "settings-module" in with_inputs
    assert any(step.get("uses", "").startswith("actions/checkout@") for step in job["steps"])

    text = DOC.read_text(encoding="utf-8")
    assert "pull-requests: write" in text and "contents: read" in text
    for name in action["inputs"]:
        assert f"`{name}`" in text, f"docs/github-action.md does not describe input {name}"
    for name in action["outputs"]:
        assert f"`{name}`" in text, f"docs/github-action.md does not describe output {name}"
