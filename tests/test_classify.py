"""Tests for SHA-229: classification rules loosened, tightened and changed-unknown."""

from __future__ import annotations

import dataclasses
import itertools
import re
from pathlib import Path
from typing import Any

import pytest

from authzlock.classify import (
    BUILTIN_RANK,
    DJANGO_AUTH_RANK,
    LABELS,
    RULES,
    Classification,
    classify,
    classify_diff,
)
from authzlock.diff import RouteChange, compute, route_changes
from authzlock.model import Inventory, Route

REPO_ROOT = Path(__file__).resolve().parent.parent

DRF = "rest_framework.permissions"
ALLOW_ANY = f"{DRF}.AllowAny"
READ_ONLY = f"{DRF}.IsAuthenticatedOrReadOnly"
IS_AUTHENTICATED = f"{DRF}.IsAuthenticated"
IS_ADMIN = f"{DRF}.IsAdminUser"
MODEL_PERMS = f"{DRF}.DjangoModelPermissions"
IS_OWNER = "shop.permissions.IsOwner"
IS_TENANT_ADMIN = "shop.permissions.IsTenantAdmin"
COMPOSED = f"({IS_AUTHENTICATED} | {IS_OWNER})"

API = Route(
    path="api/orders/<pk>/",
    name="api:order-detail",
    view="api.views.OrderViewSet",
    methods=("DELETE", "GET"),
    actions={"DELETE": "destroy", "GET": "retrieve"},
    permission_classes=(IS_AUTHENTICATED,),
    permission_source="view",
    authentication_classes=("rest_framework.authentication.SessionAuthentication",),
    authentication_source="settings-default",
)
PAGE = Route(
    path="members/",
    name="members-only",
    view="shop.views.members_only",
    methods=("any",),
    django_auth={
        "login_required": True,
        "permission_required": [],
        "unknown_decorators": [],
        "user_passes_test": False,
    },
)


def change(old: Route, new: Route) -> RouteChange:
    fields = route_changes(old, new)
    assert fields, "test pairs must differ"
    return RouteChange(base=old, current=new, fields=fields)


def _class_list(value: Any) -> Any:
    return value if value is None or isinstance(value, str) else tuple(value)


def perms(old: Any, new: Any) -> Classification:
    """Classify a DRF route whose permission_classes go from `old` to `new`."""
    return classify(
        change(
            dataclasses.replace(API, permission_classes=_class_list(old)),
            dataclasses.replace(API, permission_classes=_class_list(new)),
        )
    )


def auth(old: dict[str, Any], new: dict[str, Any]) -> Classification:
    """Classify a plain Django route whose django_auth entries are updated."""
    base = {**dict(PAGE.django_auth or {}), **old}
    current = {**dict(PAGE.django_auth or {}), **new}
    return classify(
        change(
            dataclasses.replace(PAGE, django_auth=base),
            dataclasses.replace(PAGE, django_auth=current),
        )
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([IS_AUTHENTICATED], [ALLOW_ANY]),
        ([IS_ADMIN], [IS_AUTHENTICATED]),
        ([IS_AUTHENTICATED], [READ_ONLY]),
        ([IS_ADMIN, IS_AUTHENTICATED], [READ_ONLY]),
        ([IS_AUTHENTICATED], []),
    ],
)
def test_t1_builtin_weaker_is_loosened(old: list[str], new: list[str]) -> None:
    result = perms(old, new)

    assert result.label == "loosened"
    assert result.rule == "R1"
    assert "R1" in result.reason


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([ALLOW_ANY], [IS_ADMIN]),
        ([READ_ONLY], [IS_AUTHENTICATED]),
        ([], [IS_AUTHENTICATED]),
    ],
)
def test_t2_builtin_stronger_is_tightened(old: list[str], new: list[str]) -> None:
    result = perms(old, new)

    assert result.label == "tightened"
    assert result.rule == "R1"


