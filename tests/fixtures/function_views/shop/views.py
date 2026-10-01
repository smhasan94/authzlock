"""Function and class views for URL walking and access checks."""

import functools
from collections.abc import Callable

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpRequest, HttpResponse
from django.views import View
from django.views.decorators.http import require_GET, require_http_methods


def public(request: HttpRequest) -> HttpResponse:
    return HttpResponse("public")


@login_required
def members_only(request: HttpRequest) -> HttpResponse:
    return HttpResponse("members")


@permission_required("shop.view_report")
def staff_report(request: HttpRequest) -> HttpResponse:
    return HttpResponse("report")


def product_list(request: HttpRequest) -> HttpResponse:
    return HttpResponse("products")


class ProductDetail(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        return HttpResponse(f"product {pk}")


def export(request: HttpRequest) -> HttpResponse:
    return HttpResponse("export")


def legacy_product(request: HttpRequest, sku: str) -> HttpResponse:
    return HttpResponse(f"legacy {sku}")


def archive(request: HttpRequest, year: str) -> HttpResponse:
    return HttpResponse(f"archive {year}")


def audit(view: Callable[[HttpRequest], HttpResponse]) -> Callable[[HttpRequest], HttpResponse]:
    """A decorator that does not use functools.wraps."""

    def inner(request: HttpRequest) -> HttpResponse:
        return view(request)

    return inner


@audit
def audited(request: HttpRequest) -> HttpResponse:
    return HttpResponse("audited")


@require_http_methods(["POST", "PUT"])
def update_order(request: HttpRequest) -> HttpResponse:
    return HttpResponse("updated")


def logged(view: Callable[[HttpRequest], HttpResponse]) -> Callable[[HttpRequest], HttpResponse]:
    """A decorator that keeps the wrapped view reachable through functools.wraps."""

    @functools.wraps(view)
    def inner(request: HttpRequest) -> HttpResponse:
        return view(request)

    return inner


@logged
@require_GET
def status(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")
