from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse


def products(request: HttpRequest) -> HttpResponse:
    return HttpResponse("products")


@login_required
def legacy(request: HttpRequest, code: str) -> HttpResponse:
    return HttpResponse(code)
