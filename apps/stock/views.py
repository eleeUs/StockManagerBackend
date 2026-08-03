from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from core.mixins import BranchScopeQuerysetMixin
from core.permissions import IsAdmin
from .models import Stock
from .serializers import StockSerializer, StockReorderPointUpdateSerializer


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


@extend_schema(
    tags=["Stock"],
    summary="Set or clear the low-stock alert threshold for a stock row",
    request=StockReorderPointUpdateSerializer,
    responses={200: StockSerializer},
    parameters=[
        OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="Stock row id"),
    ],
)
class StockReorderPointView(APIView):
    """
    PATCH /api/v1/stock/{id}/reorder-point/

    Admin only. Updates ONLY reorder_point — quantity is never reachable
    from this endpoint. Setting reorder_point to null clears the alert
    for this (product, branch) row; check_low_stock (BUSINESS_RULES §11)
    then skips it entirely rather than falling back to a global default.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, id):
        try:
            stock = Stock.objects.select_related("product", "branch").get(pk=id)
        except Stock.DoesNotExist:
            return Response(
                {"error": "not_found", "detail": f"Stock row #{id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = StockReorderPointUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        stock.reorder_point = serializer.validated_data["reorder_point"]
        stock.save(update_fields=["reorder_point", "updated_at"])

        return Response(StockSerializer(stock).data, status=status.HTTP_200_OK)
