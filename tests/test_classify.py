"""Tests for SHA-229 and SHA-239: classification rules R1 to R9."""

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
    MVP_RULES,
    RULES,
    Classification,
    classify,
    classify_diff,
)
from authzlock.diff import RouteChange, compute, route_changes
from authzlock.effective import expand_for
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
    # IsAuthenticatedOrReadOnly is decided per method by R9, which quotes the R1 result.
    assert result.rule == ("R9" if READ_ONLY in old + new else "R1")
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
    assert result.rule == ("R9" if READ_ONLY in old + new else "R1")
    assert "R1" in result.reason


@pytest.mark.parametrize("new", [[IS_AUTHENTICATED], [READ_ONLY], [ALLOW_ANY], []])
def test_t3_custom_replaced_by_builtin_at_most_is_authenticated_is_loosened(new: list[str]) -> None:
    result = perms([IS_OWNER], new)

    assert result.label == "loosened"
    assert result.rule == ("R9" if READ_ONLY in new else "R2")
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

    for number in range(1, 10):
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
    assert [rule.id for rule in RULES] == ["R9", *(f"R{n}" for n in range(1, 9))]
    assert all(rule.summary for rule in RULES)
    assert LABELS == (
        "added",
        "removed",
        "loosened",
        "tightened",
        "changed-unknown",
        "equivalent",
    )


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


# SHA-239: R9, per-method effective permissions ---------------------------------------------

ANON_READ_ONLY = f"{DRF}.DjangoModelPermissionsOrAnonReadOnly"


def perms_on(methods: tuple[str, ...], old: Any, new: Any) -> Classification:
    """Classify a DRF route serving `methods` whose permission_classes go from old to new."""
    route = dataclasses.replace(API, methods=methods, actions={})
    return classify(
        change(
            dataclasses.replace(route, permission_classes=_class_list(old)),
            dataclasses.replace(route, permission_classes=_class_list(new)),
        )
    )


def test_t3_post_only_route_is_equivalent() -> None:
    result = perms_on(("POST",), [IS_AUTHENTICATED], [READ_ONLY])

    assert (result.label, result.rule) == ("equivalent", "R9")
    assert result.reason.startswith("R9: ")


def test_t4_read_only_route_equivalent_and_mixed_route_tightened_names_post() -> None:
    read_only = perms_on(("GET",), [ALLOW_ANY], [READ_ONLY])
    mixed = perms_on(("GET", "POST"), [ALLOW_ANY], [READ_ONLY])

    assert (read_only.label, read_only.rule) == ("equivalent", "R9")
    assert (mixed.label, mixed.rule) == ("tightened", "R9")
    assert mixed.reason.startswith(f"R9: POST [{ALLOW_ANY}] -> [{IS_AUTHENTICATED}]")


def test_t5_anon_read_only_to_is_authenticated_is_loosened_on_post() -> None:
    result = perms_on(("GET", "POST"), [ANON_READ_ONLY], [IS_AUTHENTICATED])

    assert (result.label, result.rule) == ("loosened", "R9")
    assert result.reason.startswith(f"R9: POST [{MODEL_PERMS}] -> [{IS_AUTHENTICATED}]")
    assert "R2" in result.reason


def test_t6_custom_and_composed_classes_stay_opaque() -> None:
    dropped_owner = perms_on(("GET", "POST"), [READ_ONLY, IS_OWNER], [IS_AUTHENTICATED])
    composed_old = (f"({READ_ONLY} | {IS_OWNER})",)
    composed = perms_on(("GET", "POST"), composed_old, [IS_AUTHENTICATED])

    assert (dropped_owner.label, dropped_owner.rule) == ("loosened", "R9")
    mvp = classify(
        change(
            dataclasses.replace(API, methods=("GET", "POST"), permission_classes=composed_old),
            dataclasses.replace(
                API, methods=("GET", "POST"), permission_classes=(IS_AUTHENTICATED,)
            ),
        ),
        MVP_RULES,
    )
    assert (composed.label, composed.rule) == (mvp.label, mvp.rule) == ("changed-unknown", "R8")


