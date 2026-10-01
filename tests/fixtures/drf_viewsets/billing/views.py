"""ViewSets for router, nested router and @action routes. No models: nothing is queried."""

from typing import Any

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response


class InvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def archive(self, request: Request, pk: Any = None) -> Response:
        return Response({"archived": pk})

    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> Response:
        return Response({"total": 0})


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only: list and retrieve."""


class LineViewSet(viewsets.ModelViewSet):
    """Invoice lines, nested under an invoice."""
