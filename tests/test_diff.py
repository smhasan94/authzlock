"""Tests for SHA-228: structural diff engine between two inventories."""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Mapping
from typing import Any

from authzlock.diff import CustomPermission, Diff, FieldChange, RouteChange, compute
from authzlock.model import Inventory, Route

ORDERS = Route(
    path="api/orders/",
    name="api:order-list",
    view="api.views.OrderViewSet",
    methods=("GET", "POST"),
    actions={"GET": "list", "POST": "create"},
    permission_classes=("rest_framework.permissions.IsAuthenticated",),
    permission_source="view",
    authentication_classes=("rest_framework.authentication.SessionAuthentication",),
    authentication_source="settings",
    object_scoping={
        "get_object": {"overridden": False, "references_request_user": False},
        "get_queryset": {"overridden": True, "references_request_user": True},
        "perform_create": {"overridden": False, "references_request_user": False},
    },
)
MEMBERS = Route(
    path="members/",
    name="members-only",
    view="shop.views.members_only",
    methods=("any",),
    django_auth={
        "login_required": True,
        "permission_required": ["shop.view_member"],
        "unknown_decorators": [],
        "user_passes_test": False,
    },
)
REGISTRY: dict[str, dict[str, Any]] = {
    "api.permissions.IsOwner": {
        "docstring": "Only the owner of an order may read or delete it.",
        "name": "IsOwner",
        "used_by": ["GET,POST api/orders/ -> api.views.OrderViewSet"],
    },
}


def inventory(*routes: Route, registry: Mapping[str, Mapping[str, Any]] | None = None) -> Inventory:
    return Inventory(routes=routes, custom_permissions=REGISTRY if registry is None else registry)


def test_t1_identical_inventories_are_empty() -> None:
    diff = compute(inventory(ORDERS, MEMBERS), inventory(ORDERS, MEMBERS))

    assert diff == Diff()
    assert diff.added == diff.removed == ()
    assert diff.changed == ()
    assert diff.custom_permissions_added == diff.custom_permissions_removed == ()
    assert diff.custom_permissions_changed == ()
    assert diff.is_empty


def test_t2_route_only_in_current_is_added() -> None:
    diff = compute(inventory(ORDERS), inventory(ORDERS, MEMBERS))

    assert diff.added == (MEMBERS,)
    assert diff.removed == ()
    assert diff.changed == ()
    assert not diff.is_empty


def test_t3_route_only_in_base_is_removed() -> None:
    diff = compute(inventory(ORDERS, MEMBERS), inventory(ORDERS))

    assert diff.removed == (MEMBERS,)
    assert diff.added == ()
    assert diff.changed == ()
    assert not diff.is_empty


def test_t4_two_field_changes_on_one_route() -> None:
    new = dataclasses.replace(
        ORDERS,
        methods=("GET",),
        permission_classes=("rest_framework.permissions.IsAdminUser",),
    )

    diff = compute(inventory(ORDERS, MEMBERS), inventory(new, MEMBERS))

    assert diff.added == diff.removed == ()
    assert diff.changed == (
        RouteChange(
            base=ORDERS,
            current=new,
            fields=(
                FieldChange("methods", ("GET", "POST"), ("GET",)),
                FieldChange(
                    "permission_classes",
                    ("rest_framework.permissions.IsAuthenticated",),
                    ("rest_framework.permissions.IsAdminUser",),
                ),
            ),
        ),
    )
    assert [change.field for change in diff.changed[0].fields] == [
        "methods",
        "permission_classes",
    ]


def test_t5_nested_change_uses_dotted_field_name() -> None:
    assert MEMBERS.django_auth is not None
    new_members = dataclasses.replace(
        MEMBERS,
        django_auth={**MEMBERS.django_auth, "permission_required": ["shop.change_member"]},
    )
    assert ORDERS.object_scoping is not None
    new_orders = dataclasses.replace(
        ORDERS,
        object_scoping={
            **ORDERS.object_scoping,
            "get_queryset": {"overridden": False, "references_request_user": False},
        },
    )

    diff = compute(inventory(ORDERS, MEMBERS), inventory(new_orders, new_members))

    by_path = {change.current.path: change.fields for change in diff.changed}
    assert by_path["members/"] == (
        FieldChange(
            "django_auth.permission_required", ("shop.view_member",), ("shop.change_member",)
        ),
    )
    assert by_path["api/orders/"] == (
        FieldChange("object_scoping.get_queryset.overridden", True, False),
        FieldChange("object_scoping.get_queryset.references_request_user", True, False),
    )


