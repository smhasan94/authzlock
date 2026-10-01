from django.urls import path

from api import scoping_views

urlpatterns = [
    path("plain/", scoping_views.PlainViewSet.as_view({"get": "list"}), name="plain"),
    path("owned/", scoping_views.OwnedOrdersView.as_view(), name="owned"),
    path("all/", scoping_views.AllOrdersView.as_view(), name="all"),
    path("mixin/", scoping_views.MixinOrdersView.as_view(), name="mixin"),
]
