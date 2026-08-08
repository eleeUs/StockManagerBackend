from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsAdmin
from apps.audit.mixins import AuditedUpdateMixin
from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class CategoryListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/products/categories/  → List all categories
    POST /api/v1/products/categories/  → Create category (admin only)
    """
    queryset         = Category.objects.all()
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAdmin()]
        return [IsAuthenticated()]


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/products/  → List products
    POST /api/v1/products/  → Create product (admin only)

    Both roles can list products.
    Sellers see only active products.
    Admins see all products including inactive ones.
    """
    serializer_class = ProductSerializer
    search_fields    = ["name", "sku"]
    filterset_fields = ["category", "unit_type", "is_active"]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Product.objects.select_related("category")
        if self.request.user.role == "seller":
            qs = qs.filter(is_active=True)
        return qs


class ProductDetailView(AuditedUpdateMixin, generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/products/{id}/  → Retrieve product detail
    PATCH /api/v1/products/{id}/  → Update product (admin only)

    Products are never deleted — deactivate via is_active=False.
    Updates are recorded in the audit trail (BUSINESS_RULES §13).
    """
    queryset          = Product.objects.select_related("category")
    serializer_class   = ProductSerializer
    audit_model_name   = "Product"

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAdmin()]
        return [IsAuthenticated()]