def test_t5_missing_nested_mapping_is_all_null() -> None:
    new = dataclasses.replace(MEMBERS, django_auth=None)

    diff = compute(inventory(MEMBERS), inventory(new))

    assert diff.changed[0].fields == (
        FieldChange("django_auth.login_required", True, None),
        FieldChange("django_auth.permission_required", ("shop.view_member",), None),
        FieldChange("django_auth.unknown_decorators", (), None),
        FieldChange("django_auth.user_passes_test", False, None),
    )


def test_t6_registry_docstring_change_does_not_mark_route() -> None:
    entry = REGISTRY["api.permissions.IsOwner"]
    edited = {"api.permissions.IsOwner": {**entry, "docstring": "Owners only."}}

    diff = compute(inventory(ORDERS), inventory(ORDERS, registry=edited))

    assert diff.changed == ()
    assert diff.added == diff.removed == ()
    assert diff.custom_permissions_added == diff.custom_permissions_removed == ()
    assert len(diff.custom_permissions_changed) == 1
    change = diff.custom_permissions_changed[0]
    assert change.path == "api.permissions.IsOwner"
    assert change.fields == (
        FieldChange(
            "docstring", "Only the owner of an order may read or delete it.", "Owners only."
        ),
    )
    assert not diff.is_empty


def test_t6_registry_added_and_removed_are_reported_separately() -> None:
    other: dict[str, dict[str, Any]] = {
        "shop.permissions.IsStaff": {
            "docstring": None,
            "name": "IsStaff",
            "used_by": ["any members/ -> shop.views.members_only"],
        },
    }

    diff = compute(inventory(ORDERS), inventory(ORDERS, registry=other))

    assert diff.changed == ()
    assert diff.custom_permissions_added == (
        CustomPermission(
            path="shop.permissions.IsStaff",
            name="IsStaff",
            docstring=None,
            used_by=("any members/ -> shop.views.members_only",),
        ),
    )
    assert [entry.path for entry in diff.custom_permissions_removed] == ["api.permissions.IsOwner"]


def test_t7_output_lists_are_sorted() -> None:
    def route(path: str, view: str, methods: tuple[str, ...] = ("GET",)) -> Route:
        return Route(path=path, name=None, view=view, methods=methods)

    kept = [route(f"kept/{n}/", f"app.views.Kept{n}") for n in range(6)]
    removed = [route(f"gone/{n}/", f"app.views.Gone{n}") for n in range(6)]
    added = [route(f"new/{n}/", f"app.views.New{n}") for n in range(6)]
    changed = [dataclasses.replace(r, methods=("POST",)) for r in kept]
    base_registry: dict[str, dict[str, Any]] = {
        f"app.permissions.P{n}": {"name": f"P{n}", "docstring": "a"} for n in range(6)
    }
    current_registry: dict[str, dict[str, Any]] = {
        **{f"app.permissions.P{n}": {"name": f"P{n}", "docstring": "b"} for n in range(6)},
        **{f"app.permissions.Q{n}": {"name": f"Q{n}", "docstring": None} for n in range(6)},
    }
    del current_registry["app.permissions.P0"], current_registry["app.permissions.P5"]

    rng = random.Random(228)
    base_routes = kept + removed
    current_routes = changed + added
    rng.shuffle(base_routes)
    rng.shuffle(current_routes)
    base_items = list(base_registry.items())
    current_items = list(current_registry.items())
    rng.shuffle(base_items)
    rng.shuffle(current_items)

    diff = compute(
        Inventory(routes=tuple(base_routes), custom_permissions=dict(base_items)),
        Inventory(routes=tuple(current_routes), custom_permissions=dict(current_items)),
    )

    def keys(routes: tuple[Route, ...]) -> list[str]:
        return [r.key() for r in routes]

    assert keys(diff.added) == sorted(r.key() for r in added)
    assert keys(diff.removed) == sorted(r.key() for r in removed)
    assert [c.key() for c in diff.changed] == sorted(r.key() for r in changed)
    assert len(diff.changed) == 6
    for registry_list in (
        diff.custom_permissions_added,
        diff.custom_permissions_removed,
        diff.custom_permissions_changed,
    ):
        paths = [entry.path for entry in registry_list]
        assert paths == sorted(paths)
        assert paths
    assert compute(
        Inventory(routes=tuple(base_routes), custom_permissions=dict(base_items)),
        Inventory(routes=tuple(current_routes), custom_permissions=dict(current_items)),
    ) == compute(
        Inventory(routes=tuple(kept + removed), custom_permissions=base_registry),
        Inventory(routes=tuple(changed + added), custom_permissions=current_registry),
    )


def test_t8_view_move_is_remove_plus_add() -> None:
    moved = dataclasses.replace(MEMBERS, view="members.views.members_only")

    diff = compute(inventory(ORDERS, MEMBERS), inventory(ORDERS, moved))

    assert diff.removed == (MEMBERS,)
    assert diff.added == (moved,)
    assert diff.changed == ()
