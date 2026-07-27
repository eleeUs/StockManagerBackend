from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from core.mixins import BranchScopeQuerysetMixin
from .models import Stock
from .serializers import StockSerializer


@extend_schema(tags=["Stock"])
class StockListView(BranchScopeQuerysetMixin, generics.ListAPIView):
    """
    GET /api/v1/stock/

    Current stock levels across all branches.

    - Admins see all (product, branch) combinations.
    - Sellers see stock from ALL branches (read-only).
      This is intentional per BUSINESS_RULES §1.2: sellers need
      cross-branch visibility to check availability before suggesting
      a transfer to a customer.

    Branch-scope mixin is bypassed here for sellers (overriding get_branch_q
    to return an unfiltered Q) because visibility is intentionally global.
    The write restriction is enforced at the movement creation level, not here.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = StockSerializer
    filterset_fields   = ["branch", "product"]
    search_fields      = ["product__name", "product__sku", "branch__name"]

    def get_queryset(self):
        # Sellers can read stock from all branches (BUSINESS_RULES §1.2).
        # We intentionally skip BranchScopeQuerysetMixin here — sellers
        # have global READ visibility on stock.
        return (
            Stock.objects
            .select_related("product", "product__category", "branch")
            .order_by("branch__name", "product__name")
        )


@extend_schema(
    tags=["Stock"],
    parameters=[
        OpenApiParameter(
            "product_id",
            OpenApiTypes.INT,
            OpenApiParameter.PATH,
            description="ID of the product to query across branches",
        )
    ],
)
class StockByBranchView(generics.ListAPIView):
    """
    GET /api/v1/stock/product/{product_id}/by-branch/

    Stock level for a single product across every branch.
    Useful for admins deciding the best source branch for a transfer.
    Sellers can also use this to check availability before requesting
    a transfer from an admin.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = StockSerializer

    def get_queryset(self):
        return (
            Stock.objects
            .filter(product_id=self.kwargs["product_id"])
            .select_related("product", "branch")
            .order_by("branch__name")
        )
