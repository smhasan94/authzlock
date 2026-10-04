"""Print the inventory of the configured project as JSON.

Used by the test harness: `python -m authzlock._dump` with `AUTHZLOCK_APP` set extracts that
FastAPI app, otherwise the Django project named by `DJANGO_SETTINGS_MODULE`.
"""

from __future__ import annotations

import json
import os
import sys

from authzlock.errors import EXIT_ERROR, EXIT_OK, AuthzlockError
from authzlock.fastapi_loader import APP_ENV
from authzlock.model import Inventory


def _extract() -> Inventory:
    app = os.environ.get(APP_ENV)
    if app:
        from authzlock.extract.fastapi import extract_app
        from authzlock.fastapi_loader import load_app

        return extract_app(load_app(app))
    from authzlock.django_loader import load_project
    from authzlock.extract import extract

    load_project(None)
    return extract()


def main() -> int:
    try:
        inventory = _extract()
    except AuthzlockError as exc:
        print(f"authzlock: {exc}", file=sys.stderr)
        return EXIT_ERROR
    json.dump(inventory.to_dict(), sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
