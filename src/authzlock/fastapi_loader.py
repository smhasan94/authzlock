"""Import the target FastAPI application in the current process."""

from __future__ import annotations

import importlib
from typing import Any

from authzlock.django_loader import add_cwd_to_path
from authzlock.errors import ProjectLoadError

APP_ENV = "AUTHZLOCK_APP"
DEFAULT_ATTRIBUTE = "app"


def parse_app(import_string: str) -> tuple[str, str]:
    """Split `module:attr` into its parts; `attr` defaults to `app`."""
    module, _, attribute = import_string.partition(":")
    module, attribute = module.strip(), attribute.strip() or DEFAULT_ATTRIBUTE
    if not module:
        raise ProjectLoadError(
            f"App {import_string!r} names no module.\n"
            "Pass --app MODULE:ATTR, for example --app main:app."
        )
    return module, attribute


def load_app(import_string: str) -> Any:
    """Import the module named by `import_string` (`module:attr`) and return its application.

    The current directory is put on `sys.path` first, as for Django. Every failure is a
    two-line `ProjectLoadError`. Importing the module runs its top-level code; nothing else
    in the project is called.
    """
    module_name, attribute = parse_app(import_string)
    try:
        import fastapi  # noqa: F401 - the extractor needs it even for a plain Starlette app
        from starlette.applications import Starlette
    except ImportError as exc:
        raise ProjectLoadError(
            "FastAPI is not installed.\n"
            "Install fastapi in the environment authzlock runs in, for example "
            "pip install fastapi."
        ) from exc

    add_cwd_to_path()
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or module_name
        raise ProjectLoadError(
            f"App module {module_name!r}: cannot import {missing!r}.\n"
            "Check the module name and that its directory is on PYTHONPATH."
        ) from exc
    except Exception as exc:
        raise ProjectLoadError(
            f"App module {module_name!r} failed to import.\n{type(exc).__name__}: {exc}"
        ) from exc

    app = getattr(module, attribute, None)
    if app is None:
        raise ProjectLoadError(
            f"App module {module_name!r} has no attribute {attribute!r}.\n"
            "Pass --app MODULE:ATTR naming the application object."
        )
    if not isinstance(app, Starlette):
        raise ProjectLoadError(
            f"{module_name}:{attribute} is a {type(app).__name__}, "
            "not a FastAPI or Starlette application.\n"
            "Pass --app MODULE:ATTR naming the application object."
        )
    return app
