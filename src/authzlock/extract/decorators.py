"""Django auth rules on plain views: decorators, `method_decorator` and the auth mixins.

Runtime data comes first: the `__wrapped__` chain and the closures Django's decorators
leave behind. The view's source, parsed with `ast`, adds what runtime cannot see, such as
decorators that do not keep a reference to their arguments. No test callable is ever called.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from authzlock.extract.source import definition_in, dotted_name, source_of

NON_LITERAL = "permission_required(<non-literal>)"
# Decorators the tool already understands elsewhere; they are not reported as unknown.
_KNOWN = frozenset(
    {
        "login_required",
        "permission_required",
        "user_passes_test",
        "method_decorator",
        "require_http_methods",
        "require_GET",
        "require_POST",
        "require_safe",
    }
)


@dataclass
class DjangoAuth:
    login_required: bool = False
    permission_required: tuple[str, ...] = ()
    user_passes_test: bool = False
    unknown_decorators: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "login_required": self.login_required,
            "permission_required": list(self.permission_required),
            "user_passes_test": self.user_passes_test,
            "unknown_decorators": list(self.unknown_decorators),
        }


def resolve(callback: Callable[..., Any], view_class: type | None) -> DjangoAuth:
    """Auth rules for a non-DRF route."""
    found = _Found()
    for level in _wrapper_chain(callback):
        _from_closure(level, found)
    if view_class is not None:
        _from_mixins(view_class, found)
        for decorator in _closure(getattr(view_class, "dispatch", None)).get("decorators", ()):
            _from_decorator_object(decorator, found)
    parsed = _parse(view_class if view_class is not None else callback)
    if parsed is not None:
        if found.perms:
            # Permissions read at runtime are exact, so a non-literal argument is no gap.
            parsed.non_literal = False
        found.merge(parsed)
    return found.result()


def from_source(source: str) -> DjangoAuth:
    """Auth rules readable from the decorators of the first definition in `source`."""
    found = _parse_source(source) or _Found()
    return found.result()


@dataclass
class _Found:
    login: bool = False
    perms: set[str] = field(default_factory=set)
    test: bool = False
    unknown: set[str] = field(default_factory=set)
    non_literal: bool = False

    def merge(self, other: _Found) -> None:
        self.login |= other.login
        self.perms |= other.perms
        self.test |= other.test
        self.unknown |= other.unknown
        self.non_literal |= other.non_literal

    def result(self) -> DjangoAuth:
        unknown = set(self.unknown)
        if self.non_literal:
            unknown.add(NON_LITERAL)
        return DjangoAuth(
            login_required=self.login,
            permission_required=tuple(sorted(self.perms)),
            user_passes_test=self.test,
            unknown_decorators=tuple(sorted(unknown)),
        )


def _wrapper_chain(callback: Any) -> Iterator[Any]:
    seen: set[int] = set()
    while callback is not None and id(callback) not in seen:
        seen.add(id(callback))
        yield callback
        callback = getattr(callback, "__wrapped__", None)


def _closure(func: Any) -> dict[str, Any]:
    code = getattr(func, "__code__", None)
    cells = getattr(func, "__closure__", None) or ()
    if code is None:
        return {}
    values: dict[str, Any] = {}
    for name, cell in zip(code.co_freevars, cells, strict=False):
        try:
            values[name] = cell.cell_contents
        except ValueError:  # empty cell
            continue
    return values


def _from_closure(wrapper: Any, found: _Found) -> None:
    """A `user_passes_test` wrapper keeps `test_func`; classify it without calling it."""
    test_func = _closure(wrapper).get("test_func")
    if test_func is not None:
        _classify_test(test_func, found)


def _classify_test(test_func: Any, found: _Found) -> None:
    qualname = getattr(test_func, "__qualname__", "")
    module = getattr(test_func, "__module__", "")
    if module == "django.contrib.auth.decorators" and qualname.startswith("login_required."):
        found.login = True
    elif module == "django.contrib.auth.decorators" and qualname.startswith("permission_required."):
        found.perms |= _perm_strings(test_func)
    else:
        found.test = True


def _perm_strings(func: Any) -> set[str]:
    closure = _closure(func)
    value = closure.get("perms", closure.get("perm"))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list | tuple | set | frozenset):
        return {item for item in value if isinstance(item, str)}
    return set()


def _from_decorator_object(decorator: Any, found: _Found) -> None:
    """A decorator passed to `method_decorator`, before it is applied."""
    module = getattr(decorator, "__module__", "")
    qualname = getattr(decorator, "__qualname__", "")
    if module == "django.contrib.auth.decorators" and qualname == "login_required":
        found.login = True
        return
    closure = _closure(decorator)
    if "test_func" in closure:
        _classify_test(closure["test_func"], found)
    elif module == "django.contrib.auth.decorators" and qualname.startswith("permission_required."):
        found.perms |= _perm_strings(decorator)


def _from_mixins(view_class: type, found: _Found) -> None:
    from django.contrib.auth.mixins import (
        LoginRequiredMixin,
        PermissionRequiredMixin,
        UserPassesTestMixin,
    )

    if issubclass(view_class, LoginRequiredMixin):
        found.login = True
    if issubclass(view_class, PermissionRequiredMixin):
        value = getattr(view_class, "permission_required", None)
        if isinstance(value, str):
            found.perms.add(value)
        elif isinstance(value, list | tuple):
            found.perms |= {item for item in value if isinstance(item, str)}
    if issubclass(view_class, UserPassesTestMixin):
        found.test = True


def _parse(obj: Any) -> _Found | None:
    source = source_of(obj)
    return _parse_source(source) if source is not None else None


def _parse_source(source: str) -> _Found | None:
    definition = definition_in(source)
    if definition is None:
        return None
    found = _Found()
    for node in definition.decorator_list:
        _classify_node(node, found)
    return found


def _classify_node(node: ast.expr, found: _Found) -> None:
    call = node if isinstance(node, ast.Call) else None
    name = dotted_name(call.func if call else node)
    short = name.rsplit(".", 1)[-1] if name else None
    if short == "login_required":
        found.login = True
    elif short == "user_passes_test":
        found.test = True
    elif short == "permission_required":
        _permission_argument(call.args[0] if call and call.args else None, found)
    elif short == "method_decorator" and call and call.args:
        _classify_node(call.args[0], found)
    elif short is not None and short not in _KNOWN:
        found.unknown.add(short)
    elif short is None:
        found.unknown.add(ast.unparse(node))


def _permission_argument(arg: ast.expr | None, found: _Found) -> None:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        found.perms.add(arg.value)
        return
    if isinstance(arg, ast.List | ast.Tuple):
        strings = [
            item.value
            for item in arg.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        if len(strings) == len(arg.elts):
            found.perms.update(strings)
            return
    found.non_literal = True
