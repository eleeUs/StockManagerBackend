from django.db.models import Q
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes

from core.mixins import BranchScopeQuerysetMixin
from core.permissions import IsAdmin, IsAdminOrSeller
from core.pagination import MovementCursorPagination

from .models import StockMovement
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
# Shared schema responses (reused across multiple endpoints)
# ---------------------------------------------------------------------------

_INSUFFICIENT_STOCK  = OpenApiResponse(description="Insufficient stock at branch (stock < requested quantity)")
_INVALID_MOVEMENT    = OpenApiResponse(description="Movement violates a business rule")
_UNAUTHORIZED        = OpenApiResponse(description="User role does not permit this action")
_NOT_FOUND           = OpenApiResponse(description="Movement not found")


# ---------------------------------------------------------------------------
# Movement history
# ---------------------------------------------------------------------------

@extend_schema(tags=["Movements"])
class MovementListView(BranchScopeQuerysetMixin, generics.ListAPIView):
    """
    GET /api/v1/movements/

    Paginated, cursor-based movement history.
    Supports filtering by date range, type, status, product, and branch.

    Scope:
    - Admins see all movements across all branches.
    - Sellers see only movements where their branch is source OR destination.
      This includes inbound transfers so sellers can track incoming stock.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = StockMovementSerializer
    filterset_class    = StockMovementFilter
    pagination_class   = MovementCursorPagination

    def get_branch_q(self, user) -> Q:
        # Sellers see movements from/to their branch (OR condition).
        # This overrides the mixin default which only handles a single field.
        return (
            Q(source_branch=user.branch) |
            Q(destination_branch=user.branch)
        )

    def get_queryset(self):
        qs = (
            StockMovement.objects
            .select_related(
                "product",
                "source_branch",
                "destination_branch",
                "created_by",
            )
            .order_by("-created_at", "id")
        )
        user = self.request.user
        if user.is_seller:
            qs = qs.filter(self.get_branch_q(user))
        return qs


# ---------------------------------------------------------------------------
# Movement creation endpoints
# ---------------------------------------------------------------------------

class IngresoView(APIView):
    """POST /api/v1/movements/ingreso/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements"],
        summary="Register a stock entry",
        request=IngresoSerializer,
        responses={
            201: StockMovementSerializer,
            400: _INVALID_MOVEMENT,
            403: _UNAUTHORIZED,
        },
    )
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
            supplier_id=d["supplier"].id if d["supplier"] else None,
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class VentaView(APIView):
    """
    POST /api/v1/movements/venta/

    Sellers are restricted to their assigned branch.
    Admins can sell from any branch.
    """
    permission_classes = [IsAdminOrSeller]

    @extend_schema(
        tags=["Movements"],
        summary="Register a sale",
        request=VentaSerializer,
        responses={
            201: StockMovementSerializer,
            400: _INSUFFICIENT_STOCK,
            403: OpenApiResponse(
                description="Seller attempting to sell from a branch other than their own"
            ),
        },
    )
    def post(self, request):
        serializer = VentaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Sellers are restricted to their assigned branch (BUSINESS_RULES §1.2)
        if request.user.is_seller and d["branch"] != request.user.branch:
            return Response(
                {
                    "error": "unauthorized_movement",
                    "detail": "Sellers can only register sales from their assigned branch.",
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
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class TransferenciaView(APIView):
    """POST /api/v1/movements/transferencia/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements - Transfers"],
        summary="Create a pending transfer between branches (step 1 of 2)",
        description=(
            "Creates a transfer in PENDING status. "
            "Source stock is decremented immediately to reserve the quantity. "
            "The transfer must be confirmed or cancelled explicitly."
        ),
        request=TransferenciaSerializer,
        responses={
            201: StockMovementSerializer,
            400: OpenApiResponse(
                description="Insufficient stock at source, same source/destination, or invalid quantity"
            ),
            403: _UNAUTHORIZED,
        },
    )
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
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class ConfirmTransferView(APIView):
    """POST /api/v1/movements/transferencia/{id}/confirm/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements - Transfers"],
        summary="Confirm a pending transfer (step 2 of 2)",
        description="Adds stock to the destination branch. Cannot be undone — create a reversal instead.",
        parameters=[
            OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="Transfer movement ID")
        ],
        request=None,
        responses={
            200: StockMovementSerializer,
            400: _INVALID_MOVEMENT,
            403: _UNAUTHORIZED,
            404: _NOT_FOUND,
            409: OpenApiResponse(description="Transfer already confirmed"),
        },
    )
    def post(self, request, pk):
        movement = StockMovementService.confirmar_transferencia(
            movement_id=pk,
            user=request.user,
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_200_OK)


