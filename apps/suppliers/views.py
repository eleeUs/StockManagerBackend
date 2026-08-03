from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsAdmin
from .models import Supplier
from .serializers import SupplierSerializer


class SupplierListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/suppliers/  → List suppliers
    POST /api/v1/suppliers/  → Create supplier (admin only)

    Both roles can list suppliers — a seller may need to reference a
    supplier name when reviewing an entry's history, even though only
    admins can register entries. Sellers only see active suppliers.
    """
    serializer_class = SupplierSerializer
    search_fields     = ["name", "contact_name", "contact_email"]
    filterset_fields  = ["is_active"]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Supplier.objects.all()
        if self.request.user.role == "seller":
            qs = qs.filter(is_active=True)
        return qs


class SupplierDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/suppliers/{id}/  → Retrieve supplier detail
    PATCH /api/v1/suppliers/{id}/  → Update supplier (admin only)

    Suppliers are never deleted — deactivate via is_active=False,
    same policy as Branch and Product.
    """
    queryset         = Supplier.objects.all()
    serializer_class = SupplierSerializer

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAdmin()]
        return [IsAuthenticated()]
