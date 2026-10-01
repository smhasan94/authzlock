"""The one endpoint of the docs/scenario.md walkthrough."""

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from billing.permissions import IsOwner


class InvoiceDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [IsAuthenticated, IsOwner]
