"""Generate a pytest module from the lockfile: anonymous requests to protected routes are
refused.

`plan_route` decides per route what can be asserted from the lockfile alone, `build_url`
turns a URL pattern into a sample URL, and `render_module` writes the module. Nothing here
loads Django or the target project; the generated module does that when it runs.

What gets asserted, per route:

- `IsAuthenticated` or `IsAdminUser` among the permission classes: every method is refused
  (401 or 403).
- `IsAuthenticatedOrReadOnly` as the strongest class: POST, PUT, PATCH and DELETE are refused.
- `django_auth` with `login_required` or a `permission_required` list: every method is
  refused, and 302 is accepted too because the decorators redirect to the login page.
- `dynamic`, a class outside the four ranked DRF built-ins, a composed expression, or
  `user_passes_test` as the only signal: one skipped test that names the cause.
- Anything else (`AllowAny`, no permission data, undecorated views): no test.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from authzlock.classify import BUILTIN_RANK, IS_ADMIN_USER, IS_AUTHENTICATED
from authzlock.extract.custom import BUILTIN_MODULE
from authzlock.model import Route

DEFAULT_OUTPUT = "tests/test_authz_lock.py"
IS_AUTHENTICATED_OR_READ_ONLY = f"{BUILTIN_MODULE}.IsAuthenticatedOrReadOnly"
UNSAFE_METHODS = ("DELETE", "PATCH", "POST", "PUT")
REFUSED = "REFUSED"
REFUSED_OR_REDIRECT = "REFUSED_OR_REDIRECT"

Kind = Literal["assert", "skip", "none"]


@dataclass(frozen=True)
class RouteTest:
    """What the generated module does for one route.

    `assert` tests send each of `methods` to `url` and accept the statuses named by
    `accepted`; `skip` tests carry `reason`; `none` routes produce no test.
    """

    key: str
    path: str
    view: str
    kind: Kind
    methods: tuple[str, ...] = ()
    url: str | None = None
    accepted: str = REFUSED
    reason: str = ""


# URL building -------------------------------------------------------------------------------

_CONVERTER = re.compile(r"<(?:(?P<type>[^<>:]+):)?(?P<name>[^<>:]+)>")
_UUID_SAMPLE = "00000000-0000-4000-8000-000000000001"
# Values tried, in order, for a regex group; the first that matches the group is used.
_GROUP_SAMPLES = ("1", "x", "a", "abc", "2024", "1111", "x1", "a-1", _UUID_SAMPLE)
_REGEX_META = frozenset("\\.*+?[]{}()|^$")


def _converter_sample(converter: str | None, name: str) -> str | None:
    if converter in (None, "int"):
        return "1"
    if converter in ("slug", "str", "path"):
        return name
    if converter == "uuid":
        return _UUID_SAMPLE
    return None


def _group_end(pattern: str, start: int) -> int | None:
    """Index of the `)` that closes the group opening at `start`, or None."""
    depth = 0
    index = start
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _group_body(group: str) -> str:
    """The regex inside `(?P<name>...)`, `(?:...)` or `(...)`."""
    inner = group[1:-1]
    named = re.match(r"\?P<[^>]+>", inner)
    if named:
        return inner[named.end() :]
    return inner[2:] if inner.startswith("?:") else inner


def _group_sample(body: str) -> str | None:
    try:
        compiled = re.compile(body)
    except re.error:
        return None
    return next((sample for sample in _GROUP_SAMPLES if compiled.fullmatch(sample)), None)


def build_url(pattern: str) -> str | None:
    """A literal URL that `pattern` matches, or None when one cannot be built safely.

    Path converters become `1` (`int` and untyped), the parameter name (`slug`, `str`,
    `path`) or a fixed UUID; an unknown converter gives None. In a regex pattern each group
    becomes the first sample value it matches, anchors are dropped, and any other regex
    syntax left over (an escaped dot, `?`, a character class) gives None.
    """
    is_regex = "^" in pattern or "(?" in pattern or pattern.endswith("$")
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if is_regex and char == "\\":
            parts.append(pattern[index : index + 2])
            index += 2
            continue
        if is_regex and char == "(":
            end = _group_end(pattern, index)
            if end is None:
                return None
            sample = _group_sample(_group_body(pattern[index : end + 1]))
            if sample is None:
                return None
            parts.append(sample)
            index = end + 1
            continue
        if char == "<":
            match = _CONVERTER.match(pattern, index)
            if match is None:
                return None
            sample = _converter_sample(match["type"], match["name"])
            if sample is None:
                return None
            parts.append(sample)
            index = match.end()
            continue
        parts.append(char)
        index += 1
    url = "".join(parts)
    if is_regex:
        url = url.replace("^", "").removesuffix("$")
        if any(char in _REGEX_META for char in url):
            return None
    return "/" + url


# Planning -----------------------------------------------------------------------------------


def _skip(route: Route, reason: str) -> RouteTest:
    return RouteTest(route.key(), route.path, route.view, "skip", reason=reason)


def _drf_methods(route: Route) -> tuple[str, ...] | str:
    """Methods the permission classes refuse to anonymous users, or a skip reason."""
    classes = route.permission_classes
    if classes == "dynamic":
        return "permission_classes is dynamic; the lockfile cannot say who may call it"
    if not classes or isinstance(classes, str):
        return ()
    for entry in classes:
        if entry.startswith("("):
            return f"composed permission {entry} cannot be evaluated from the lockfile"
        if entry not in BUILTIN_RANK:
            return f"{entry} is not a built-in DRF permission"
    if IS_AUTHENTICATED in classes or IS_ADMIN_USER in classes:
        return route.methods
    if IS_AUTHENTICATED_OR_READ_ONLY in classes:
        return tuple(method for method in route.methods if method in UNSAFE_METHODS)
    return ()


def plan_route(route: Route) -> RouteTest:
    """What to generate for `route`; see the module docstring for the rules."""
    drf = _drf_methods(route)
    if isinstance(drf, str):
        return _skip(route, drf)
    auth = route.django_auth or {}
    decorated = bool(auth.get("login_required")) or bool(auth.get("permission_required"))
    if not drf and not decorated:
        if auth.get("user_passes_test"):
            return _skip(route, "user_passes_test cannot be evaluated from the lockfile")
        return RouteTest(route.key(), route.path, route.view, "none")
    methods = set(drf)
    if decorated:
        methods |= set(route.methods)
    sent = sorted({"GET" if method == "any" else method for method in methods})
    url = build_url(route.path)
    if url is None:
        return _skip(route, f"no sample URL can be built for the pattern {route.path}")
    return RouteTest(
        route.key(),
        route.path,
        route.view,
        "assert",
        methods=tuple(sent),
        url=url,
        accepted=REFUSED_OR_REDIRECT if decorated else REFUSED,
    )


@dataclass(frozen=True)
class Summary:
    routes: int
    tests: int
    skipped: int
    without_assertions: int

    def __str__(self) -> str:
        return (
            f"{self.routes} routes, {self.tests} tests, {self.skipped} skipped, "
            f"{self.without_assertions} without assertions"
        )


def summarize(plans: Sequence[RouteTest]) -> Summary:
    def count(kind: Kind) -> int:
        return sum(1 for plan in plans if plan.kind == kind)

    return Summary(len(plans), count("assert"), count("skip"), count("none"))


# Rendering ----------------------------------------------------------------------------------

_HEADER = '''"""Anonymous-access tests generated by `authzlock gen-tests` from {lockfile}.

