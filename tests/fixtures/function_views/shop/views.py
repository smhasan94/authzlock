"""Plain function views: one public, one behind login, one behind a permission."""

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpRequest, HttpResponse


def public(request: HttpRequest) -> HttpResponse:
    return HttpResponse("public")


@login_required
def members_only(request: HttpRequest) -> HttpResponse:
    return HttpResponse("members")


@permission_required("shop.view_report")
def staff_report(request: HttpRequest) -> HttpResponse:
    return HttpResponse("report")
