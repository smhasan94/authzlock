"""CLI tests for SHA-245: `update --ignore-path/--ignore-view/--no-ignore`, and `check` and
`diff` applying the recorded list.

Every test loads the `ignore_routes` fixture, which mounts the Django admin, in a
subprocess. Admin route counts differ across Django versions, so tests assert that no
`admin/` route is left and that the other routes equal an unfiltered run, never a count.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK
from harness import git, make_repo, project_env, run_cli

FIXTURE = "ignore_routes"
INTERNAL = "shop.internal.views"
INTERNAL_API = "shop.internal_api.views"
STOCK_KEEPER = "shop.permissions.IsStockKeeper"


def _update(cwd: Path, *args: str) -> dict[str, Any]:
    result = run_cli(["update", "--quiet", *args], cwd=cwd, fixture=FIXTURE)
    assert result.returncode == EXIT_OK, result.stderr
    return yaml.safe_load((cwd / "authz.lock").read_text(encoding="utf-8"))


def _paths(document: dict[str, Any]) -> list[str]:
    return [route["path"] for route in document["routes"]]


def _views(document: dict[str, Any]) -> list[str]:
    return [route["view"] for route in document["routes"]]


@pytest.fixture
def unfiltered(tmp_path: Path) -> dict[str, Any]:
    directory = tmp_path / "unfiltered"
    directory.mkdir()
    return _update(directory)


def test_t1_ignore_path_drops_admin_routes_and_records_prefix(
    tmp_path: Path, unfiltered: dict[str, Any]
) -> None:
    document = _update(tmp_path, "--ignore-path", "admin/")

    assert document["ignore"] == {"paths": ["admin/"]}
    assert not any(path.startswith("admin/") for path in _paths(document))
    assert any(path.startswith("admin/") for path in _paths(unfiltered))
    kept = [route for route in unfiltered["routes"] if not route["path"].startswith("admin/")]
    assert document["routes"] == kept
    assert document["custom_permissions"] == unfiltered["custom_permissions"]


def test_t2_ignore_view_matches_on_module_boundary(tmp_path: Path) -> None:
    document = _update(tmp_path, "--ignore-view", "shop.internal")

    assert document["ignore"] == {"views": ["shop.internal"]}
    assert not any(view.startswith(f"{INTERNAL}.") for view in _views(document))
    assert f"{INTERNAL_API}.status" in _views(document)
    # IsStockKeeper was only used by an ignored view.
    assert STOCK_KEEPER not in document["custom_permissions"]


def test_t3_lists_are_sorted_deduplicated_and_plain_run_has_no_key(
    tmp_path: Path, unfiltered: dict[str, Any]
) -> None:
    document = _update(
        tmp_path,
        *("--ignore-path", "internal/", "--ignore-path", "admin/", "--ignore-path", "admin/"),
        *("--ignore-view", "shop.internal_api", "--ignore-view", "shop.internal"),
    )

    assert document["ignore"] == {
        "paths": ["admin/", "internal/"],
        "views": ["shop.internal", "shop.internal_api"],
    }
    assert "ignore" not in unfiltered
    assert unfiltered["schema_version"] == document["schema_version"] == 1


def test_t4_update_keeps_replaces_or_clears_the_list(
    tmp_path: Path, unfiltered: dict[str, Any]
) -> None:
    _update(tmp_path, "--ignore-path", "admin/")

    kept = _update(tmp_path)
    assert kept["ignore"] == {"paths": ["admin/"]}
    assert not any(path.startswith("admin/") for path in _paths(kept))

    replaced = _update(tmp_path, "--ignore-path", "internal/")
    assert replaced["ignore"] == {"paths": ["internal/"]}
    assert any(path.startswith("admin/") for path in _paths(replaced))
    assert not any(path.startswith("internal/") for path in _paths(replaced))

    cleared = _update(tmp_path, "--no-ignore")
    assert cleared == unfiltered
    unfiltered_bytes = (tmp_path / "unfiltered" / "authz.lock").read_bytes()
    assert (tmp_path / "authz.lock").read_bytes() == unfiltered_bytes


def test_extra_no_ignore_with_ignore_option_exits_2(tmp_path: Path) -> None:
    result = run_cli(
        ["update", "--no-ignore", "--ignore-path", "admin/"], cwd=tmp_path, fixture=FIXTURE
    )

    assert result.returncode == EXIT_ERROR
    assert "--no-ignore" in result.stderr
    assert not (tmp_path / "authz.lock").exists()


def test_t5_check_applies_lockfile_list_without_options(tmp_path: Path) -> None:
    _update(tmp_path, "--ignore-path", "admin/")

    clean = run_cli(["check"], cwd=tmp_path, fixture=FIXTURE)
    assert clean.returncode == EXIT_OK, clean.stdout + clean.stderr

    lock = tmp_path / "authz.lock"
    text = lock.read_text(encoding="utf-8")
    without_key, removed = re.subn(r"^ignore:\n(?:  .*\n)+", "", text, flags=re.MULTILINE)
    assert removed == 1
    lock.write_text(without_key, encoding="utf-8")

    stale = run_cli(["check"], cwd=tmp_path, fixture=FIXTURE)
    assert stale.returncode == EXIT_MISMATCH
    added_group = stale.stdout.split("added:\n", 1)[1]
    added_keys = []
    for line in added_group.splitlines():
        if not line.startswith("  "):
            break
        added_keys.append(line.strip())
    assert added_keys, stale.stdout
    assert all(" admin/" in key for key in added_keys), added_keys
    assert "removed:" not in stale.stdout
    assert "changed:" not in stale.stdout


def test_t6_diff_reports_ignored_routes_removed_with_note(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)
    update = run_cli(["update", "--ignore-path", "admin/"], cwd=repo, env=project_env(repo))
    assert update.returncode == EXIT_OK, update.stderr

    text = run_cli(["diff", "--base", "HEAD"], cwd=repo, env=project_env(repo))
    markdown = run_cli(
        ["diff", "--base", "HEAD", "--format", "markdown"], cwd=repo, env=project_env(repo)
    )

    assert text.returncode == EXIT_MISMATCH, text.stderr
    notes = [line for line in text.stdout.splitlines() if line.startswith("note: ")]
    assert len(notes) == 1, text.stdout
    assert "ignore list changed from nothing at HEAD to paths [admin/]" in notes[0]
    removed = [line for line in text.stdout.splitlines() if line.startswith("removed ")]
    assert removed
    assert all(" admin/" in line for line in removed)
    assert not [line for line in text.stdout.splitlines() if line.startswith("added ")]
    assert markdown.stdout.count("> **Note:** ignore list changed") == 1


def test_extra_diff_without_list_change_has_no_note(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path, lockfile=None)
    update = run_cli(["update", "--ignore-path", "admin/"], cwd=repo, env=project_env(repo))
    assert update.returncode == EXIT_OK, update.stderr
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", "lockfile with ignore list")

    result = run_cli(["diff", "--base", "HEAD"], cwd=repo, env=project_env(repo))

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert "note:" not in result.stdout
