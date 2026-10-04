"""Classification of route changes: loosened, tightened, changed-unknown or equivalent.

Rules R1 to R8 (agreed 2026-09-29, recorded on epic SHA-177), R9 (SHA-239) and R10
(SHA-243) are evaluated in `RULES` order and the first rule that returns a `Classification`
wins; R8 always matches. R10 runs first and covers FastAPI routes, whose
`permission_source` is `dependency`: a dependency is only a name, so a changed dependency
list is never ranked, and only losing or gaining every security scheme is labelled. R9 runs
next: for `IsAuthenticatedOrReadOnly` and `DjangoModelPermissionsOrAnonReadOnly`,
whose meaning depends on the HTTP method, it classifies each method's effective permissions
with R1 to R8 and reports the worst result, or `equivalent` when no method changed. Every
result names its rule and gives a one-line reason that starts with the rule id.

The rules are conservative: a false `loosened` alarm is worse than `changed-unknown`. Only
the four built-in DRF classes in `BUILTIN_RANK` are ranked. Every other permission entry is
opaque: custom and third-party classes and the unranked built-ins (`DjangoModelPermissions`
and the like) are only handled by the explicit removal and addition rules R2 to R4, and
composed expressions such as `(a.X | b.Y)` and the `dynamic` sentinel are never labelled
loosened or tightened. `docs/classification.md` lists the rules with one example each.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from authzlock.diff import Diff, FieldChange, RouteChange
from authzlock.effective import expand_for, is_expandable
from authzlock.extract.custom import BUILTIN_MODULE
from authzlock.extract.decorators import NON_LITERAL
from authzlock.model import Route

Label = Literal["added", "removed", "loosened", "tightened", "changed-unknown", "equivalent"]
LABELS: tuple[Label, ...] = (
    "added",
    "removed",
    "loosened",
    "tightened",
    "changed-unknown",
    "equivalent",
)

DYNAMIC = "dynamic"
DEPENDENCY = "dependency"

# DRF built-ins from weakest to strongest. A permission list is an AND, and each class
# implies every class ranked below it, so a list of ranked classes is as strong as its
# strongest member. An empty list allows anyone, like AllowAny.
BUILTIN_RANK: Mapping[str, int] = {
    f"{BUILTIN_MODULE}.AllowAny": 0,
    f"{BUILTIN_MODULE}.IsAuthenticatedOrReadOnly": 1,
    f"{BUILTIN_MODULE}.IsAuthenticated": 2,
    f"{BUILTIN_MODULE}.IsAdminUser": 3,
}
IS_AUTHENTICATED = f"{BUILTIN_MODULE}.IsAuthenticated"
IS_ADMIN_USER = f"{BUILTIN_MODULE}.IsAdminUser"

# Django auth levels from weakest to strongest; see `_django_auth_level`.
DJANGO_AUTH_RANK: Mapping[str, int] = {
    "none": 0,
    "login_required": 1,
    "permission_required": 2,
}

# Fields that say where a rule came from or what a route is called, not who may call it.
# They may change alongside the fields a rule covers without stopping that rule.
NEUTRAL_FIELDS = frozenset({"name", "permission_source", "authentication_source"})
# The django_auth leaves R6 understands; any other django_auth leaf change goes to R8.
_DJANGO_AUTH_LEAVES = frozenset({"django_auth.login_required", "django_auth.permission_required"})


@dataclass(frozen=True)
class Classification:
    """A label, the rule that produced it (None for added and removed routes) and why."""

    label: Label
    rule: str | None
    reason: str


ADDED = Classification("added", None, "route added")
REMOVED = Classification("removed", None, "route removed")


@dataclass(frozen=True)
class Rule:
    """One classification rule: an id, a one-line summary for docs and a check that
    returns a `Classification` when the rule applies and None otherwise."""

    id: str
    summary: str
    check: Callable[[RouteChange], Classification | None]


@dataclass(frozen=True, kw_only=True)
class ClassifiedRoute:
    """One entry of a classified diff. `route` is the current route, or the base route
    for a removed one; `change` is set for routes present on both sides."""

    key: str
    route: Route
    classification: Classification
    change: RouteChange | None = None


def classify(change: RouteChange, rules: tuple[Rule, ...] | None = None) -> Classification:
    """Classify one changed route with the first rule that applies."""
    for rule in RULES if rules is None else rules:
        result = rule.check(change)
        if result is not None:
            return result
    return _r8_anything_else(change)


def classify_diff(diff: Diff, rules: tuple[Rule, ...] | None = None) -> tuple[ClassifiedRoute, ...]:
    """Every added, removed and changed route of `diff` with its label, sorted by route key."""
    entries = [
        *(
            ClassifiedRoute(key=route.key(), route=route, classification=ADDED)
            for route in diff.added
        ),
        *(
            ClassifiedRoute(key=route.key(), route=route, classification=REMOVED)
            for route in diff.removed
        ),
        *(
            ClassifiedRoute(
                key=change.key(),
                route=change.current,
                classification=classify(change, rules),
                change=change,
            )
            for change in diff.changed
        ),
    ]
    return tuple(
        sorted(entries, key=lambda entry: (entry.key, LABELS.index(entry.classification.label)))
    )


# Helpers ---------------------------------------------------------------------------------


def _changed(change: RouteChange) -> dict[str, FieldChange]:
    """Changed fields by name, without the neutral ones."""
    return {fc.field: fc for fc in change.fields if fc.field not in NEUTRAL_FIELDS}


def _only(change: RouteChange, *names: str) -> FieldChange | None:
    """The change to `names[0]` when it changed and nothing outside `names` did."""
    changed = _changed(change)
    if names[0] not in changed or not set(changed) <= set(names):
        return None
    return changed[names[0]]


def _is_composed(entry: str) -> bool:
    return entry.startswith("(")


def _is_custom(entry: str) -> bool:
    return entry.rsplit(".", 1)[0] != BUILTIN_MODULE


@dataclass(frozen=True)
class _Split:
    """A permission list split into ranked built-ins and opaque single classes."""

    ranked: frozenset[str]
    opaque: frozenset[str]

    @property
    def strongest(self) -> int:
        return max((BUILTIN_RANK[entry] for entry in self.ranked), default=0)


def _split(value: Any) -> _Split | None:
    """None when the list is not a plain list of classes (null, dynamic or composed)."""
    if not isinstance(value, tuple) or any(_is_composed(entry) for entry in value):
        return None
    ranked = frozenset(entry for entry in value if entry in BUILTIN_RANK)
    return _Split(ranked=ranked, opaque=frozenset(value) - ranked)


def _permission_sets(change: RouteChange) -> tuple[_Split, _Split] | None:
    """Old and new permission lists when only they (and neutral fields) changed and both
    are plain lists of classes."""
    fc = _only(change, "permission_classes")
    if fc is None:
        return None
    old, new = _split(fc.old), _split(fc.new)
    if old is None or new is None:
        return None
    return old, new


def _rank_name(rank: int) -> str:
    return next(name for name, value in BUILTIN_RANK.items() if value == rank)


def _describe(entries: frozenset[str]) -> str:
    return ", ".join(
        f"{'custom' if _is_custom(entry) else 'unranked'} class {entry}"
        for entry in sorted(entries)
    )


# Rules -----------------------------------------------------------------------------------


def _r1_builtin_ranking(change: RouteChange) -> Classification | None:
    sets = _permission_sets(change)
    if sets is None:
        return None
    old, new = sets
    if old.opaque or new.opaque or old.strongest == new.strongest:
        return None
    label: Label = "loosened" if new.strongest < old.strongest else "tightened"
    return Classification(
        label,
        "R1",
        f"R1: strongest built-in {_rank_name(old.strongest)} -> {_rank_name(new.strongest)}",
    )


def _r2_custom_removed(change: RouteChange) -> Classification | None:
    sets = _permission_sets(change)
    if sets is None:
        return None
    old, new = sets
    # Any opaque class left in the new list could make up for the removal, so R2 never
    # fires then; that is what guarantees a new custom class never yields `loosened`.
    if not old.opaque or new.opaque:
        return None
    ceiling = max(old.strongest, BUILTIN_RANK[IS_AUTHENTICATED])
    if new.strongest > ceiling:
        return None
    if new.ranked <= old.ranked:
        detail = f"{_describe(old.opaque)} removed"
    else:
        detail = f"{_describe(old.opaque)} replaced by built-in {_rank_name(new.strongest)}"
    return Classification("loosened", "R2", f"R2: {detail}")


def _r3_custom_replaced(change: RouteChange) -> Classification | None:
    sets = _permission_sets(change)
    if sets is None:
        return None
    old, new = sets
    removed, added = old.opaque - new.opaque, new.opaque - old.opaque
    if not removed:
        return None
    if added:
        detail = f"{_describe(removed)} replaced by {_describe(added)}"
    elif not new.opaque and new.strongest == BUILTIN_RANK[IS_ADMIN_USER]:
        detail = f"{_describe(removed)} replaced by built-in {IS_ADMIN_USER}"
    else:
        return None
    return Classification("changed-unknown", "R3", f"R3: {detail}; cannot rank a custom class")


def _r4_custom_added(change: RouteChange) -> Classification | None:
    sets = _permission_sets(change)
    if sets is None:
        return None
    old, new = sets
    added = new.opaque - old.opaque
    kept = old.ranked <= new.ranked and old.opaque <= new.opaque
    if not added or not kept:
        return None
    return Classification(
        "tightened", "R4", f"R4: {_describe(added)} added to the existing classes"
    )


def _r5_dynamic(change: RouteChange) -> Classification | None:
    for fc in change.fields:
        if DYNAMIC in (fc.old, fc.new):
            detail = f"{fc.field} {_show(fc.old)} -> {_show(fc.new)}"
            return Classification("changed-unknown", "R5", f"R5: {detail}; dynamic is not ranked")
    return None


def _show(value: Any) -> str:
    if isinstance(value, tuple):
        return f"[{', '.join(str(item) for item in value)}]"
    return "null" if value is None else str(value)


def _django_auth_level(auth: Mapping[str, Any]) -> int:
    if auth.get("permission_required"):
        return DJANGO_AUTH_RANK["permission_required"]
    if auth.get("login_required"):
        return DJANGO_AUTH_RANK["login_required"]
    return DJANGO_AUTH_RANK["none"]


def _r6_django_auth(change: RouteChange) -> Classification | None:
    changed = _changed(change)
    if not changed or not set(changed) <= _DJANGO_AUTH_LEAVES:
        return None
    old = dict(change.base.django_auth or {})
    new = dict(change.current.django_auth or {})
    # A custom test or an unreadable permission_required argument is opaque: leave it to R8.
    for side in (old, new):
        if side.get("user_passes_test") or NON_LITERAL in (side.get("unknown_decorators") or ()):
            return None
    old_level, new_level = _django_auth_level(old), _django_auth_level(new)
    old_perms = frozenset(old.get("permission_required") or ())
    new_perms = frozenset(new.get("permission_required") or ())
    names = {value: name for name, value in DJANGO_AUTH_RANK.items()}
    if old_level != new_level:
        label: Label = "loosened" if new_level < old_level else "tightened"
        detail = f"{names[old_level]} -> {names[new_level]}"
    elif new_level == DJANGO_AUTH_RANK["permission_required"] and old_perms < new_perms:
        label, detail = (
            "tightened",
            f"permission_required gained {', '.join(sorted(new_perms - old_perms))}",
        )
    elif new_level == DJANGO_AUTH_RANK["permission_required"] and new_perms < old_perms:
        label, detail = (
            "loosened",
            f"permission_required lost {', '.join(sorted(old_perms - new_perms))}",
        )
    else:
        return None
    return Classification(label, "R6", f"R6: django_auth {detail}")


def _r7_methods_gained(change: RouteChange) -> Classification | None:
    fc = _only(change, "methods", "actions")
    if fc is None:
        return None
    old, new = set(fc.old or ()), set(fc.new or ())
    if not old < new:
        return None
    gained = ", ".join(sorted(new - old))
    return Classification(
        "changed-unknown", "R7", f"R7: methods gained {gained} with permissions unchanged"
    )


def _r8_anything_else(change: RouteChange) -> Classification:
    fields = [fc.field for fc in change.fields]
    perm = next((fc for fc in change.fields if fc.field == "permission_classes"), None)
    if perm is not None and any(
        isinstance(side, tuple) and any(_is_composed(entry) for entry in side)
        for side in (perm.old, perm.new)
    ):
        detail = "composed permission expression is not ranked"
    else:
        detail = "no rule covers this change"
    return Classification("changed-unknown", "R8", f"R8: {detail} ({', '.join(fields)})")


def _r9_per_method(change: RouteChange) -> Classification | None:
    fc = _only(change, "permission_classes")
    if fc is None or not isinstance(fc.old, tuple) or not isinstance(fc.new, tuple):
        return None
    if not (is_expandable(fc.old) or is_expandable(fc.new)):
        return None
    methods = change.current.methods
    if not methods or "any" in methods:
        return None
    results: list[tuple[str, tuple[str, ...], tuple[str, ...], Classification]] = []
    for method in methods:
        old, new = expand_for(fc.old, method), expand_for(fc.new, method)
        if old == new:
            continue
        per_method = RouteChange(
            base=replace(change.base, permission_classes=old, methods=(method,)),
            current=replace(change.current, permission_classes=new, methods=(method,)),
            fields=(FieldChange("permission_classes", old, new),),
        )
        results.append((method, old, new, classify(per_method, MVP_RULES)))
    if not results:
        return Classification(
            "equivalent",
            "R9",
            f"R9: no method's effective permissions changed ({', '.join(methods)})",
        )
    # The first method with the most severe label decides; methods are sorted.
    method, old, new, decided = min(results, key=lambda item: _SEVERITY.index(item[3].label))
    return Classification(
        decided.label, "R9", f"R9: {method} {_show(old)} -> {_show(new)} ({decided.reason})"
    )


def _r10_dependency(change: RouteChange) -> Classification | None:
    if DEPENDENCY not in (change.base.permission_source, change.current.permission_source):
        return None
    changed = _changed(change)
    perm = changed.get("permission_classes")
    if perm is not None:
        return Classification(
            "changed-unknown",
            "R10",
            f"R10: dependencies changed, and dependencies are not ranked "
            f"({_show(perm.old)} -> {_show(perm.new)})",
        )
    auth = changed.get("authentication_classes")
    if auth is None:
        return None
    if set(changed) == {"authentication_classes"} and (
        isinstance(auth.old, tuple) and isinstance(auth.new, tuple)
    ):
        if auth.old and not auth.new:
            return Classification(
                "loosened", "R10", f"R10: every security scheme removed ({_show(auth.old)})"
            )
        if auth.new and not auth.old:
            return Classification(
                "tightened", "R10", f"R10: security scheme added ({_show(auth.new)})"
            )
    return Classification(
        "changed-unknown",
        "R10",
        f"R10: security schemes changed ({_show(auth.old)} -> {_show(auth.new)})",
    )


# Per-method labels from most to least severe, for R9 to pick the route's label.
_SEVERITY: tuple[Label, ...] = ("loosened", "changed-unknown", "tightened")

MVP_RULES: tuple[Rule, ...] = (
    Rule(
        "R1",
        "Both permission lists hold only ranked built-ins: compare the strongest class.",
        _r1_builtin_ranking,
    ),
    Rule(
        "R2",
        "Custom class removed, or replaced by a built-in at or below IsAuthenticated: loosened.",
        _r2_custom_removed,
    ),
    Rule(
        "R3",
        "Custom class replaced by IsAdminUser or another custom class: changed-unknown.",
        _r3_custom_replaced,
    ),
    Rule("R4", "Custom class added to an otherwise unchanged list: tightened.", _r4_custom_added),
    Rule("R5", "Either side of a changed field is dynamic: changed-unknown.", _r5_dynamic),
    Rule(
        "R6",
        "login_required or permission_required gained: tightened; the reverse: loosened.",
        _r6_django_auth,
    ),
    Rule(
        "R7",
        "Methods gained entries with permissions unchanged: changed-unknown.",
        _r7_methods_gained,
    ),
    Rule("R8", "Anything else: changed-unknown.", _r8_anything_else),
)

RULES: tuple[Rule, ...] = (
    Rule(
        "R10",
        "FastAPI dependency routes: a changed dependency list is changed-unknown; every "
        "security scheme removed is loosened, the first one added is tightened, with nothing "
        "else changed.",
        _r10_dependency,
    ),
    Rule(
        "R9",
        "IsAuthenticatedOrReadOnly or DjangoModelPermissionsOrAnonReadOnly on either side: "
        "classify each method's effective permissions with R1 to R8; equivalent when none "
        "changed.",
        _r9_per_method,
    ),
    *MVP_RULES,
)
