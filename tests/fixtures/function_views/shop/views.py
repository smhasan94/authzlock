"""Function and class views for URL walking and access checks."""

import functools
from collections.abc import Callable

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.views import View
from django.views.decorators.cache import cache_page
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


PERM_CONSTANT = "shop.export_order"


@permission_required("shop.delete_order")
def delete_order(request: HttpRequest) -> HttpResponse:
    return HttpResponse("deleted")


@permission_required(["shop.change_order", "shop.add_order"])
def bulk_edit(request: HttpRequest) -> HttpResponse:
    return HttpResponse("edited")


@permission_required(PERM_CONSTANT)
def export_orders(request: HttpRequest) -> HttpResponse:
    return HttpResponse("exported")


def staff_only(user: object) -> bool:
    raise AssertionError("must not be called")


@user_passes_test(staff_only)
def staff_tools(request: HttpRequest) -> HttpResponse:
    return HttpResponse("tools")


@cache_page(60)
def cached(request: HttpRequest) -> HttpResponse:
    return HttpResponse("cached")
