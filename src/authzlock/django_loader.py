"""Load the target Django project in the current process."""

from __future__ import annotations

import os

from authzlock.errors import ProjectLoadError

SETTINGS_ENV = "DJANGO_SETTINGS_MODULE"


def load_project(settings_module: str | None) -> None:
    """Set up Django for `settings_module`, or for `DJANGO_SETTINGS_MODULE` when None.

    Django can only be set up once per process, so a second call is a no-op.
    """
    if settings_module is not None:
        os.environ[SETTINGS_ENV] = settings_module
    module = os.environ.get(SETTINGS_ENV)
    if not module:
        raise ProjectLoadError(
            "No Django settings module given.\n"
            f"Set {SETTINGS_ENV} or pass --settings, for example --settings mysite.settings."
        )

    import django
    from django.apps import apps
    from django.core.exceptions import ImproperlyConfigured

    if apps.ready:
        return
    try:
        django.setup()
    except ModuleNotFoundError as exc:
        missing = exc.name or module
        raise ProjectLoadError(
            f"Settings module {module!r}: cannot import {missing!r}.\n"
            "Check the module name and that its directory is on PYTHONPATH."
        ) from exc
    except ImproperlyConfigured as exc:
        raise ProjectLoadError(
            f"Settings module {module!r} is not configured correctly.\n{exc}"
        ) from exc
    except Exception as exc:
        raise ProjectLoadError(
            f"Settings module {module!r} failed to load.\n{type(exc).__name__}: {exc}"
        ) from exc