Each test sends anonymous requests to a route that {lockfile} says requires
authentication and expects them to be refused. Do not edit this file; regenerate it with:

    authzlock gen-tests --lockfile {lockfile} --output {output}

A 404 means the sample URL did not match the route; a 200 means the route lets anonymous
users in although {lockfile} says it should not.
"""

from __future__ import annotations

import pytest

REFUSED = frozenset({{401, 403}})
# Django's login_required and permission_required redirect to the login page.
REFUSED_OR_REDIRECT = frozenset({{302, 401, 403}})


@pytest.fixture(scope="module")
def anonymous_client():
    """A Django test client; sets Django up unless pytest-django already has."""
    import django
    from django.apps import apps
    from django.test import Client
    from django.test.utils import setup_test_environment, teardown_test_environment

    if not apps.ready:
        django.setup()
    try:
        setup_test_environment()
    except RuntimeError:
        owned = False
    else:
        owned = True
    yield Client()
    if owned:
        teardown_test_environment()


def assert_refused(client, method, url, route, accepted):
    response = client.generic(method, url)
    assert response.status_code in accepted, (
        f"{{method}} {{url}} returned {{response.status_code}} to an anonymous user; "
        f"{{route}} is expected to refuse it"
    )
'''


def _literal(value: str) -> str:
    """`value` as a double-quoted Python string literal."""
    return json.dumps(value)


def _names(plans: Iterable[RouteTest]) -> list[str]:
    """One test function name per plan, from the path and the view, unique in order."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for plan in plans:
        view = plan.view.rsplit(".", 1)[-1]
        slug = re.sub(r"[^a-z0-9]+", "_", f"{plan.path} {view}".lower()).strip("_")
        base = f"test_{slug[:60].rstrip('_') or 'root'}"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return names


def _assert_test(name: str, plan: RouteTest) -> str:
    methods = ", ".join(_literal(method) for method in plan.methods)
    assert plan.url is not None
    return (
        "\n\n"
        "@pytest.mark.parametrize(\n"
        '    "method",\n'
        f"    [{methods}],\n"
        ")\n"
        f"def {name}(anonymous_client, method):\n"
        "    assert_refused(\n"
        "        anonymous_client,\n"
        "        method,\n"
        f"        {_literal(plan.url)},\n"
        f"        {_literal(plan.key)},\n"
        f"        {plan.accepted},\n"
        "    )\n"
    )


def _skip_test(name: str, plan: RouteTest) -> str:
    return (
        "\n\n"
        "@pytest.mark.skip(\n"
        f"    reason={_literal(plan.reason)},\n"
        ")\n"
        f"def {name}():\n"
        f"    {_literal(plan.key)}\n"
    )


def render_module(plans: Sequence[RouteTest], *, lockfile: str, output: str) -> str:
    """The generated module for `plans`; the same input always gives the same text."""
    generated = [plan for plan in plans if plan.kind != "none"]
    parts = [_HEADER.format(lockfile=lockfile, output=output)]
    for name, plan in zip(_names(generated), generated, strict=True):
        parts.append(_assert_test(name, plan) if plan.kind == "assert" else _skip_test(name, plan))
    return "".join(parts)


def generate(routes: Iterable[Route], *, lockfile: str, output: str) -> tuple[str, Summary]:
    """The module text and the summary for the routes of one lockfile."""
    plans = [plan_route(route) for route in routes]
    return render_module(plans, lockfile=lockfile, output=output), summarize(plans)
