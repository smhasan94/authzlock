"""Tests for SHA-227: the lockfile is byte-identical across runs, directories and machines.

T1 to T5 run `authzlock update` in subprocesses (`run_cli`), because Django can only be set
up once per process. T5 compares with the golden files `tests/fixtures/<fixture>/
authz.lock*.expected`; run `pytest tests/test_determinism.py --update-golden` to rewrite them.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from authzlock import __version__
from authzlock.errors import EXIT_OK, LockfileError
from authzlock.lockfile import dump
from authzlock.model import Inventory, Route
from harness import FIXTURES, run_cli

# Every fixture that is a complete project; `minimal` adds nothing and `broken` cannot load.
DETERMINISM_FIXTURES = ("class_views", "drf_apiview", "drf_viewsets", "function_views")
SEEDS = ("0", "1", "2", "3", "random")


def _update(
    cwd: Path,
    *,
    fixture: str | None = None,
    env: dict[str, str | None] | None = None,
    lockfile: Path | None = None,
) -> bytes:
    """Run `authzlock update` and return the bytes of the lockfile it wrote."""
    target = lockfile or cwd / "authz.lock"
    result = run_cli(
        ["update", "--quiet", "--lockfile", str(target)], cwd=cwd, fixture=fixture, env=env
    )
    assert result.returncode == EXIT_OK, result.stderr
    return target.read_bytes()


def _minor(distribution: str) -> str:
    return ".".join(version(distribution).split(".")[:2])


def golden_candidates(fixture: str) -> list[Path]:
    """Golden files for `fixture`, most specific first; the first that exists is used.

    A version-specific file exists only where that Django or DRF release genuinely produces
    different routes, for example DRF 3.14's regex format-suffix patterns.
    """
    django, drf = _minor("django"), _minor("djangorestframework")
    directory = FIXTURES / fixture
    return [
        directory / f"authz.lock.drf-{drf}.expected",
        directory / f"authz.lock.django-{django}.expected",
        directory / "authz.lock.expected",
    ]


@pytest.mark.parametrize("fixture", DETERMINISM_FIXTURES)
def test_t1_hash_seeds_give_identical_bytes(fixture: str, tmp_path: Path) -> None:
    outputs = {
        seed: _update(
            tmp_path,
            fixture=fixture,
            env={"PYTHONHASHSEED": seed},
            lockfile=tmp_path / f"{seed}.lock",
        )
        for seed in SEEDS
    }

    assert len(set(outputs.values())) == 1, sorted(outputs)


@pytest.mark.parametrize("fixture", DETERMINISM_FIXTURES)
def test_t2_working_directory_does_not_matter(
    fixture: str, tmp_path: Path, repo_root: Path
) -> None:
    fixture_dir = FIXTURES / fixture
    empty = tmp_path / "empty"
    empty.mkdir()
    work = tmp_path / "work"
    work.mkdir()

    from_root = _update(repo_root, fixture=fixture, lockfile=tmp_path / "root.lock")
    from_temp = _update(work, fixture=fixture)
    # The same project with a different sys.path order: unrelated entries before and after.
    reordered = _update(
        work,
        fixture=fixture,
        env={"PYTHONPATH": os.pathsep.join(map(str, (empty, fixture_dir, repo_root / "tests")))},
        lockfile=tmp_path / "reordered.lock",
    )

    assert from_root == from_temp == reordered


@pytest.mark.parametrize("fixture", DETERMINISM_FIXTURES)
def test_t3_fixture_location_does_not_matter(fixture: str, tmp_path: Path) -> None:
    outputs = []
    for location in (tmp_path / "a", tmp_path / "b" / "deeper" / "checkout"):
        project = location / fixture
        shutil.copytree(FIXTURES / fixture, project, ignore=shutil.ignore_patterns("*.expected"))
        outputs.append(
            _update(
                project,
                env={"PYTHONPATH": str(project), "DJANGO_SETTINGS_MODULE": "settings"},
            )
        )

    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("fixture", DETERMINISM_FIXTURES)
def test_t4_no_machine_specific_strings(fixture: str, tmp_path: Path, repo_root: Path) -> None:
    text = _update(tmp_path, fixture=fixture).decode("utf-8")
    patterns = {
        "macOS home": r"/Users/",
        "Linux home": r"/home/",
        "Windows drive": r"[A-Za-z]:\\",
        "ISO date": r"\d{4}-\d{2}-\d{2}",
        "time of day": r"\b\d{1,2}:\d{2}(:\d{2})?\b",
        "authzlock version": r"authzlock[ =:v-]*\d+\.\d+",
        "installed version": re.escape(__version__),
        "hostname": re.escape(socket.gethostname()),
        "temp directory": re.escape(str(tmp_path)),
        "repo root": re.escape(str(repo_root)),
        "fixture directory": re.escape(str(FIXTURES)),
    }

    found = {label: re.findall(pattern, text) for label, pattern in patterns.items()}

    assert {label: hits for label, hits in found.items() if hits} == {}


@pytest.mark.parametrize("fixture", DETERMINISM_FIXTURES)
def test_t5_golden_lockfile_matches_in_every_cell(
    fixture: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    generated = _update(tmp_path, fixture=fixture)
    candidates = golden_candidates(fixture)
    golden = next((path for path in candidates if path.is_file()), candidates[-1])

    if request.config.getoption("--update-golden"):
        golden.write_bytes(generated)
        pytest.skip(f"wrote {golden.relative_to(FIXTURES)}")

    assert golden.is_file(), f"no golden file for {fixture}; run pytest --update-golden"
    assert generated == golden.read_bytes(), f"{fixture} differs from {golden.name}"


def _route(**overrides: Any) -> Route:
    fields: dict[str, Any] = {
        "path": "orders/",
        "name": "orders",
        "view": "shop.views.OrderView",
        "methods": ("GET",),
        "permission_classes": ("rest_framework.permissions.IsAuthenticated",),
        "permission_source": "view",
        "authentication_classes": ("rest_framework.authentication.SessionAuthentication",),
        "authentication_source": "settings-default",
    }
    fields.update(overrides)
    return Route(**fields)


@pytest.mark.parametrize(
    ("inventory", "where"),
    [
        pytest.param(
            Inventory(routes=(_route(view="/home/dev/project/shop/views.py"),)),
            "routes[0].view",
            id="posix-view",
        ),
        pytest.param(
            Inventory(routes=(_route(view="C:\\project\\shop\\views.py"),)),
            "routes[0].view",
            id="windows-view",
        ),
        pytest.param(
            Inventory(routes=(_route(view="\\\\server\\share\\views.py"),)),
            "routes[0].view",
            id="unc-view",
        ),
        pytest.param(
            Inventory(routes=(_route(permission_classes=("/Users/dev/perms.py",)),)),
            "routes[0].permission_classes",
            id="class-list",
        ),
        pytest.param(
            Inventory(
                routes=(_route(),),
                custom_permissions={"/Users/dev/perms.IsOwner": {"name": "IsOwner"}},
            ),
            "custom_permissions",
            id="custom-permission-key",
        ),
    ],
)
def test_t6_serializer_rejects_absolute_paths(inventory: Inventory, where: str) -> None:
    with pytest.raises(LockfileError, match=re.escape(where)):
        dump(inventory)


def test_extra_leading_slash_url_path_is_not_a_file_path() -> None:
    text = dump(Inventory(routes=(_route(path="/orders/"),)))

    assert "path: /orders/" in text
