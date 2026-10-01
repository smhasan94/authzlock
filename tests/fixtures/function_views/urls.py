from django.urls import include, path, re_path
from shop import views

urlpatterns = [
    path("public/", views.public, name="public"),
    path("members/", views.members_only, name="members-only"),
    path("reports/staff/", views.staff_report, name="staff-report"),
    path("audited/", views.audited, name="audited"),
    path("orders/", views.update_order, name="orders"),
    path("status/", views.status, name="status"),
    path("orders/delete/", views.delete_order, name="delete-order"),
    path("orders/bulk/", views.bulk_edit, name="bulk-edit"),
    path("orders/export/", views.export_orders, name="export-orders"),
    path("staff/tools/", views.staff_tools, name="staff-tools"),
    path("cached/", views.cached, name="cached"),
    re_path(r"^archive/(?P<year>[0-9]{4})/$", views.archive, name="archive"),
    path("shop/", include("shop.urls", namespace="shop")),
    path("a/", include("shop.urls", namespace="a")),
    path("b/", include("shop.urls", namespace="b")),
]
