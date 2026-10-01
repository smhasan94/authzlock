from typing import Any

from api.models import Order


class OwnedQuerysetMixin:
    """Project mixin that scopes the queryset to the current user."""

    request: Any

    def get_queryset(self) -> Any:
        return Order.objects.filter(owner=self.request.user)
