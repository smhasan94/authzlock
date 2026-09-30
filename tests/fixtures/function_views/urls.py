from django.urls import path
from shop import views

urlpatterns = [
    path("public/", views.public, name="public"),
    path("members/", views.members_only, name="members-only"),
    path("reports/staff/", views.staff_report, name="staff-report"),
]
