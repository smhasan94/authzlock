"""Read the source of a view function or class and pick apart its definition with `ast`."""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def source_of(obj: Any) -> str | None:
    """Dedented source of a function or class, or None when it cannot be read."""
    try:
        target = obj if isinstance(obj, type) else inspect.unwrap(obj)
        return textwrap.dedent(inspect.getsource(target))
    except (OSError, TypeError, ValueError):
        return None


def definition_in(source: str) -> Definition | None:
    """The first function or class definition in `source`."""
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    for node in module.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return node
    return None


def dotted_name(node: ast.expr) -> str | None:
    """`a.b.c` for a Name or Attribute chain, None for anything else."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))
