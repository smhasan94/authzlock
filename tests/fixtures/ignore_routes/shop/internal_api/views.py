from django.http import HttpRequest, HttpResponse


def status(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")
