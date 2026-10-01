"""Tests for SHA-210: object-scoping heuristic for get_queryset, get_object, perform_create."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from authzlock.extract.scoping import references_request_user
from harness import fixture_env, run_extract

NOT_OVERRIDDEN = {"overridden": False, "references_request_user": None}


@pytest.fixture(scope="module")
def routes() -> dict[str, dict[str, Any]]:
    return {route["path"]: route for route in run_extract("drf_apiview")["routes"]}


def test_t1_no_override_all_false_and_null(routes: dict[str, dict[str, Any]]) -> None:
    assert routes["scoped/plain/"]["object_scoping"] == {
        "get_object": NOT_OVERRIDDEN,
        "get_queryset": NOT_OVERRIDDEN,
        "perform_create": NOT_OVERRIDDEN,
    }


def test_t2_owner_filter_references_request_user(routes: dict[str, dict[str, Any]]) -> None:
    scoping = routes["scoped/owned/"]["object_scoping"]
    assert scoping["get_queryset"] == {"overridden": True, "references_request_user": True}
    assert scoping["get_object"] == NOT_OVERRIDDEN


def test_t3_unfiltered_override_is_false(routes: dict[str, dict[str, Any]]) -> None:
    scoping = routes["scoped/all/"]["object_scoping"]
    assert scoping["get_queryset"] == {"overridden": True, "references_request_user": False}


def test_t4_perform_create_references_request_user(routes: dict[str, dict[str, Any]]) -> None:
    scoping = routes["scoped/owned/"]["object_scoping"]
    assert scoping["perform_create"] == {"overridden": True, "references_request_user": True}
    # ListCreateAPIView gets perform_create from DRF's CreateModelMixin; that is not an override.
    assert routes["orders/"]["object_scoping"]["perform_create"] == NOT_OVERRIDDEN


def test_t5_mixin_override_counts(routes: dict[str, dict[str, Any]]) -> None:
    scoping = routes["scoped/mixin/"]["object_scoping"]
    assert scoping["get_queryset"] == {"overridden": True, "references_request_user": True}


# DRF reads Django settings at import time, so the exec-built class lives in a child process.
_UNREADABLE = """
import json, django
django.setup()
from authzlock.extract.scoping import resolve

namespace = {}
exec(
    "from rest_framework import generics\\n"
    "class Hidden(generics.ListAPIView):\\n"
    "    def get_queryset(self):\\n"
    "        return self.request.user.orders.all()\\n",
    namespace,
)
print(json.dumps(resolve(namespace["Hidden"])))
"""


def test_t6_unreadable_source_gives_null() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _UNREADABLE],
        env=fixture_env("drf_apiview"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    scoping = json.loads(result.stdout)
    assert scoping["get_queryset"] == {"overridden": True, "references_request_user": None}


def test_t7_helper_call_is_not_followed() -> None:
    helper = "def get_queryset(self):\n    return scoped_for(self.request)\n"
    assert references_request_user(helper) is False


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("return Order.objects.filter(owner=self.request.user)", True),
        ("return Order.objects.filter(owner_id=self.request.user.id)", True),
        ("return Order.objects.filter(owner=request.user)", True),
        ("return Order.objects.filter(agent=self.request.user_agent)", False),
        ("return Order.objects.filter(user=self.user)", False),
    ],
)
def test_extra_request_user_chains(body: str, expected: bool) -> None:
    assert references_request_user(f"def get_queryset(self):\n    {body}\n") is expected


def test_extra_non_generic_views_have_no_scoping(routes: dict[str, dict[str, Any]]) -> None:
    assert routes["explicit/"]["object_scoping"] is None
    assert routes["health/"]["object_scoping"] is None
