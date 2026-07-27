from rest_framework import serializers
from .models import Category, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Category
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model  = Product
        fields = [
            "id",
            "sku",
            "name",
            "category",
            "category_name",
            "unit_type",
            "description",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_sku(self, value):
        # Normalize SKU to uppercase to avoid duplicate SKUs
        # that differ only in case (e.g. "abc123" vs "ABC123")
        return value.upper().strip()
