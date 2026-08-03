"""
apps/reports/views.py

Read-only reporting endpoints. All three reports are pure aggregations
over apps.stock and apps.movements tables — this app defines no models
and is intentionally NOT registered in INSTALLED_APPS (no migrations
are needed for a models-less app).
"""
from datetime import date as date_cls
from decimal import Decimal

from django.db.models import Count, Sum, Q, F, DecimalField, ExpressionWrapper
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from core.mixins import BranchScopeQuerysetMixin
from core.permissions import IsAdmin
from core.pagination import StandardPagination

from apps.stock.models import Stock
from apps.stock.serializers import StockSerializer
from apps.branches.models import Branch
from apps.movements.models import StockMovement

from .serializers import (
    MovementSummarySerializer,
    BranchActivitySerializer,
    StockValuationSerializer,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_required_date(query_params, param_name):
    """
    Parses a required ISO date query param.
    Raises ValidationError (→ 400) if missing or malformed, mirroring the
    domain-exception → structured-response convention used elsewhere
    (core/exceptions.py) for consistent error payloads on this app too.
    """
    raw = query_params.get(param_name)
    if not raw:
        raise ValidationError({param_name: "This query parameter is required (format: YYYY-MM-DD)."})
    try:
        return date_cls.fromisoformat(raw)
    except ValueError:
        raise ValidationError({param_name: "Invalid date format. Use YYYY-MM-DD."})


def _summary_by_type(queryset):
    """
    Per-movement_type aggregation shared by the movements summary report
    and the summary_by_type section of the branch activity report.
    Relies on idx_movement_type_date (movement_type, -created_at) —
    no new index is required.
    """
    return list(
        queryset
        .values("movement_type")
        .annotate(count=Count("id"), total_quantity=Sum("quantity"))
        .order_by("movement_type")
    )


# ---------------------------------------------------------------------------
# A1 — Low stock report
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Reports"],
    summary="List stock rows at or below a threshold",
    parameters=[
        OpenApiParameter(
            "threshold", OpenApiTypes.INT, OpenApiParameter.QUERY,
            description="Stock quantity ceiling. Default 10.",
        ),
        OpenApiParameter(
            "branch", OpenApiTypes.INT, OpenApiParameter.QUERY,
            description="Optional branch id filter.",
        ),
    ],
    responses={200: StockSerializer(many=True)},
)
class LowStockReportView(BranchScopeQuerysetMixin, generics.ListAPIView):
    """
    GET /api/v1/reports/stock/low/

    Stock rows where quantity <= threshold (default 10).

    - Admins see low stock across all branches.
    - Sellers are scoped to their own branch (unlike the general
      GET /stock/ endpoint, which intentionally grants sellers global
      read visibility per BUSINESS_RULES §1.2). A restock report only
      matters to the seller for the branch they operate.

    Reuses BranchScopeQuerysetMixin.get_branch_q() rather than
    duplicating the branch-filter predicate.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = StockSerializer
    pagination_class   = StandardPagination

    def get_queryset(self):
        threshold_raw = self.request.query_params.get("threshold", "10")
        try:
            threshold = int(threshold_raw)
        except ValueError:
            raise ValidationError({"threshold": "Must be an integer."})

        qs = (
            Stock.objects
            .select_related("product", "product__category", "branch")
            .filter(quantity__lte=threshold)
            .order_by("branch__name", "quantity")
        )

        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        user = self.request.user
        if user.is_seller:
            qs = qs.filter(self.get_branch_q(user))

        return qs


# ---------------------------------------------------------------------------
# A2 — Movement summary report
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Reports"],
    summary="Aggregate movement counts and quantities by type",
    parameters=[
        OpenApiParameter(
            "date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY,
            description="Start date (inclusive), ISO format.", required=True,
        ),
        OpenApiParameter(
            "date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY,
            description="End date (inclusive), ISO format.", required=True,
        ),
        OpenApiParameter(
            "branch", OpenApiTypes.INT, OpenApiParameter.QUERY,
            description="Optional branch id — matches source OR destination.",
        ),
    ],
    request=None,
    responses={
        200: MovementSummarySerializer,
        400: None,
        403: None,
    },
)
class MovementSummaryReportView(APIView):
    """
    GET /api/v1/reports/movements/summary/

    One row per movement_type with count and total_quantity, within a
    required date range. Admin only — cross-branch aggregation is not
    part of the seller's read visibility.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        date_from = _parse_required_date(request.query_params, "date_from")
        date_to   = _parse_required_date(request.query_params, "date_to")

        qs = StockMovement.objects.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )

        branch_id = request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(Q(source_branch_id=branch_id) | Q(destination_branch_id=branch_id))

        payload = {
            "date_from": date_from,
            "date_to":   date_to,
            "results":   _summary_by_type(qs),
        }
        return Response(MovementSummarySerializer(payload).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# A3 — Branch activity report
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Reports"],
    summary="Type summary and daily breakdown of activity for one branch",
    parameters=[
        OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="Branch id"),
        OpenApiParameter(
            "date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY,
            description="Start date (inclusive), ISO format.", required=True,
        ),
        OpenApiParameter(
            "date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY,
            description="End date (inclusive), ISO format.", required=True,
        ),
    ],
    request=None,
    responses={
        200: BranchActivitySerializer,
        400: None,
        403: None,
        404: None,
    },
)
class BranchActivityReportView(APIView):
    """
    GET /api/v1/reports/branches/{id}/activity/

    Combines a summary_by_type section (same shape as the movements
    summary report) with a daily_breakdown grouped by date + movement_type
    using TruncDate. Admin only; sellers cannot access another branch's
    (or even their own) full activity report through this endpoint.
    """
    permission_classes = [IsAdmin]

    def get(self, request, id):
        branch    = get_object_or_404(Branch, pk=id)
        date_from = _parse_required_date(request.query_params, "date_from")
        date_to   = _parse_required_date(request.query_params, "date_to")

        qs = StockMovement.objects.filter(
            Q(source_branch_id=branch.id) | Q(destination_branch_id=branch.id),
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )

        daily_breakdown = list(
            qs
            .annotate(date=TruncDate("created_at"))
            .values("date", "movement_type")
            .annotate(count=Count("id"), total_quantity=Sum("quantity"))
            .order_by("date", "movement_type")
        )

        payload = {
            "branch_id":       branch.id,
            "branch_name":     branch.name,
            "date_from":       date_from,
            "date_to":         date_to,
            "summary_by_type": _summary_by_type(qs),
            "daily_breakdown": daily_breakdown,
        }
        return Response(BranchActivitySerializer(payload).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# A4 — Stock valuation report (Phase 7)
# ---------------------------------------------------------------------------

@extend_schema(
    tags=["Reports"],
    summary="Inventory valuation by branch and by product",
    parameters=[
        OpenApiParameter(
            "branch", OpenApiTypes.INT, OpenApiParameter.QUERY,
            description="Optional branch id filter.",
        ),
    ],
    request=None,
    responses={200: StockValuationSerializer, 403: None},
)
class StockValuationReportView(APIView):
    """
    GET /api/v1/reports/stock/valuation/

    Total inventory value (quantity * product.cost_price), broken down
    by branch and by product. Admin only — cost_price is margin-sensitive
    data that sellers never see (apps/products/serializers.py), so a
    valuation built on top of it is equally restricted.

    Stock rows for products with no cost_price set are excluded from the
    sums rather than treated as worth zero — products_missing_cost_price
    tells the caller how many distinct products are missing that data,
    so the total isn't silently understated without a signal.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        branch_id = request.query_params.get("branch")

        qs = Stock.objects.select_related("product", "branch")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        priced_qs = qs.filter(product__cost_price__isnull=False).annotate(
            value=ExpressionWrapper(
                F("quantity") * F("product__cost_price"),
                output_field=DecimalField(max_digits=16, decimal_places=3),
            )
        )

        missing_count = (
            qs.filter(product__cost_price__isnull=True)
            .values("product_id")
            .distinct()
            .count()
        )

        total_valuation = priced_qs.aggregate(total=Sum("value"))["total"]

        by_branch = [
            {
                "branch_id":   row["branch_id"],
                "branch_name": row["branch__name"],
                "valuation":   row["valuation"],
            }
            for row in (
                priced_qs.values("branch_id", "branch__name")
                .annotate(valuation=Sum("value"))
                .order_by("branch__name")
            )
        ]

        by_product = [
            {
                "product_id": row["product_id"],
                "sku":        row["product__sku"],
                "name":       row["product__name"],
                "quantity":   row["quantity"],
                "valuation":  row["valuation"],
            }
            for row in (
                priced_qs.values("product_id", "product__sku", "product__name")
                .annotate(quantity=Sum("quantity"), valuation=Sum("value"))
                .order_by("product__name")
            )
        ]

        payload = {
            "branch":                      int(branch_id) if branch_id else None,
            "total_valuation":             total_valuation or Decimal("0.000"),
            "products_missing_cost_price": missing_count,
            "by_branch":                   by_branch,
            "by_product":                  by_product,
        }
        return Response(StockValuationSerializer(payload).data, status=status.HTTP_200_OK)
