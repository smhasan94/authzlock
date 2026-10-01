from django.urls import path
from django.views.generic import RedirectView, TemplateView
from pages import views

urlpatterns = [
    path("items/", views.ItemView.as_view(), name="items"),
    path("about/", TemplateView.as_view(template_name="about.html"), name="about"),
    path("old/", RedirectView.as_view(url="/about/"), name="old"),
    path("readonly/", views.ReadOnlyView.as_view(), name="readonly"),
    path("account/", views.AccountView.as_view(), name="account"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("orders/", views.OrderAdminView.as_view(), name="orders"),
    path("staff/", views.StaffView.as_view(), name="staff"),
]
