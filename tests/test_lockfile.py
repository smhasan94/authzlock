"""Tests for SHA-224: lockfile schema v1, serializer and loader."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from authzlock.errors import LockfileError
from authzlock.lockfile import dump, load
from authzlock.model import Inventory, Route
from harness import run_extract

ROUTE = Route(
    path="orders/<int:pk>/",
    name="api:order-detail",
    view="api.views.OrderViewSet",
    methods=("DELETE", "GET"),
    actions={"DELETE": "destroy", "GET": "retrieve"},
    permission_classes=(
        "(api.permissions.IsOwner & rest_framework.permissions.IsAuthenticated)",
        "rest_framework.permissions.IsAdminUser",
    ),
    permission_source="view",
    authentication_classes="dynamic",
    authentication_source="view",
    django_auth=None,
    object_scoping={"get_queryset": True, "filters": ["owner"]},
)
PLAIN = Route(
    path="4.2/yes/",
    name=None,
    view="shop.views.public",
    methods=("any",),
    django_auth={
        "login_required": True,
        "permission_required": ["shop.view_order"],
        "user_passes_test": False,
        "unknown_decorators": [],
    },
)
INVENTORY = Inventory(
    routes=(PLAIN, ROUTE),
    custom_permissions={
        "api.permissions.IsOwner": {
            "doc": "Only the owner of an object may access it.",
            "used_by": ["DELETE,GET orders/<int:pk>/ -> api.views.OrderViewSet"],
        }
    },
)


def test_t1_dump_starts_with_schema_version_and_sorted_routes() -> None:
    inventory = Inventory.from_dict(run_extract("drf_viewsets"))
    text = dump(inventory)
    assert text.startswith("schema_version: 1\n")
    data = yaml.safe_load(text)
    keys = [(route["path"], route["view"]) for route in data["routes"]]
    assert keys == sorted(keys)
    assert len(keys) == len(inventory.routes)


def test_t2_round_trip_equality() -> None:
    assert load(dump(INVENTORY)) == INVENTORY


def test_t3_newer_schema_version_is_rejected() -> None:
    with pytest.raises(LockfileError) as excinfo:
        load("schema_version: 2\nroutes: []\ncustom_permissions: {}\n")
    message = str(excinfo.value)
    assert "newer" in message
    assert "upgrade" in message


def test_t4_missing_routes_key_is_named() -> None:
    with pytest.raises(LockfileError, match="routes"):
        load("schema_version: 1\n")


def test_t5_unsorted_lists_are_sorted_on_dump() -> None:
    route = Route(path="p/", name=None, view="v.f", methods=("POST", "GET"))
    text = dump(Inventory(routes=(route,)))
    assert text.index("- GET") < text.index("- POST")


def test_t6_docs_example_loads_and_documents_every_key(repo_root: Path) -> None:
    doc = (repo_root / "docs" / "lockfile.md").read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", doc, re.DOTALL)
    assert match, "docs/lockfile.md has no yaml example"
    example = match.group(1)
    inventory = load(example)
    assert inventory.routes
    prose = doc.replace(example, "")
    data = yaml.safe_load(example)
    keys = set(data) | {key for route in data["routes"] for key in route}
    for key in sorted(keys):
        assert f"`{key}`" in prose, f"{key} is not described"


def test_t7_wrong_field_type_names_the_path() -> None:
    data = yaml.safe_load(dump(INVENTORY))
    data["routes"][0]["permission_classes"] = 5
    with pytest.raises(LockfileError, match=r"routes\[0\]\.permission_classes"):
        load(yaml.safe_dump(data))


def test_extra_dump_is_idempotent() -> None:
    text = dump(INVENTORY)
    assert dump(load(text)) == text


def test_extra_dump_format() -> None:
    text = dump(INVENTORY)
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "\r" not in text
    assert "&id" not in text and "*id" not in text
    assert list(yaml.safe_load(text)) == ["schema_version", "routes", "custom_permissions"]
    assert list(yaml.safe_load(text)["routes"][0])[:3] == ["path", "name", "view"]


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("- just a list\n", "mapping"),
        ("schema_version: 0\nroutes: []\n", "schema_version"),
        ("schema_version: 1\nroutes: [{path: p/}]\n", "routes[0]"),
        ("schema_version: 1\nroutes: []\nextra: 1\n", "extra"),
        ("schema_version: [\n", "YAML"),
    ],
)
def test_extra_invalid_documents_are_rejected(text: str, fragment: str) -> None:
    with pytest.raises(LockfileError) as excinfo:
        load(text)
    assert fragment in str(excinfo.value)
