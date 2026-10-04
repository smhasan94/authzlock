"""Tests for SHA-241: `authzlock diff --format json` and `--format sarif`.

CLI tests build a temporary git repository from a fixture with `make_repo` and run the CLI
in a subprocess, because Django can only be set up once per process. Document and SARIF
structure tests use hand-built diffs and never load a project.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from authzlock import __version__
from authzlock.classify import Classification, ClassifiedRoute, Label
from authzlock.diff import Diff, compute
from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK
from authzlock.model import Inventory, Route
from authzlock.render import DiffReport, build_report, to_document
from authzlock.sarif import FINGERPRINT, LEVELS, to_sarif
from harness import git, make_repo, project_env, run_cli

DOCS = Path(__file__).resolve().parent.parent / "docs"
SCHEMA = json.loads((DOCS / "diff.schema.json").read_text(encoding="utf-8"))
SCENARIO_KEY = "DELETE,GET invoices/<int:pk>/ -> billing.views.InvoiceDetailView"
ORIGINAL = "    permission_classes = [IsAuthenticated, IsOwner]\n"
LOOSENED = "    permission_classes = [IsAuthenticated]\n"


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} not found exactly once in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _diff(repo: Path, *args: str) -> Any:
    return run_cli(["diff", "--base", "HEAD", *args], cwd=repo, env=project_env(repo))


def _json(repo: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = _diff(repo, "--format", "json", *args)
    assert result.stderr == "", result.stderr
    return result.returncode, json.loads(result.stdout)


def _sarif(repo: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = _diff(repo, "--format", "sarif", *args)
    assert result.stderr == "", result.stderr
    return result.returncode, json.loads(result.stdout)


@pytest.fixture
def loosened_repo(tmp_path: Path) -> Path:
    repo = make_repo("scenario_loosen", tmp_path)
    _replace(repo / "billing" / "views.py", ORIGINAL, LOOSENED)
    return repo


def test_t1_json_on_scenario_validates_against_schema_and_counts_one_loosened(
    loosened_repo: Path,
) -> None:
    code, document = _json(loosened_repo)

    jsonschema.validate(document, SCHEMA)
    assert code == EXIT_MISMATCH
    assert document["summary"] == {
        "loosened": 1,
        "tightened": 0,
        "added": 0,
        "removed": 0,
        "changed_unknown": 0,
        "equivalent": 0,
    }
    assert document["tool"] == {"name": "authzlock", "version": __version__}
    [change] = document["changes"]
    assert change["label"] == "loosened"
    assert change["rule"] == "R2"
    assert change["route"]["key"] == SCENARIO_KEY


def test_t2_field_values_are_lockfile_values() -> None:
    composed = "(billing.permissions.IsOwner | rest_framework.permissions.IsAdminUser)"
    base = Route(
        path="a/",
        name=None,
        view="shop.views.A",
        methods=("GET",),
        permission_classes=("shop.permissions.CanShip", composed),
        authentication_classes=None,
    )
    current = Route(
        path="a/",
        name=None,
        view="shop.views.A",
        methods=("GET",),
        permission_classes="dynamic",
        authentication_classes=("rest_framework.authentication.SessionAuthentication",),
    )
    diff = compute(Inventory(routes=(base,)), Inventory(routes=(current,)))
    report = build_report(diff, ref="main", lockfile="authz.lock", base_found=True)

    document = to_document(report, {})

    jsonschema.validate(document, SCHEMA)
    [change] = document["changes"]
    fields = {entry["field"]: (entry["old"], entry["new"]) for entry in change["fields"]}
    assert fields["permission_classes"] == (["shop.permissions.CanShip", composed], "dynamic")
    assert fields["authentication_classes"] == (
        None,
        ["rest_framework.authentication.SessionAuthentication"],
    )
    assert change["location"] == {"file": "authz.lock", "line": 1}


def _entry(label: Label, path: str, rule: str | None = None) -> ClassifiedRoute:
    route = Route(path=path, name=None, view=f"shop.views.V{path[0]}", methods=("GET",))
    return ClassifiedRoute(
        key=route.key(), route=route, classification=Classification(label, rule, label)
    )


def _all_labels_report() -> DiffReport:
    entries = (
        _entry("added", "a/"),
        _entry("changed-unknown", "c/", "R8"),
        _entry("loosened", "l/", "R2"),
        _entry("removed", "r/"),
        _entry("tightened", "t/", "R1"),
    )
    return DiffReport(
        ref="main", lockfile="authz.lock", base_found=True, diff=Diff(), entries=entries
    )


def test_t3_sarif_structure_rules_levels_and_fingerprints() -> None:
    report = _all_labels_report()
    locations = {entry.key: ("shop/views.py", 3) for entry in report.entries}

    log = to_sarif(to_document(report, locations))

    assert log["version"] == "2.1.0"
    assert log["$schema"].startswith("https://")
    [run] = log["runs"]
    driver = run["tool"]["driver"]
    assert (driver["name"], driver["version"]) == ("authzlock", __version__)
    rule_ids = {rule["id"] for rule in driver["rules"]}
    assert rule_ids == set(LEVELS)
    assert LEVELS == {
        "loosened": "error",
        "changed-unknown": "warning",
        "added": "warning",
        "tightened": "note",
        "removed": "note",
        "equivalent": "note",
    }
    assert len(run["results"]) == 5
    for result, entry in zip(run["results"], report.entries, strict=True):
        assert result["ruleId"] == entry.classification.label
        assert result["level"] == LEVELS[result["ruleId"]]
        assert entry.key in result["message"]["text"]
        assert result["partialFingerprints"] == {FINGERPRINT: entry.key}
        [location] = result["locations"]
        physical = location["physicalLocation"]
        assert physical["artifactLocation"]["uri"] == "shop/views.py"
        assert physical["region"] == {"startLine": 3}
    assert "toolExecutionNotifications" not in run["invocations"][0]


def test_t4_location_is_repo_relative_view_line_and_removed_route_falls_back(
    tmp_path: Path,
) -> None:
    repo = make_repo("scenario_loosen", tmp_path)
    urls = repo / "urls.py"
    extra = '    path("archive/<int:pk>/", views.InvoiceDetailView.as_view(), name="archive"),\n'
    _replace(urls, "]\n", f"{extra}]\n")
    assert run_cli(["update"], cwd=repo, env=project_env(repo)).returncode == 0
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", "archive route")
    _replace(urls, extra, "")
    views = repo / "billing" / "views.py"
    _replace(views, ORIGINAL, LOOSENED)
    view_line = (
        views.read_text(encoding="utf-8")
        .splitlines()
        .index("class InvoiceDetailView(generics.RetrieveDestroyAPIView):")
        + 1
    )

    _, document = _json(repo)

    by_label = {change["label"]: change for change in document["changes"]}
    assert set(by_label) == {"loosened", "removed"}
    assert by_label["loosened"]["location"] == {"file": "billing/views.py", "line": view_line}
    assert by_label["removed"]["location"] == {"file": "authz.lock", "line": 1}


def test_t5_empty_diff_gives_empty_changes_and_results_exit_0(tmp_path: Path) -> None:
    repo = make_repo("scenario_loosen", tmp_path)

    json_code, document = _json(repo)
    sarif_code, log = _sarif(repo, "--quiet")

    assert json_code == sarif_code == EXIT_OK
    jsonschema.validate(document, SCHEMA)
    assert document["changes"] == []
    assert set(document["summary"].values()) == {0}
    assert log["runs"][0]["results"] == []


def test_t6_exit_codes_and_fail_on_unchanged_and_errors_leave_stdout_empty(
    loosened_repo: Path, tmp_path: Path
) -> None:
    assert _sarif(loosened_repo)[0] == EXIT_MISMATCH

    tightened = make_repo("drf_apiview", tmp_path / "tightened")
    _replace(
        tightened / "api" / "views.py",
        "class ExplicitView(APIView):\n    permission_classes = [IsAuthenticated]\n",
        "class ExplicitView(APIView):\n    permission_classes = [IsAdminUser]\n",
    )
    code, document = _json(tightened, "--fail-on", "loosened")
    assert code == EXIT_OK
    assert document["summary"]["tightened"] == 1

    for output_format in ("json", "sarif"):
        result = run_cli(
            ["diff", "--base", "no-such-ref", "--format", output_format],
            cwd=loosened_repo,
            env=project_env(loosened_repo),
        )
        assert result.returncode == EXIT_ERROR
        assert result.stdout == ""
        assert "no-such-ref" in result.stderr


def test_t7_two_runs_are_byte_identical_and_contain_no_absolute_path(
    loosened_repo: Path,
) -> None:
    for output_format in ("json", "sarif"):
        first = _diff(loosened_repo, "--format", output_format).stdout
        second = _diff(loosened_repo, "--format", output_format).stdout

        assert first == second
        for root in {str(loosened_repo), str(loosened_repo.resolve())}:
            assert root not in first


def test_t8_base_without_lockfile_sets_lockfile_found_false_and_notification(
    tmp_path: Path,
) -> None:
    repo = make_repo("scenario_loosen", tmp_path, lockfile=None)

    _, document = _json(repo)
    _, log = _sarif(repo)

    jsonschema.validate(document, SCHEMA)
    assert document["base"]["lockfile_found"] is False
    assert document["changes"]
    assert {change["label"] for change in document["changes"]} == {"added"}
    assert all(change["rule"] is None for change in document["changes"])
    fields = document["changes"][0]["fields"]
    permission = next(field for field in fields if field["field"] == "permission_classes")
    assert permission["old"] is None
    assert permission["new"]
    [notification] = log["runs"][0]["invocations"][0]["toolExecutionNotifications"]
    assert "no authz.lock" in notification["message"]["text"]


def _schema_keys(node: dict[str, Any], prefix: str = "") -> set[str]:
    """Dotted key paths of a JSON Schema's object properties; `[]` marks list items."""
    if "$ref" in node:
        node = SCHEMA["$defs"][node["$ref"].rsplit("/", 1)[1]]
    keys: set[str] = set()
    for name, child in node.get("properties", {}).items():
        path = f"{prefix}{name}"
        keys.add(path)
        keys |= _schema_keys(child, f"{path}.")
        items = child.get("items")
        if isinstance(items, dict):
            keys |= _schema_keys(items, f"{path}[].")
    return keys


