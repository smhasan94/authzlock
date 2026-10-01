"""Tests for SHA-200: the route model and its dict round trip."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from authzlock.model import Inventory, Route

ROUTE_FIELDS = [
    "path",
    "name",
    "view",
    "methods",
    "actions",
    "permission_classes",
    "permission_source",
    "authentication_classes",
    "authentication_source",
    "django_auth",
    "object_scoping",
]


def test_extra_route_to_dict_keeps_lockfile_field_order() -> None:
    route = Route(path="shop/", name="shop:list", view="shop.views.product_list")
    assert list(route.to_dict()) == ROUTE_FIELDS


def test_extra_route_defaults_for_later_fields() -> None:
    data = Route(path="p/", name=None, view="v.f").to_dict()
    assert data["methods"] == []
    assert data["actions"] == {}
    for key in ROUTE_FIELDS[5:]:
        assert data[key] is None


def test_extra_route_is_frozen_and_keyword_only() -> None:
    route = Route(path="p/", name=None, view="v.f")
    with pytest.raises(FrozenInstanceError):
        route.path = "q/"  # type: ignore[misc]
    with pytest.raises(TypeError):
        Route("p/", None, "v.f")  # type: ignore[misc]


def test_extra_route_key() -> None:
    route = Route(path="shop/", name=None, view="shop.views.f", methods=("GET", "POST"))
    assert route.key() == "GET,POST shop/ -> shop.views.f"
    assert Route(path="p/", name=None, view="v.f").key() == "p/ -> v.f"


def test_extra_inventory_round_trip() -> None:
    inventory = Inventory(
        routes=(
            Route(
                path="shop/",
                name="shop:list",
                view="shop.views.product_list",
                methods=("GET",),
                actions={"get": "list"},
                permission_classes=("rest_framework.permissions.IsAuthenticated",),
            ),
        ),
        custom_permissions={"shop.perms.IsOwner": {"used_by": ["GET shop/ -> v"]}},
    )
    data = inventory.to_dict()
    assert data["routes"][0]["permission_classes"] == ["rest_framework.permissions.IsAuthenticated"]
    assert Inventory.from_dict(data) == inventory
