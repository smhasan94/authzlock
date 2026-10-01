from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class IsOwner(BasePermission):
    """Only the owner of an object may access it."""

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        return bool(getattr(obj, "owner", None) == request.user)
