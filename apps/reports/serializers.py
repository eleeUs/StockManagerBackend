from rest_framework import serializers


class MovementSummaryItemSerializer(serializers.Serializer):
    """
    One row of the per-movement-type aggregation.
    Shared shape between the movements summary report and the
    `summary_by_type` section of the branch activity report.
    """
    movement_type  = serializers.CharField()
    count          = serializers.IntegerField()
    total_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class MovementSummarySerializer(serializers.Serializer):
    """GET /api/v1/reports/movements/summary/ response shape."""
    date_from = serializers.DateField()
    date_to   = serializers.DateField()
    results   = MovementSummaryItemSerializer(many=True)


class DailyBreakdownItemSerializer(serializers.Serializer):
    """One row of the day + movement_type breakdown for a single branch."""
    date           = serializers.DateField()
    movement_type  = serializers.CharField()
    count          = serializers.IntegerField()
    total_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class BranchActivitySerializer(serializers.Serializer):
    """GET /api/v1/reports/branches/{id}/activity/ response shape."""
    branch_id        = serializers.IntegerField()
    branch_name      = serializers.CharField()
    date_from        = serializers.DateField()
    date_to          = serializers.DateField()
    summary_by_type  = MovementSummaryItemSerializer(many=True)
    daily_breakdown  = DailyBreakdownItemSerializer(many=True)


class StockValuationByBranchItemSerializer(serializers.Serializer):
    branch_id   = serializers.IntegerField()
    branch_name = serializers.CharField()
    valuation   = serializers.DecimalField(max_digits=16, decimal_places=3)


class StockValuationByProductItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    sku        = serializers.CharField()
    name       = serializers.CharField()
    quantity   = serializers.DecimalField(max_digits=12, decimal_places=3)
    valuation  = serializers.DecimalField(max_digits=16, decimal_places=3)


class StockValuationSerializer(serializers.Serializer):
    """
    GET /api/v1/reports/stock/valuation/ response shape.

    products_missing_cost_price surfaces data quality: stock rows for
    products with no cost_price set are excluded from valuation entirely
    rather than silently treated as worth zero, so this count tells the
    admin how much of the picture is missing.
    """
    branch                       = serializers.IntegerField(allow_null=True)
    total_valuation              = serializers.DecimalField(max_digits=16, decimal_places=3)
    products_missing_cost_price  = serializers.IntegerField()
    by_branch                    = StockValuationByBranchItemSerializer(many=True)
    by_product                   = StockValuationByProductItemSerializer(many=True)
