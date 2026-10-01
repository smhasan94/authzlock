from django.urls import path, re_path

from shop import views

app_name = "shop"

urlpatterns = [
    path("", views.product_list, name="list"),
    path("<int:pk>/", views.ProductDetail.as_view(), name="detail"),
    path("export/", views.export),
    re_path(r"^legacy/(?P<sku>[0-9]+)/$", views.legacy_product, name="legacy"),
]
