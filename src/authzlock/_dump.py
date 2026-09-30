"""Print the inventory of the configured Django project as JSON.

Used by the test harness: `python -m authzlock._dump` with `DJANGO_SETTINGS_MODULE` set.
"""

from __future__ import annotations

import json
import sys

from authzlock.django_loader import load_project
from authzlock.errors import EXIT_ERROR, EXIT_OK, AuthzlockError
from authzlock.extract import extract


def main() -> int:
    try:
        load_project(None)
        inventory = extract()
    except AuthzlockError as exc:
        print(f"authzlock: {exc}", file=sys.stderr)
        return EXIT_ERROR
    json.dump(inventory.to_dict(), sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
