from django.contrib import admin
from django.urls import path, re_path
from shop import views
from shop.internal import views as internal_views
from shop.internal_api import views as internal_api_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("products/", views.products, name="products"),
    re_path(r"^legacy/(?P<code>[a-z]+)/$", views.legacy, name="legacy"),
    path("internal/stock/", internal_views.StockView.as_view(), name="internal-stock"),
    path("internal/audit/", internal_views.audit, name="internal-audit"),
    path("api/internal/", internal_api_views.status, name="internal-api-status"),
]
