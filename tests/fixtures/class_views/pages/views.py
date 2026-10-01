"""Class-based views with different handler sets."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import (
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UserPassesTestMixin,
)
from django.http import HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View


class ItemView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("items")

    def post(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("created")


class ReadOnlyView(View):
    """Defines post, but http_method_names only allows get."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("read")

    def post(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("never reached")


class AccountView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("account")


@method_decorator(login_required, name="dispatch")
class SettingsView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("settings")


class OrderAdminView(PermissionRequiredMixin, View):
    permission_required = "shop.view_order"

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("orders")


class StaffView(UserPassesTestMixin, View):
    def test_func(self) -> bool:
        raise AssertionError("must not be called")

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("staff")
