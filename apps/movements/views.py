from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsAdmin, IsAdminOrSeller, CanAccessBranch
from core.pagination import MovementCursorPagination
from apps.stock.models import Stock
from apps.stock.serializers import StockSerializer

from .models import StockMovement, MovementType
from .serializers import (
    StockMovementSerializer,
    IngresoSerializer,
    VentaSerializer,
    TransferenciaSerializer,
    AjusteSerializer,
    DevolucionSerializer,
    DonacionSerializer,
)
from .services import StockMovementService
from .filters import StockMovementFilter


# ---------------------------------------------------------------------------
# Stock (read-only views)
# ---------------------------------------------------------------------------

class StockListView(generics.ListAPIView):
    """
    GET /api/v1/stock/
    Current stock levels, filterable by branch and product.

    Sellers see all branches (read-only) per BUSINESS_RULES §1.2.
    Admins see all stock including for inactive branches.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = StockSerializer
    filterset_fields   = ["branch", "product"]
    search_fields      = ["product__name", "product__sku", "branch__name"]

    def get_queryset(self):
        return (
            Stock.objects
            .select_related("product", "product__category", "branch")
            .order_by("branch__name", "product__name")
        )


class StockByBranchView(generics.ListAPIView):
    """
    GET /api/v1/stock/product/{product_id}/by-branch/
    Stock levels for a single product across all branches.
    Useful for admins deciding where to source a transfer.
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


# ---------------------------------------------------------------------------
# Movement history
# ---------------------------------------------------------------------------

class MovementListView(generics.ListAPIView):
    """
    GET /api/v1/movements/
    Paginated, filterable movement history.

    Sellers see movements for their branch only.
    Admins see all movements.
    """
    permission_classes  = [IsAuthenticated]
    serializer_class    = StockMovementSerializer
    filterset_class     = StockMovementFilter
    pagination_class    = MovementCursorPagination
    ordering_fields     = ["created_at"]

    def get_queryset(self):
        qs = (
            StockMovement.objects
            .select_related(
                "product",
                "source_branch",
                "destination_branch",
                "created_by",
            )
            .order_by("-created_at")
        )
        user = self.request.user
        if user.is_seller:
            # Sellers see movements where their branch is source or destination
            from django.db.models import Q
            qs = qs.filter(
                Q(source_branch=user.branch) |
                Q(destination_branch=user.branch)
            )
        return qs


# ---------------------------------------------------------------------------
# Movement creation endpoints — one view per type
# ---------------------------------------------------------------------------

class IngresoView(APIView):
    """POST /api/v1/movements/ingreso/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = IngresoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        movement = StockMovementService.ingreso(
            product_id=d["product"].id,
            branch_id=d["branch"].id,
            quantity=d["quantity"],
            entry_date=d["entry_date"],
            user=request.user,
            notes=d["notes"],
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class VentaView(APIView):
    """
    POST /api/v1/movements/venta/
    Allowed: Admin or Seller.
    Sellers are restricted to their assigned branch (enforced here).
    """
    permission_classes = [IsAdminOrSeller]

    def post(self, request):
        serializer = VentaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Sellers can only sell from their assigned branch
        if request.user.is_seller and d["branch"] != request.user.branch:
            return Response(
                {
                    "error": "unauthorized_movement",
                    "detail": "Sellers can only sell from their assigned branch.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        movement = StockMovementService.venta(
            product_id=d["product"].id,
            branch_id=d["branch"].id,
            quantity=d["quantity"],
            user=request.user,
            notes=d["notes"],
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class TransferenciaView(APIView):
    """POST /api/v1/movements/transferencia/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = TransferenciaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        movement = StockMovementService.crear_transferencia(
            product_id=d["product"].id,
            source_branch_id=d["source_branch"].id,
            destination_branch_id=d["destination_branch"].id,
            quantity=d["quantity"],
            user=request.user,
            notes=d["notes"],
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class ConfirmTransferView(APIView):
    """POST /api/v1/movements/transferencia/{id}/confirm/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        movement = StockMovementService.confirmar_transferencia(
            movement_id=pk,
            user=request.user,
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_200_OK,
        )


class CancelTransferView(APIView):
    """POST /api/v1/movements/transferencia/{id}/cancel/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        movement = StockMovementService.cancelar_transferencia(
            movement_id=pk,
            user=request.user,
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_200_OK,
        )


class AjusteView(APIView):
    """POST /api/v1/movements/ajuste/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = AjusteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        movement = StockMovementService.ajuste(
            product_id=d["product"].id,
            branch_id=d["branch"].id,
            new_quantity=d["new_quantity"],
            user=request.user,
            notes=d["notes"],
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class DevolucionView(APIView):
    """POST /api/v1/movements/devolucion/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = DevolucionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        movement = StockMovementService.devolucion(
            product_id=d["product"].id,
            branch_id=d["branch"].id,
            quantity=d["quantity"],
            user=request.user,
            notes=d["notes"],
            original_movement_id=(
                d["original_movement"].id if d.get("original_movement") else None
            ),
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class DonacionView(APIView):
    """POST /api/v1/movements/donacion/ — Admin only"""
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = DonacionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        movement = StockMovementService.donacion(
            product_id=d["product"].id,
            branch_id=d["branch"].id,
            quantity=d["quantity"],
            user=request.user,
            notes=d["notes"],
        )
        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )
