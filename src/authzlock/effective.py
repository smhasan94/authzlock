"""Per-method effective permissions for the two DRF built-ins that depend on the method.

`IsAuthenticatedOrReadOnly` allows anyone on a safe method and requires authentication on
every other; `DjangoModelPermissionsOrAnonReadOnly` allows anyone on a safe method and
requires model permissions on every other. `expand` rewrites a permission list into one
list per HTTP method with those two classes replaced by what they mean for that method.
It is used at classification time only (rule R9); the lockfile keeps one list per route.

Every other entry, including custom, third-party and composed classes, is copied as is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from authzlock.extract.custom import BUILTIN_MODULE

ALLOW_ANY = f"{BUILTIN_MODULE}.AllowAny"
IS_AUTHENTICATED = f"{BUILTIN_MODULE}.IsAuthenticated"
IS_AUTHENTICATED_OR_READ_ONLY = f"{BUILTIN_MODULE}.IsAuthenticatedOrReadOnly"
DJANGO_MODEL_PERMISSIONS = f"{BUILTIN_MODULE}.DjangoModelPermissions"
DJANGO_MODEL_PERMISSIONS_OR_ANON_READ_ONLY = (
    f"{BUILTIN_MODULE}.DjangoModelPermissionsOrAnonReadOnly"
)

# rest_framework.permissions.SAFE_METHODS, copied so classification works without DRF.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

# Each expandable class and what it means on a safe method and on any other method.
EXPANDABLE: Mapping[str, tuple[str, str]] = {
    IS_AUTHENTICATED_OR_READ_ONLY: (ALLOW_ANY, IS_AUTHENTICATED),
    DJANGO_MODEL_PERMISSIONS_OR_ANON_READ_ONLY: (ALLOW_ANY, DJANGO_MODEL_PERMISSIONS),
}


def is_expandable(permission_classes: Iterable[str]) -> bool:
    """True if the list holds a class whose meaning depends on the method."""
    return any(entry in EXPANDABLE for entry in permission_classes)


def expand_for(permission_classes: Iterable[str], method: str) -> tuple[str, ...]:
    """The effective permission list for one method, sorted and without duplicates.

    `AllowAny` restricts nothing in a list of several classes, so it is dropped unless it is
    the only one.
    """
    safe = method in SAFE_METHODS
    entries = {
        EXPANDABLE[entry][0 if safe else 1] if entry in EXPANDABLE else entry
        for entry in permission_classes
    }
    if len(entries) > 1:
        entries.discard(ALLOW_ANY)
    return tuple(sorted(entries))


def expand(permission_classes: Iterable[str], methods: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """The effective permission list of each method in `methods`."""
    classes = tuple(permission_classes)
    return {method: expand_for(classes, method) for method in methods}
