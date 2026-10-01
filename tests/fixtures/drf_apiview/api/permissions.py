from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class IsOwner(BasePermission):
    """Only the owner of an object may access it."""

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        return bool(getattr(obj, "owner", None) == request.user)


class NoDoc(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return True


class IsBlocked(BasePermission):
    """The user is on the block list."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return False


class Exploding(BasePermission):
    """Raises if authzlock ever instantiates or calls it."""

    def __init__(self) -> None:
        raise RuntimeError("must not be instantiated")

    def has_permission(self, request: Request, view: Any) -> bool:
        raise RuntimeError("must not be called")
