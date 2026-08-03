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
            "cost_price",
            "sale_price",
            "description",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_sku(self, value):
        # Normalize SKU to uppercase to avoid duplicate SKUs
        # that differ only in case (e.g. "abc123" vs "ABC123")
        return value.upper().strip()

    def to_representation(self, instance):
        """
        cost_price is margin-sensitive data (BUSINESS_RULES §9) — a seller
        seeing acquisition cost next to sale price exposes profit margins
        that are not part of their role. sale_price stays visible to both
        roles since it's what the seller actually quotes to customers.

        Stripped in to_representation (not via a separate serializer) so
        every existing view — list, detail, nested usage in other
        serializers — inherits the restriction automatically.
        """
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_seller", False):
            data.pop("cost_price", None)
        return data
