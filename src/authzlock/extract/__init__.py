"""Build the inventory for the Django project loaded in this process."""

from __future__ import annotations

from authzlock.model import Inventory


def extract() -> Inventory:
    """Return the project's inventory. A stub until URL walking lands in SHA-200."""
    return Inventory()
