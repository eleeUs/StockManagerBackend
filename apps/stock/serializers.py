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
            "updated_at",
        ]
        read_only_fields = fields
