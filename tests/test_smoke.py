"""Smoke tests for SHA-183 (T1, T3) and SHA-272 (T2, T3)."""

from __future__ import annotations

import os

import pytest

import authzlock


def test_t1_version_is_nonempty_string() -> None:
    assert isinstance(authzlock.__version__, str)
    assert authzlock.__version__


def test_t3_django_version_matches_session() -> None:
    expected = os.environ.get("AUTHZLOCK_DJANGO")
    if not expected:
        pytest.skip("AUTHZLOCK_DJANGO is only set inside nox test sessions")
    django = pytest.importorskip("django")
    assert django.get_version().startswith(expected + ".")


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".")[:2])


def test_t2_drf_version_matches_session() -> None:
    """SHA-272 T2 in the tests_min_drf session, T3 in every other nox tests session."""
    if not os.environ.get("AUTHZLOCK_DJANGO"):
        pytest.skip("AUTHZLOCK_DJANGO is only set inside nox test sessions")
    rest_framework = pytest.importorskip("rest_framework")
    expected = os.environ.get("AUTHZLOCK_DRF")
    if expected:
        assert rest_framework.VERSION.startswith(expected + ".")
    else:
        assert _version_tuple(rest_framework.VERSION) >= (3, 16)
