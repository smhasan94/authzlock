"""Tests for SHA-232: the sticky pull request comment and the exit logic of the GitHub Action.

`authzlock._github` is run the way `action.yml` runs it, as `python -m authzlock._github`
in a subprocess, with a fake `gh` first on `PATH`. The fake keeps the pull request's
comments in a JSON file, answers the three `gh api` calls the module makes (list, create,
update) and records every call, so no test talks to GitHub.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from authzlock import _github
from authzlock.diff import Diff, compute
from authzlock.model import Inventory, Route
from authzlock.render import MARKDOWN_MARKER, build_report, render_markdown

REPO = "octo/shop"
PR = 7
COMMENTS_PATH = f"repos/{REPO}/issues/{PR}/comments"

# The fake `gh`. It serves the comment list in pages of two so that `--paginate --slurp`
# matters, and fails on anything it does not know, including DELETE.
FAKE_GH = r"""
import json, os, sys

state_dir = os.environ["FAKE_GH_STATE"]
comments_file = os.path.join(state_dir, "comments.json")
calls_file = os.path.join(state_dir, "calls.jsonl")

args = sys.argv[1:]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(calls_file, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"args": args, "stdin": stdin}) + "\n")
with open(comments_file, encoding="utf-8") as fh:
    comments = json.load(fh)

def save():
    with open(comments_file, "w", encoding="utf-8") as fh:
        json.dump(comments, fh)

if os.environ.get("GH_TOKEN") != "fake-token":
    sys.exit("gh: GH_TOKEN not set")
if args[:1] != ["api"]:
    sys.exit("fake gh: only `gh api` is supported")
method = "GET"
if "-X" in args:
    method = args[args.index("-X") + 1]
path = [a for a in args[1:] if a.startswith("repos/")][0]

if method == "GET" and path.endswith("/comments"):
    pages = [comments[i:i + 2] for i in range(0, len(comments), 2)] or [[]]
    if "--paginate" in args and "--slurp" in args:
        print(json.dumps(pages))
    else:
        print(json.dumps(pages[0]))
elif method == "POST" and path.endswith("/comments"):
    body = json.loads(stdin)["body"]
    new_id = max([c["id"] for c in comments], default=100) + 1
    comment = {"id": new_id, "body": body, "created_at": "2026-10-01T12:00:00Z",
               "user": {"login": "github-actions[bot]"}}
    comments.append(comment)
    save()
    print(json.dumps(comment))
elif method == "PATCH" and "/issues/comments/" in path:
    comment_id = int(path.rsplit("/", 1)[1])
    for comment in comments:
        if comment["id"] == comment_id:
            comment["body"] = json.loads(stdin)["body"]
            save()
            print(json.dumps(comment))
            break
    else:
        sys.exit(f"fake gh: no comment {comment_id}")
else:
    sys.exit(f"fake gh: unsupported call {method} {path}")
