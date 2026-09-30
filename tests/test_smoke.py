"""Smoke tests for SHA-183: T1 and T3."""

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