@pytest.mark.parametrize(
    ("methods", "old", "new"),
    [
        (("any",), [IS_AUTHENTICATED], [READ_ONLY]),
        (("GET", "POST"), "dynamic", [READ_ONLY]),
        (("GET", "POST"), [READ_ONLY], "dynamic"),
    ],
)
def test_t7_any_methods_or_dynamic_skip_r9(methods: tuple[str, ...], old: Any, new: Any) -> None:
    route = dataclasses.replace(API, methods=methods, actions={})
    pair = change(
        dataclasses.replace(route, permission_classes=_class_list(old)),
        dataclasses.replace(route, permission_classes=_class_list(new)),
    )

    result = classify(pair)

    assert result.rule != "R9"
    assert result == classify(pair, MVP_RULES)


# The universe for T8: the ranked built-ins, the two expandable classes (IsAuthenticated-
# OrReadOnly is both), two custom classes and dynamic.
_R9_UNIVERSE = (
    ALLOW_ANY,
    READ_ONLY,
    IS_AUTHENTICATED,
    IS_ADMIN,
    ANON_READ_ONLY,
    IS_OWNER,
    IS_TENANT_ADMIN,
)
_R9_VALUES: list[Any] = [
    tuple(combo) for size in range(4) for combo in itertools.combinations(_R9_UNIVERSE, size)
] + ["dynamic"]
_EXPANDABLE = {READ_ONLY, ANON_READ_ONLY}
_CUSTOM = {IS_OWNER, IS_TENANT_ADMIN}


def _expected_r9_label(old: Any, new: Any, methods: tuple[str, ...]) -> str:
    """AC4 restated: the most severe per-method R1 to R8 label, or equivalent."""
    labels = []
    for method in methods:
        before, after = expand_for(old, method), expand_for(new, method)
        if before != after:
            pair = change(
                dataclasses.replace(API, methods=(method,), permission_classes=before),
                dataclasses.replace(API, methods=(method,), permission_classes=after),
            )
            labels.append(classify(pair, MVP_RULES).label)
    for label in ("loosened", "changed-unknown", "tightened"):
        if label in labels:
            return label
    return "equivalent"


@pytest.mark.parametrize("methods", [("GET",), ("POST",), ("GET", "POST")])
def test_t8_exhaustive_never_loosened_with_new_custom_and_matches_mvp_without_expansion(
    methods: tuple[str, ...],
) -> None:
    route = dataclasses.replace(API, methods=methods, actions={})
    checked = 0
    for old, new in itertools.product(_R9_VALUES, repeat=2):
        if old == new:
            continue
        pair = change(
            dataclasses.replace(route, permission_classes=old),
            dataclasses.replace(route, permission_classes=new),
        )
        result = classify(pair)
        if isinstance(new, tuple) and _CUSTOM & set(new):
            assert result.label != "loosened", (old, new, result)
        sides = [side for side in (old, new) if isinstance(side, tuple)]
        if not any(_EXPANDABLE & set(side) for side in sides):
            assert result == classify(pair, MVP_RULES), (old, new)
        if result.label == "equivalent":
            assert any(_EXPANDABLE & set(side) for side in sides), (old, new)
        if result.rule == "R9":
            assert result.label == _expected_r9_label(old, new, methods), (old, new, result)
        checked += 1
    assert checked > 4000


def _rule_ids(text: str) -> list[str]:
    return re.findall(r"^\|\s*(R\d+)\s*\|", text, flags=re.MULTILINE)


def test_t10_docs_and_readme_list_r9_and_equivalent() -> None:
    docs = (REPO_ROOT / "docs" / "classification.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert _rule_ids(docs) == _rule_ids(readme) == [rule.id for rule in RULES]
    for text in (docs, readme):
        r9 = next(line for line in text.splitlines() if line.startswith("| R9 |"))
        assert "`equivalent`" in r9
        assert "IsAuthenticatedOrReadOnly" in r9
        assert "DjangoModelPermissionsOrAnonReadOnly" in r9
