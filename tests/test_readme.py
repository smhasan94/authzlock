"""Tests for SHA-235: the README stays true to the tool.

T1 runs the README quickstart, the shell blocks whose fence info string is `sh quickstart`,
in a temporary git repository holding a copy of the `drf_viewsets` fixture, and compares the
`authzlock diff` output shown in the README with the real output; run
`pytest tests/test_readme.py --update-docs` to rewrite that block. The other tests compare
the README's lockfile excerpt, rule table and integration snippets with their sources.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.main import get_command

from authzlock import lockfile
from authzlock.cli import app
from authzlock.errors import EXIT_OK
from harness import FIXTURES, GIT_ENV, make_repo

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
FIXTURE = "drf_viewsets"
VIEWS = Path("billing") / "views.py"
# The edit the README asks the reader to make between the quickstart blocks.
ADMIN_ONLY = 'methods=["post"], permission_classes=[IsAdminUser]'
ANY_USER = 'methods=["post"], permission_classes=[IsAuthenticated]'
# The README uses this settings module; the fixture's is `settings`.
README_SETTINGS = "mysite.settings"
FIXTURE_SETTINGS = "settings"
EXPECTED_EXIT = re.compile(r"#\s*exits (\d+)\b")
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```$", re.DOTALL | re.MULTILINE)
DIFF_BLOCK = re.compile(r"(<!-- readme-diff:start -->\n)(.*?)(<!-- readme-diff:end -->)", re.DOTALL)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _blocks(text: str, info: str) -> list[str]:
    """Bodies of the fenced code blocks whose info string is exactly `info`."""
    return [body for found, body in FENCE.findall(text) if found.strip() == info]


def _section(text: str, heading: str) -> str:
    """The body of the `## heading` section, up to the next level-2 heading."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.M)
    assert match, f"README has no '## {heading}' section"
    return match.group(1)


# T1 ---------------------------------------------------------------------------------------


def _shell_env() -> dict[str, str]:
    """The reader's shell: no project settings, this interpreter's `authzlock` first on PATH."""
    env = {k: v for k, v in os.environ.items() if k not in {"DJANGO_SETTINGS_MODULE", "PYTHONPATH"}}
    for key, value in GIT_ENV.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def _run_block(block: str, repo: Path, env: dict[str, str]) -> list[str]:
    """Run each command line of `block` in `repo`; return the outputs of the diff commands.

    A line ending in `# exits N` must exit with N, every other line with 0. `export` lines
    set a variable for the following lines, as they would in the reader's shell.
    """
    diff_outputs: list[str] = []
    for line in block.splitlines():
        command = line.split("#", 1)[0].strip()
        if not command:
            continue
        expected = EXPECTED_EXIT.search(line)
        expected_code = int(expected.group(1)) if expected else EXIT_OK
        if command.startswith("export "):
            name, _, value = command.removeprefix("export ").partition("=")
            env[name] = value.replace(README_SETTINGS, FIXTURE_SETTINGS)
            continue
        assert "mysite" not in command, f"unexpected project-specific command: {line}"
        result = subprocess.run(
            shlex.split(command), cwd=repo, env=env, capture_output=True, text=True, check=False
        )
        assert result.returncode == expected_code, (
            f"`{command}` exited {result.returncode}, README says {expected_code}\n"
            f"{result.stdout}{result.stderr}"
        )
        if " diff " in f" {command} ":
            diff_outputs.append(result.stdout)
    return diff_outputs


def _apply_readme_edit(repo: Path) -> None:
    path = repo / VIEWS
    text = path.read_text(encoding="utf-8")
    assert text.count(ADMIN_ONLY) == 1, f"{ADMIN_ONLY!r} not found exactly once in {path}"
    path.write_text(text.replace(ADMIN_ONLY, ANY_USER), encoding="utf-8")