def test_t9_docs_keys_match_schema_and_workflow_snippet_uses_upload_sarif() -> None:
    page = (DOCS / "diff-json.md").read_text(encoding="utf-8")
    keys_section = page.split("## Keys", 1)[1]
    documented = set(re.findall(r"^\| `([^`]+)` \|", keys_section, re.MULTILINE))

    assert documented == _schema_keys(SCHEMA)

    cli = (DOCS / "cli.md").read_text(encoding="utf-8")
    section = cli.split("### SARIF and GitHub code scanning", 1)[1].split("\n### ", 1)[0]
    [snippet] = re.findall(r"```yaml\n(.*?)```", section, re.DOTALL)
    workflow = yaml.safe_load(snippet)
    steps = workflow["jobs"]["authzlock"]["steps"]
    uses = [step.get("uses", "") for step in steps]
    assert any(use.startswith("github/codeql-action/upload-sarif@") for use in uses)
    assert any("--format sarif" in step.get("run", "") for step in steps)
    assert workflow["permissions"]["security-events"] == "write"


def test_extra_document_example_in_docs_validates() -> None:
    page = (DOCS / "diff-json.md").read_text(encoding="utf-8")
    [example] = re.findall(r"```json\n(.*?)```", page, re.DOTALL)

    jsonschema.validate(json.loads(example), SCHEMA)


def test_extra_text_output_unchanged_by_new_formats(loosened_repo: Path) -> None:
    result = _diff(loosened_repo)

    assert result.returncode == EXIT_MISMATCH
    assert result.stdout.splitlines()[-1] == (
        "1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent"
    )
    assert not result.stdout.lstrip().startswith("{")
