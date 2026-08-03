from django.urls import path
from .views import SupplierListCreateView, SupplierDetailView

urlpatterns = [
    path("",          SupplierListCreateView.as_view(), name="supplier-list-create"),
    path("<int:pk>/", SupplierDetailView.as_view(),      name="supplier-detail"),
]