"""


@dataclass
class FakeGh:
    state: Path
    env: dict[str, str]

    def seed(self, comments: list[dict[str, Any]]) -> None:
        (self.state / "comments.json").write_text(json.dumps(comments), encoding="utf-8")

    def comments(self) -> list[dict[str, Any]]:
        loaded: list[dict[str, Any]] = json.loads(
            (self.state / "comments.json").read_text(encoding="utf-8")
        )
        return loaded

    def calls(self) -> list[dict[str, Any]]:
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def methods(self) -> list[str]:
        return [
            call["args"][call["args"].index("-X") + 1] if "-X" in call["args"] else "GET"
            for call in self.calls()
        ]


@pytest.fixture
def fake_gh(tmp_path: Path) -> FakeGh:
    bin_dir = tmp_path / "bin"
    state = tmp_path / "gh-state"
    bin_dir.mkdir()
    state.mkdir()
    script = bin_dir / "gh"
    script.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
    script.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GH_STATE": str(state),
        "GH_TOKEN": "fake-token",
    }
    env.pop("GITHUB_OUTPUT", None)
    fake = FakeGh(state=state, env=env)
    fake.seed([])
    return fake


RunGithub = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def run_github(fake_gh: FakeGh) -> RunGithub:
    """Run `python -m authzlock._github <args>` with the fake `gh` on PATH."""

    def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "authzlock._github", *args],
            env={**fake_gh.env, **(env or {})},
            capture_output=True,
            text=True,
            check=False,
        )

    return _run


def _route(path: str, permission: str) -> Route:
    return Route(
        path=path,
        name=None,
        view=f"api.views.{path.strip('/').title()}View",
        methods=("GET",),
        permission_classes=(permission,),
        permission_source="view",
    )


ADMIN = "rest_framework.permissions.IsAdminUser"
AUTHENTICATED = "rest_framework.permissions.IsAuthenticated"
ALLOW_ANY = "rest_framework.permissions.AllowAny"


def _markdown(diff: Diff) -> str:
    return render_markdown(
        build_report(diff, ref="origin/main", lockfile="authz.lock", base_found=True)
    )


def _loosened_markdown() -> str:
    base = Inventory(routes=(_route("orders/", AUTHENTICATED),))
    current = Inventory(routes=(_route("orders/", ALLOW_ANY),))
    return _markdown(compute(base, current))


def _tightened_markdown() -> str:
    base = Inventory(routes=(_route("orders/", AUTHENTICATED),))
    current = Inventory(routes=(_route("orders/", ADMIN),))
    return _markdown(compute(base, current))


def _empty_markdown() -> str:
    inventory = Inventory(routes=(_route("orders/", AUTHENTICATED),))
    return _markdown(compute(inventory, inventory))


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _upsert(run_github: RunGithub, body_file: Path) -> subprocess.CompletedProcess[str]:
    return run_github(
        "upsert-comment", "--repo", REPO, "--pr", str(PR), "--body-file", str(body_file)
    )


def test_t2_upsert_creates_then_updates_comment(
    tmp_path: Path, fake_gh: FakeGh, run_github: RunGithub
) -> None:
    loosened = _loosened_markdown()
    assert "| loosened |" in loosened
    first = _upsert(run_github, _write(tmp_path, "first.md", loosened))

    assert first.returncode == 0, first.stderr
    assert fake_gh.methods() == ["GET", "POST"]
    comments = fake_gh.comments()
    assert len(comments) == 1
    assert comments[0]["body"].startswith(MARKDOWN_MARKER)
    assert "| loosened |" in comments[0]["body"]
    created_id = comments[0]["id"]
    assert all(call["args"][0] == "api" for call in fake_gh.calls())
    list_call = fake_gh.calls()[0]["args"]
    assert COMMENTS_PATH in list_call and "--paginate" in list_call

    second = _upsert(run_github, _write(tmp_path, "second.md", _tightened_markdown()))

    assert second.returncode == 0, second.stderr
    assert fake_gh.methods() == ["GET", "POST", "GET", "PATCH"]
    patch_call = fake_gh.calls()[-1]["args"]
    assert f"repos/{REPO}/issues/comments/{created_id}" in patch_call
    comments = fake_gh.comments()
    assert len(comments) == 1, "a second push must update the comment, not add one"
    assert comments[0]["id"] == created_id
    assert comments[0]["body"].startswith(MARKDOWN_MARKER)
    assert "| tightened |" in comments[0]["body"]
    assert "| loosened |" not in comments[0]["body"]


def test_t3_empty_diff_posts_no_changes_message(
    tmp_path: Path, fake_gh: FakeGh, run_github: RunGithub
) -> None:
    result = _upsert(run_github, _write(tmp_path, "empty.md", _empty_markdown()))

    assert result.returncode == 0, result.stderr
    (comment,) = fake_gh.comments()
    assert comment["body"].startswith(MARKDOWN_MARKER)
    # The CLI writes "No access-control changes against `origin/main`." as a sentence.
    assert "no access-control changes" in comment["body"].lower()
    clean = "0 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent"
    assert clean in comment["body"]

    # An empty report file (nothing captured) gets the same message rather than a blank comment.
    result = _upsert(run_github, _write(tmp_path, "blank.md", ""))
    assert result.returncode == 0, result.stderr
    (comment,) = fake_gh.comments()
    assert comment["body"].startswith(MARKDOWN_MARKER)
    assert "no access-control changes" in comment["body"]


@pytest.mark.parametrize(
    ("fail_on_loosened", "markdown", "expected_exit"),
    [
        pytest.param("true", _loosened_markdown, 1, id="true-loosened-fails"),
        pytest.param("true", _tightened_markdown, 0, id="true-tightened-passes"),
        pytest.param("false", _loosened_markdown, 0, id="false-loosened-passes"),
        pytest.param("false", _empty_markdown, 0, id="false-empty-passes"),
    ],
)
def test_t4_exit_logic_for_fail_on_loosened_combinations(
    tmp_path: Path,
    fake_gh: FakeGh,
    run_github: RunGithub,
    fail_on_loosened: str,
    markdown: Callable[[], str],
    expected_exit: int,
) -> None:
    report = _write(tmp_path, "report.md", markdown())
    loosened = _github.parse_summary(report.read_text(encoding="utf-8"))["loosened"]
    assert _github.should_fail(
        fail_on_loosened=fail_on_loosened == "true", loosened=loosened
    ) is bool(expected_exit)

    result = run_github("gate", "--report", str(report), "--fail-on-loosened", fail_on_loosened)

    assert result.returncode == expected_exit, result.stdout + result.stderr
    if expected_exit:
        assert "loosened" in result.stdout + result.stderr
    assert fake_gh.calls() == [], "the gate never calls GitHub"


def test_t4_gate_rejects_unknown_flag_value_and_missing_summary(
    tmp_path: Path, run_github: RunGithub
) -> None:
    report = _write(tmp_path, "report.md", _loosened_markdown())
    bad_flag = run_github("gate", "--report", str(report), "--fail-on-loosened", "yes")
    assert bad_flag.returncode == 2
    assert "fail-on-loosened" in bad_flag.stderr

    no_summary = _write(tmp_path, "garbled.md", "authzlock: something went wrong\n")
    garbled = run_github("gate", "--report", str(no_summary), "--fail-on-loosened", "true")
    assert garbled.returncode == 2
    assert "summary line" in garbled.stderr


def test_t6_multiple_marker_comments_update_newest_only(
    tmp_path: Path, fake_gh: FakeGh, run_github: RunGithub
) -> None:
    older = {
        "id": 10,
        "body": f"{MARKDOWN_MARKER}\nold run",
        "created_at": "2026-09-01T10:00:00Z",
        "user": {"login": "github-actions[bot]"},
    }
    unrelated = {
        "id": 15,
        "body": "Looks good to me.",
        "created_at": "2026-09-02T10:00:00Z",
        "user": {"login": "reviewer"},
    }
    newer = {
        "id": 20,
        "body": f"{MARKDOWN_MARKER}\nnewer run",
        "created_at": "2026-09-03T10:00:00Z",
        "user": {"login": "github-actions[bot]"},
    }
    fake_gh.seed([older, unrelated, newer])

    result = _upsert(run_github, _write(tmp_path, "report.md", _tightened_markdown()))

    assert result.returncode == 0, result.stderr
    assert fake_gh.methods() == ["GET", "PATCH"], "only the newest marker comment is touched"
    assert f"repos/{REPO}/issues/comments/20" in fake_gh.calls()[-1]["args"]
    by_id = {comment["id"]: comment for comment in fake_gh.comments()}
    assert set(by_id) == {10, 15, 20}, "no comment is deleted or added"
    assert by_id[10] == older
    assert by_id[15] == unrelated
    assert "| tightened |" in by_id[20]["body"]


def test_extra_newest_marker_comment_ignores_quotes_and_orders_by_time() -> None:
    comments = [
        {"id": 30, "body": f"> {MARKDOWN_MARKER}\n> quoted", "created_at": "2026-09-05T00:00:00Z"},
        {"id": 12, "body": f"{MARKDOWN_MARKER}\nb", "created_at": "2026-09-04T00:00:00Z"},
        {"id": 11, "body": f"\n{MARKDOWN_MARKER}\na", "created_at": "2026-09-01T00:00:00Z"},
    ]
    assert _github.find_comment(comments) == 12
    assert _github.find_comment([comments[0]]) is None


def test_extra_long_body_is_truncated_below_github_limit() -> None:
    body = _github.comment_body(MARKDOWN_MARKER + "\n" + "x" * 100_000)
    assert len(body) <= _github.MAX_BODY
    assert body.startswith(MARKDOWN_MARKER)
    assert "truncated" in body


def test_extra_outputs_written_to_github_output(tmp_path: Path, run_github: RunGithub) -> None:
    report = _write(tmp_path, "report.md", _loosened_markdown())
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")

    result = run_github("outputs", "--report", str(report), env={"GITHUB_OUTPUT": str(output)})

    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    summary = "1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent"
    assert f"summary={summary}" in lines
    assert "loosened=1" in lines


def test_extra_gh_failure_is_reported(tmp_path: Path, fake_gh: FakeGh) -> None:
    report = _write(tmp_path, "report.md", _loosened_markdown())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "authzlock._github",
            "upsert-comment",
            "--repo",
            REPO,
            "--pr",
            str(PR),
            "--body-file",
            str(report),
        ],
        env={**fake_gh.env, "GH_TOKEN": "wrong"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "gh api" in result.stderr
    assert fake_gh.comments() == []
