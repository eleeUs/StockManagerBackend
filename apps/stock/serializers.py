from rest_framework import serializers
from .models import Stock


class StockSerializer(serializers.ModelSerializer):
    product_name     = serializers.CharField(source="product.name",     read_only=True)
    product_sku      = serializers.CharField(source="product.sku",      read_only=True)
    product_unit_type = serializers.CharField(source="product.unit_type", read_only=True)
    branch_name      = serializers.CharField(source="branch.name",      read_only=True)

    class Meta:
        model  = Stock
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "product_unit_type",
            "branch",
            "branch_name",
            "quantity",
            "reorder_point",
            "updated_at",
        ]
        read_only_fields = fields


class StockReorderPointUpdateSerializer(serializers.Serializer):
    """
    POST/PATCH body for updating a single Stock row's reorder_point.

    Deliberately a plain Serializer, not ModelSerializer.update() against
    the full Stock model — this endpoint must only ever be able to touch
    reorder_point. quantity remains reachable exclusively through
    StockMovementService, per the "views never touch Stock directly for
    mutations" convention; reorder_point is metadata, not a stock
    mutation, so a narrow dedicated serializer is the safest way to allow
    it without widening that door.
    """
    reorder_point = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=0,
        allow_null=True,
        required=True,
        help_text="Null clears the alert threshold for this row.",
    )