@pytest.mark.parametrize("new", [[IS_AUTHENTICATED], [READ_ONLY], [ALLOW_ANY], []])
def test_t3_custom_replaced_by_builtin_at_most_is_authenticated_is_loosened(new: list[str]) -> None:
    result = perms([IS_OWNER], new)

    assert result.label == "loosened"
    assert result.rule == "R2"
    assert "R2" in result.reason
    assert IS_OWNER in result.reason


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([IS_AUTHENTICATED, IS_OWNER], [IS_AUTHENTICATED]),
        ([IS_ADMIN, IS_OWNER], [IS_ADMIN]),
        ([IS_ADMIN, IS_OWNER], [IS_AUTHENTICATED]),
    ],
)
def test_t4_custom_removed_is_loosened(old: list[str], new: list[str]) -> None:
    result = perms(old, new)

    assert result.label == "loosened"
    assert result.rule == "R2"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([IS_OWNER], [IS_ADMIN]),
        ([IS_AUTHENTICATED, IS_OWNER], [IS_ADMIN]),
    ],
)
def test_t5_custom_replaced_by_is_admin_user_is_unknown(old: list[str], new: list[str]) -> None:
    result = perms(old, new)

    assert result.label == "changed-unknown"
    assert result.rule == "R3"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([IS_OWNER], [IS_TENANT_ADMIN]),
        ([IS_AUTHENTICATED, IS_OWNER], [IS_AUTHENTICATED, IS_TENANT_ADMIN]),
        ([IS_OWNER], [MODEL_PERMS]),
    ],
)
def test_t6_custom_replaced_by_other_custom_is_unknown(old: list[str], new: list[str]) -> None:
    result = perms(old, new)

    assert result.label == "changed-unknown"
    assert result.rule == "R3"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([IS_AUTHENTICATED], [IS_AUTHENTICATED, IS_OWNER]),
        ([], [IS_OWNER]),
        ([IS_OWNER], [IS_OWNER, IS_TENANT_ADMIN]),
    ],
)
def test_t7_custom_added_to_unchanged_set_is_tightened(old: list[str], new: list[str]) -> None:
    result = perms(old, new)

    assert result.label == "tightened"
    assert result.rule == "R4"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("dynamic", [IS_AUTHENTICATED]),
        ([IS_AUTHENTICATED], "dynamic"),
        ("dynamic", [IS_OWNER]),
        ([ALLOW_ANY], "dynamic"),
    ],
)
def test_t8_dynamic_on_either_side_is_unknown(old: Any, new: Any) -> None:
    result = perms(old, new)

    assert result.label == "changed-unknown"
    assert result.rule == "R5"

    authn = classify(change(API, dataclasses.replace(API, authentication_classes="dynamic")))
    assert authn.label == "changed-unknown"
    assert authn.rule == "R5"


def test_t9_login_required_loosened_and_tightened() -> None:
    off = auth({"login_required": True}, {"login_required": False})
    on = auth({"login_required": False}, {"login_required": True})

    assert (off.label, off.rule) == ("loosened", "R6")
    assert (on.label, on.rule) == ("tightened", "R6")


@pytest.mark.parametrize(
    "new",
    [
        [IS_AUTHENTICATED],
        [ALLOW_ANY],
        [IS_ADMIN],
        [IS_OWNER],
        [],
        "dynamic",
        [f"({IS_AUTHENTICATED} & {IS_OWNER})"],
        [IS_AUTHENTICATED, IS_OWNER],
    ],
)
def test_t10_composed_expression_is_unknown(new: Any) -> None:
    forward = perms([COMPOSED], new)
    backward = perms(new, [COMPOSED])

    assert forward.label == "changed-unknown"
    assert backward.label == "changed-unknown"


def test_t11_docs_list_every_rule() -> None:
    text = (REPO_ROOT / "docs" / "classification.md").read_text(encoding="utf-8")
    rows = {
        match.group(1): match.group(0)
        for match in re.finditer(r"^\|\s*(R\d+)\s*\|.*\|\s*$", text, flags=re.MULTILINE)
    }

    for number in range(1, 9):
        rule_id = f"R{number}"
        assert rule_id in rows, f"{rule_id} has no row in docs/classification.md"
        cells = [cell.strip() for cell in rows[rule_id].strip().strip("|").split("|")]
        assert all(cells), f"{rule_id} row has an empty cell: {rows[rule_id]}"
    assert {rule.id for rule in RULES} == set(rows)
    assert re.search(r"^#+ .*[Ee]xamples?", text, flags=re.MULTILINE)


# The universe for T12: every ranked built-in, an unranked built-in, two custom classes and
# two composed expressions, as sets of up to three entries, plus `dynamic` and null.
_ENTRIES = (
    ALLOW_ANY,
    READ_ONLY,
    IS_AUTHENTICATED,
    IS_ADMIN,
    MODEL_PERMS,
    IS_OWNER,
    IS_TENANT_ADMIN,
    COMPOSED,
    f"(~{IS_OWNER})",
)
_VALUES: list[Any] = [
    tuple(sorted(combo)) for size in range(4) for combo in itertools.combinations(_ENTRIES, size)
]
_VALUES += ["dynamic", None]


