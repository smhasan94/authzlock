from api import views
from django.urls import include, path

urlpatterns = [
    path("scoped/", include("api.scoping_urls")),
    path("explicit/", views.ExplicitView.as_view(), name="explicit"),
    path("orders/", views.OrderListView.as_view(), name="orders"),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("staff/report/", views.StaffReportView.as_view(), name="staff-report"),
    path("dynamic/", views.DynamicView.as_view(), name="dynamic"),
    path("token/", views.TokenView.as_view(), name="token"),
    path("composed/", views.ComposedView.as_view(), name="composed"),
    path("negated/", views.NegatedView.as_view(), name="negated"),
    path("notes/", views.NotesView.as_view(), name="notes"),
    path("exploding/", views.ExplodingView.as_view(), name="exploding"),
    path("health/", views.health, name="health"),
]
