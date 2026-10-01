from billing import views
from django.urls import path

urlpatterns = [
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice-detail"),
]
