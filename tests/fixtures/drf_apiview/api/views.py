"""DRF views covering each way permission and authentication classes are set."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwner


class ExplicitView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


class OrderListView(generics.ListCreateAPIView):
    """Relies on the settings defaults for both class lists."""


class OrderDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [IsOwner]


class StaffBase(APIView):
    permission_classes = [IsAdminUser]


class StaffReportView(StaffBase):
    def get(self, request: Request) -> Response:
        return Response({"report": []})


class DynamicView(APIView):
    def get_permissions(self) -> Any:
        raise AssertionError("must not be called")

    def get(self, request: Request) -> Response:
        return Response({})


class TokenView(APIView):
    permission_classes = [IsAuthenticated]

    def get_authenticators(self) -> Any:
        raise AssertionError("must not be called")

    def post(self, request: Request) -> Response:
        return Response({})


def health(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")
