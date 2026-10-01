from api import views
from django.urls import path

urlpatterns = [
    path("explicit/", views.ExplicitView.as_view(), name="explicit"),
    path("orders/", views.OrderListView.as_view(), name="orders"),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("staff/report/", views.StaffReportView.as_view(), name="staff-report"),
    path("dynamic/", views.DynamicView.as_view(), name="dynamic"),
    path("token/", views.TokenView.as_view(), name="token"),
    path("health/", views.health, name="health"),
]
