from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from shop.permissions import IsStockKeeper


class StockView(APIView):
    permission_classes = [IsStockKeeper]

    def get(self, request: Request) -> Any:
        return Response([])


@staff_member_required
def audit(request: HttpRequest) -> HttpResponse:
    return HttpResponse("audit")
