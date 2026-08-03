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
