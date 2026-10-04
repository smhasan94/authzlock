"""Tests for SHA-306: the route ignore lists in `diff --format json` and `--format sarif`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from authzlock.model import IgnoreList
from authzlock.render import ignore_note
from harness import make_repo, project_env, run_cli

SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "docs" / "diff.schema.json").read_text("utf-8")
)
EMPTY = {"paths": [], "views": []}
SCOPED = {"paths": ["scoped/"], "views": []}
NOTE = ignore_note("HEAD", IgnoreList(), IgnoreList.of(["scoped/"]))


def _diff(repo: Path, output_format: str) -> tuple[int, dict[str, Any]]:
    result = run_cli(
        ["diff", "--base", "HEAD", "--format", output_format], cwd=repo, env=project_env(repo)
    )
    assert result.stderr == "", result.stderr
    return result.returncode, json.loads(result.stdout)


def _notes(log: dict[str, Any]) -> list[str]:
    [run] = log["runs"]
    [invocation] = run["invocations"]
    return [note["message"]["text"] for note in invocation.get("toolExecutionNotifications", [])]


@pytest.fixture
def ignore_added(tmp_path: Path) -> Path:
    """drf_apiview committed without an ignore list; the working tree ignores `scoped/`."""
    repo = make_repo("drf_apiview", tmp_path)
    result = run_cli(["update", "--ignore-path", "scoped/"], cwd=repo, env=project_env(repo))
    assert result.returncode == 0, result.stderr
    return repo


def test_t1_json_reports_both_lists_and_the_dropped_routes(ignore_added: Path) -> None:
    code, document = _diff(ignore_added, "json")

    jsonschema.validate(document, SCHEMA)
    assert code == 1
    assert list(document)[:5] == ["schema_version", "tool", "base", "ignore", "summary"]
    assert document["ignore"] == {"base": EMPTY, "current": SCOPED, "changed": True}
    removed = [c["route"]["path"] for c in document["changes"] if c["label"] == "removed"]
    assert removed and all(path.startswith("scoped/") for path in removed)
    assert len(removed) == len(document["changes"])


def test_t2_sarif_carries_the_text_output_note(ignore_added: Path) -> None:
    _, log = _diff(ignore_added, "sarif")
    text = run_cli(["diff", "--base", "HEAD"], cwd=ignore_added, env=project_env(ignore_added))

    assert _notes(log) == [NOTE]
    assert NOTE in text.stdout


def test_t3_unchanged_list_gives_changed_false_and_no_note(tmp_path: Path) -> None:
    repo = make_repo("drf_apiview", tmp_path)

    _, document = _diff(repo, "json")
    _, log = _diff(repo, "sarif")
    _, again = _diff(repo, "json")

    assert document["ignore"] == {"base": EMPTY, "current": EMPTY, "changed": False}
    assert _notes(log) == []
    assert document == again


def test_t3_missing_base_lockfile_and_a_recorded_list_give_both_notes(tmp_path: Path) -> None:
    repo = make_repo("drf_apiview", tmp_path, lockfile=None)
    result = run_cli(["update", "--ignore-path", "scoped/"], cwd=repo, env=project_env(repo))
    assert result.returncode == 0, result.stderr

    _, document = _diff(repo, "json")
    _, log = _diff(repo, "sarif")

    assert document["base"]["lockfile_found"] is False
    assert document["ignore"] == {"base": EMPTY, "current": SCOPED, "changed": True}
    notes = _notes(log)
    assert len(notes) == 2
    assert notes[0].startswith("base ref has no authz.lock")
    assert notes[1] == NOTE


def test_t4_docs_name_rules_r1_to_r10(repo_root: Path) -> None:
    page = (repo_root / "docs" / "diff-json.md").read_text(encoding="utf-8")

    assert "`R1` to `R10`" in page
    assert "`R1` to `R9`" not in page
