from billing import views
from django.urls import include, path
from rest_framework.routers import DefaultRouter, SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

router = DefaultRouter()
router.register("invoices", views.InvoiceViewSet, basename="invoice")
router.register("customers", views.CustomerViewSet, basename="customer")

lines = NestedSimpleRouter(router, "invoices", lookup="invoice")
lines.register("lines", views.LineViewSet, basename="invoice-lines")

v2 = SimpleRouter()
v2.register("invoices", views.InvoiceViewSet, basename="v2-invoice")

urlpatterns = [
    path("", include(router.urls)),
    path("", include(lines.urls)),
    path("v2/", include(v2.urls)),
]