def test_t1_quickstart_commands_run_as_documented(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    text = _readme()
    blocks = _blocks(text, "sh quickstart")
    assert len(blocks) == 3, f"expected 3 `sh quickstart` blocks, found {len(blocks)}"
    # The README shows the edit the test makes between the first and second block.
    edit = [body for body in _blocks(text, "diff") if "IsAdminUser" in body]
    assert len(edit) == 1, "README must show the IsAdminUser edit as one ```diff block"
    assert f"-    @action(detail=True, {ADMIN_ONLY})" in edit[0]
    assert f"+    @action(detail=True, {ANY_USER})" in edit[0]

    repo = make_repo(FIXTURE, tmp_path, lockfile=None)
    env = _shell_env()
    assert _run_block(blocks[0], repo, env) == []
    assert (repo / "authz.lock").is_file()
    _apply_readme_edit(repo)
    diffs = _run_block(blocks[1], repo, env)
    assert len(diffs) == 1, "the second quickstart block must run `authzlock diff` once"
    assert _run_block(blocks[2], repo, env) == []

    shown = f"```text\n{diffs[0]}```\n"
    if request.config.getoption("--update-docs"):
        assert DIFF_BLOCK.search(text), "no readme-diff markers in README.md"
        README.write_text(
            DIFF_BLOCK.sub(lambda m: m.group(1) + shown + m.group(3), text), encoding="utf-8"
        )
        pytest.skip("rewrote the readme-diff block in README.md")
    match = DIFF_BLOCK.search(text)
    assert match, "no <!-- readme-diff:start --> / <!-- readme-diff:end --> markers in README"
    assert match.group(2) == shown, (
        "README diff output is stale; run `pytest tests/test_readme.py --update-docs`"
    )


# T2 ---------------------------------------------------------------------------------------


def _golden_routes() -> dict[tuple[str, str], dict[str, Any]]:
    data = yaml.safe_load((FIXTURES / FIXTURE / "authz.lock.expected").read_text("utf-8"))
    return {(route["path"], route["view"]): route for route in data["routes"]}


def test_t2_lockfile_excerpt_loads() -> None:
    excerpts = [body for body in _blocks(_readme(), "yaml") if body.startswith("schema_version:")]
    assert len(excerpts) == 1, "README must hold one lockfile excerpt starting schema_version:"

    inventory = lockfile.load(excerpts[0])

    assert inventory.routes, "the lockfile excerpt has no routes"
    # The excerpt is real: every route in it is a route of the drf_viewsets golden lockfile.
    golden = _golden_routes()
    for route in yaml.safe_load(excerpts[0])["routes"]:
        key = (route["path"], route["view"])
        assert key in golden, f"{key} is not a route of {FIXTURE}"
        assert route == golden[key], f"README excerpt of {key} differs from the golden file"


# T3 ---------------------------------------------------------------------------------------

RULE_ROW = re.compile(r"^\| (R\d+) \|.*\|$", re.MULTILINE)


def test_t3_classification_rules_match_docs() -> None:
    docs = (REPO_ROOT / "docs" / "classification.md").read_text(encoding="utf-8")
    readme = _readme()

    readme_ids = set(RULE_ROW.findall(readme))
    assert readme_ids == set(RULE_ROW.findall(docs))
    assert {f"R{n}" for n in range(1, 9)} <= readme_ids
    # The table is a verbatim copy, so every row matches too.
    doc_rows = [m.group(0) for m in RULE_ROW.finditer(docs)]
    readme_rows = [m.group(0) for m in RULE_ROW.finditer(readme)]
    assert readme_rows == doc_rows


# T4 ---------------------------------------------------------------------------------------

EXCLUSIONS = {
    "FastAPI": "FastAPI",
    "custom permission logic": "custom permission",
    "black-box testing of a running app": "running app",
    "generated tests": "generate",
}


def test_t4_does_not_do_section_lists_four_exclusions() -> None:
    section = _section(_readme(), "What authzlock does not do")
    items = re.findall(r"^- (.+(?:\n  .+)*)", section, re.MULTILINE)

    assert len(items) == 4, items
    for label, phrase in EXCLUSIONS.items():
        matching = [item for item in items if phrase in item]
        assert len(matching) == 1, f"one item must cover {label} ({phrase!r}): {items}"


# T5 ---------------------------------------------------------------------------------------


def _action_steps(text: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for body in _blocks(text, "yaml"):
        if "uses: smhasan94/authzlock" not in body:
            continue
        workflow = yaml.safe_load(body)
        for job in workflow["jobs"].values():
            steps.extend(s for s in job["steps"] if "smhasan94/authzlock" in s.get("uses", ""))
    return steps


def test_t5_action_snippet_inputs_exist_in_action_yml() -> None:
    action = yaml.safe_load((REPO_ROOT / "action.yml").read_text(encoding="utf-8"))
    inputs: dict[str, Any] = action["inputs"]
    required = {name for name, spec in inputs.items() if spec.get("required")}
    text = _readme()

    steps = _action_steps(text)

    assert steps, "README has no workflow snippet that uses smhasan94/authzlock"
    for step in steps:
        assert step["uses"] == "smhasan94/authzlock@v1"
        given = set(step.get("with", {}))
        assert given <= set(inputs), f"inputs not in action.yml: {given - set(inputs)}"
        assert required <= given, f"required inputs missing: {required - given}"
    # The pre-commit snippet names hooks that .pre-commit-hooks.yaml defines.
    hooks = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    hook_ids = {hook["id"] for hook in hooks}
    configs = [yaml.safe_load(b) for b in _blocks(text, "yaml") if b.startswith("repos:")]
    assert configs, "README has no .pre-commit-config.yaml snippet"
    used = {hook["id"] for config in configs for repo in config["repos"] for hook in repo["hooks"]}
    assert used and used <= hook_ids, used - hook_ids


# T6 ---------------------------------------------------------------------------------------

INLINE_CODE = re.compile(r"`([^`\n]+)`")
INVOCATION = re.compile(r"\bauthzlock[ \t]+(-{0,2}[A-Za-z][\w-]*)")


def _code(text: str) -> str:
    """Every fenced block and inline code span of `text`, joined by newlines."""
    fenced = [body for _, body in FENCE.findall(text)]
    prose = FENCE.sub("", text)
    return "\n".join(fenced + INLINE_CODE.findall(prose))


def _cli_words() -> set[str]:
    group = get_command(app)
    commands = set(getattr(group, "commands", {}))
    return commands | {"--version"}


def test_t6_no_undocumented_cli_commands_in_readme() -> None:
    allowed = _cli_words()
    assert allowed == {"update", "check", "diff", "gen-tests", "--version"}, allowed

    used = set(INVOCATION.findall(_code(_readme())))

    assert {"update", "check", "diff"} <= used, used
    assert used <= allowed, f"README uses commands the CLI does not define: {used - allowed}"


def test_t6_checker_flags_an_unknown_command() -> None:
    fake = "Run `authzlock lint` first.\n\n```sh\npython -m authzlock verify\n```\n"

    assert set(INVOCATION.findall(_code(fake))) - _cli_words() == {"lint", "verify"}
