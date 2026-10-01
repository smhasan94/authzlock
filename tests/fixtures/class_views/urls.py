from django.urls import path
from django.views.generic import RedirectView, TemplateView
from pages import views

urlpatterns = [
    path("items/", views.ItemView.as_view(), name="items"),
    path("about/", TemplateView.as_view(template_name="about.html"), name="about"),
    path("old/", RedirectView.as_view(url="/about/"), name="old"),
    path("readonly/", views.ReadOnlyView.as_view(), name="readonly"),
]
