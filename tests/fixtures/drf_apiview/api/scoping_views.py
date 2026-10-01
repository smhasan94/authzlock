"""Views covering the object-scoping heuristic. Nothing here is ever executed."""

from typing import Any

from rest_framework import generics, viewsets

from api.mixins import OwnedQuerysetMixin
from api.models import Order


class PlainViewSet(viewsets.ModelViewSet):
    """Overrides no hook."""


class OwnedOrdersView(generics.ListCreateAPIView):
    def get_queryset(self) -> Any:
        return Order.objects.filter(owner=self.request.user)

    def perform_create(self, serializer: Any) -> None:
        serializer.save(owner=self.request.user)


class AllOrdersView(generics.ListAPIView):
    def get_queryset(self) -> Any:
        return Order.objects.all()


class MixinOrdersView(OwnedQuerysetMixin, generics.ListAPIView):
    pass
