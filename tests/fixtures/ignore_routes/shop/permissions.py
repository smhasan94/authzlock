from typing import Any

from rest_framework.permissions import BasePermission


class IsStockKeeper(BasePermission):
    """Only users in the stock keepers group."""

    def has_permission(self, request: Any, view: Any) -> bool:
        return bool(request.user and request.user.groups.filter(name="stock").exists())