def _has_custom(value: Any) -> bool:
    if not isinstance(value, tuple):
        return False
    return any(
        not name.startswith(f"{DRF}.") for entry in value for name in re.findall(r"[\w.]+", entry)
    )


def test_t12_new_custom_class_never_yields_loosened() -> None:
    checked = 0
    for old, new in itertools.product(_VALUES, _VALUES):
        if old == new:
            continue
        result = perms(old, new)
        assert result.label in LABELS
        assert result.reason.startswith(f"{result.rule}: ")
        if _has_custom(new) or (isinstance(new, tuple) and MODEL_PERMS in new):
            assert result.label != "loosened", (old, new, result)
        if old is None or new is None or "dynamic" in (old, new):
            assert result.label == "changed-unknown", (old, new, result)
        checked += 1
    assert checked > 10_000


def test_extra_ranking_tables() -> None:
    assert list(BUILTIN_RANK) == [ALLOW_ANY, READ_ONLY, IS_AUTHENTICATED, IS_ADMIN]
    assert list(BUILTIN_RANK.values()) == sorted(BUILTIN_RANK.values())
    assert list(DJANGO_AUTH_RANK) == ["none", "login_required", "permission_required"]
    assert list(DJANGO_AUTH_RANK.values()) == sorted(DJANGO_AUTH_RANK.values())


def test_extra_rules_table_is_ordered_and_ends_with_catch_all() -> None:
    assert [rule.id for rule in RULES] == [f"R{n}" for n in range(1, 9)]
    assert all(rule.summary for rule in RULES)
    assert LABELS == ("added", "removed", "loosened", "tightened", "changed-unknown")


def test_extra_permission_required_gaining_and_losing_entries() -> None:
    gain = auth(
        {"permission_required": ["shop.view"]}, {"permission_required": ["shop.add", "shop.view"]}
    )
    lose = auth(
        {"permission_required": ["shop.add", "shop.view"]}, {"permission_required": ["shop.view"]}
    )
    login_to_perm = auth(
        {"login_required": True, "permission_required": []},
        {"login_required": False, "permission_required": ["shop.view"]},
    )
    swap = auth({"permission_required": ["shop.add"]}, {"permission_required": ["shop.view"]})

    assert (gain.label, gain.rule) == ("tightened", "R6")
    assert (lose.label, lose.rule) == ("loosened", "R6")
    assert (login_to_perm.label, login_to_perm.rule) == ("tightened", "R6")
    assert (swap.label, swap.rule) == ("changed-unknown", "R8")


def test_extra_login_required_removed_with_custom_test_left_is_unknown() -> None:
    result = auth(
        {"login_required": True, "user_passes_test": True},
        {"login_required": False, "user_passes_test": True},
    )

    assert (result.label, result.rule) == ("changed-unknown", "R8")


def test_extra_methods_gaining_entries_is_unknown() -> None:
    result = classify(
        change(
            API,
            dataclasses.replace(
                API,
                methods=("DELETE", "GET", "PUT"),
                actions={"DELETE": "destroy", "GET": "retrieve", "PUT": "update"},
            ),
        )
    )

    assert (result.label, result.rule) == ("changed-unknown", "R7")


@pytest.mark.parametrize(
    "new",
    [
        dataclasses.replace(API, authentication_classes=()),
        dataclasses.replace(API, permission_classes=(ALLOW_ANY,), methods=("GET",)),
        dataclasses.replace(API, methods=("GET",)),
        dataclasses.replace(API, permission_classes=(IS_AUTHENTICATED, READ_ONLY)),
        dataclasses.replace(API, name="api:order"),
        dataclasses.replace(API, permission_classes=None),
    ],
)
def test_extra_anything_else_is_unknown(new: Route) -> None:
    result = classify(change(API, new))

    assert (result.label, result.rule) == ("changed-unknown", "R8")
    assert result.reason.startswith("R8: ")


def test_extra_classify_diff_labels_added_removed_and_changed() -> None:
    loosened = dataclasses.replace(API, permission_classes=(ALLOW_ANY,))
    base = Inventory(routes=(API, PAGE))
    current = Inventory(routes=(loosened, dataclasses.replace(PAGE, path="members/new/")))

    entries = classify_diff(compute(base, current))

    by_label = {entry.classification.label: entry for entry in entries}
    assert set(by_label) == {"added", "removed", "loosened"}
    assert by_label["added"].route.path == "members/new/"
    assert by_label["removed"].route.path == "members/"
    assert by_label["loosened"].change is not None
    assert by_label["loosened"].classification.rule == "R1"
    assert by_label["added"].classification.rule is None
    assert [entry.key for entry in entries] == sorted(entry.key for entry in entries)
