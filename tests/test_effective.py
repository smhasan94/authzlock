"""Tests for SHA-239: per-method expansion of method-dependent DRF permissions."""

from __future__ import annotations

import subprocess
import sys

from authzlock.effective import (
    ALLOW_ANY,
    DJANGO_MODEL_PERMISSIONS,
    DJANGO_MODEL_PERMISSIONS_OR_ANON_READ_ONLY,
    IS_AUTHENTICATED,
    IS_AUTHENTICATED_OR_READ_ONLY,
    SAFE_METHODS,
    expand,
    is_expandable,
)

IS_OWNER = "shop.permissions.IsOwner"
COMPOSED = f"({IS_AUTHENTICATED_OR_READ_ONLY} | {IS_OWNER})"


def test_t1_is_authenticated_or_read_only_expands_per_method() -> None:
    result = expand([IS_AUTHENTICATED_OR_READ_ONLY], ["DELETE", "GET", "POST"])

    assert result == {
        "DELETE": (IS_AUTHENTICATED,),
        "GET": (ALLOW_ANY,),
        "POST": (IS_AUTHENTICATED,),
    }
    assert expand([IS_AUTHENTICATED_OR_READ_ONLY], ["HEAD", "OPTIONS"]) == {
        "HEAD": (ALLOW_ANY,),
        "OPTIONS": (ALLOW_ANY,),
    }


def test_t1_safe_methods_match_drf() -> None:
    # Importing DRF needs configured Django settings, so check in a child process.
    script = (
        "from django.conf import settings\n"
        "settings.configure()\n"
        "from rest_framework.permissions import SAFE_METHODS\n"
        "print(' '.join(sorted(SAFE_METHODS)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == sorted(SAFE_METHODS)


def test_t2_django_model_permissions_or_anon_read_only_expands_per_method() -> None:
    result = expand([DJANGO_MODEL_PERMISSIONS_OR_ANON_READ_ONLY], ["GET", "POST"])

    assert result == {"GET": (ALLOW_ANY,), "POST": (DJANGO_MODEL_PERMISSIONS,)}


def test_extra_allow_any_is_dropped_from_lists_with_other_members() -> None:
    result = expand([IS_AUTHENTICATED_OR_READ_ONLY, IS_OWNER], ["GET", "POST"])

    assert result == {"GET": (IS_OWNER,), "POST": (IS_AUTHENTICATED, IS_OWNER)}
    assert expand([ALLOW_ANY], ["POST"]) == {"POST": (ALLOW_ANY,)}
    assert expand([], ["GET"]) == {"GET": ()}


def test_extra_other_entries_are_copied_unchanged() -> None:
    result = expand([COMPOSED, IS_AUTHENTICATED], ["GET"])

    assert result == {"GET": (COMPOSED, IS_AUTHENTICATED)}
    assert not is_expandable([COMPOSED])
    assert is_expandable([IS_OWNER, IS_AUTHENTICATED_OR_READ_ONLY])