class CancelTransferView(APIView):
    """POST /api/v1/movements/transferencia/{id}/cancel/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements - Transfers"],
        summary="Cancel a pending transfer",
        description="Restores stock to the source branch. Only works on PENDING transfers.",
        parameters=[
            OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="Transfer movement ID")
        ],
        request=None,
        responses={
            200: StockMovementSerializer,
            400: _INVALID_MOVEMENT,
            403: _UNAUTHORIZED,
            404: _NOT_FOUND,
            409: OpenApiResponse(description="Cannot cancel a confirmed transfer"),
        },
    )
    def post(self, request, pk):
        movement = StockMovementService.cancelar_transferencia(
            movement_id=pk,
            user=request.user,
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_200_OK)


class AjusteView(APIView):
    """POST /api/v1/movements/ajuste/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements"],
        summary="Adjust stock to an absolute value",
        description=(
            "Sets stock at a branch to new_quantity (absolute value, not a delta). "
            "Intended for physical inventory corrections. "
            "To add stock formally, use the ingreso endpoint instead."
        ),
        request=AjusteSerializer,
        responses={
            201: StockMovementSerializer,
            400: _INVALID_MOVEMENT,
            403: _UNAUTHORIZED,
        },
    )
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
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class DevolucionView(APIView):
    """POST /api/v1/movements/devolucion/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements"],
        summary="Register a product return",
        description=(
            "Returns stock to the same branch where the original sale occurred. "
            "Referencing the original_movement is optional but strongly recommended for audit."
        ),
        request=DevolucionSerializer,
        responses={
            201: StockMovementSerializer,
            400: OpenApiResponse(
                description="Return quantity exceeds original sale or branch mismatch"
            ),
            403: _UNAUTHORIZED,
        },
    )
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
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class DonacionView(APIView):
    """POST /api/v1/movements/donacion/"""
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements"],
        summary="Register a stock donation",
        request=DonacionSerializer,
        responses={
            201: StockMovementSerializer,
            400: _INSUFFICIENT_STOCK,
            403: _UNAUTHORIZED,
        },
    )
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
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class ReverseMovementView(APIView):
    """
    POST /api/v1/movements/{id}/reverse/

    Creates a REVERSAL movement that undoes the stock effect of a
    confirmed movement. The original movement record is never modified.

    Supported types: ingreso, venta, transferencia (confirmed only),
    ajuste, devolucion, donacion.

    Pending transfers must be cancelled via the cancel endpoint, not reversed.
    A movement that has already been reversed cannot be reversed again.
    """
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Movements"],
        summary="Reverse a confirmed movement",
        description=(
            "Creates a REVERSAL movement with the opposite stock effect. "
            "The original movement is never modified. "
            "Cannot be applied to pending transfers or movements already reversed."
        ),
        parameters=[
            OpenApiParameter(
                "id", OpenApiTypes.INT, OpenApiParameter.PATH,
                description="ID of the movement to reverse",
            )
        ],
        request=None,
        responses={
            201: StockMovementSerializer,
            400: OpenApiResponse(
                description="Movement is pending, already reversed, or insufficient stock to undo"
            ),
            403: _UNAUTHORIZED,
            404: _NOT_FOUND,
            409: OpenApiResponse(description="Movement has already been reversed"),
        },
    )
    def post(self, request, pk):
        reversal = StockMovementService.revertir(
            movement_id=pk,
            user=request.user,
        )
        return Response(
            StockMovementSerializer(reversal).data,
            status=status.HTTP_201_CREATED,
        )
