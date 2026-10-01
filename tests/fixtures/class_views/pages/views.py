"""Class-based views with different handler sets."""

from django.http import HttpRequest, HttpResponse
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
