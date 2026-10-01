from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class IsOwner(BasePermission):
    """Only the owner of an invoice may read or delete it."""

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        return bool(getattr(obj, "owner", None) == request.user)


class IsTenantAdmin(BasePermission):
    """The user administers the tenant the invoice belongs to."""

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        return bool(getattr(obj, "tenant_admin", None) == request.user)
