from decimal import Decimal
from rest_framework import serializers

from apps.products.models import Product
from apps.branches.models import Branch
from .models import StockMovement, MovementType, MovementStatus


# ---------------------------------------------------------------------------
# Read serializer (shared across all list/detail responses)
# ---------------------------------------------------------------------------

class StockMovementSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for movement history responses.
    Expands FKs to include human-readable names.
    """
    product_name         = serializers.CharField(source="product.name",                    read_only=True)
    product_sku          = serializers.CharField(source="product.sku",                     read_only=True)
    source_branch_name   = serializers.CharField(source="source_branch.name",              read_only=True)
    destination_branch_name = serializers.CharField(source="destination_branch.name",      read_only=True)
    created_by_name      = serializers.CharField(source="created_by.full_name",            read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "movement_type",
            "status",
            "product",
            "product_name",
            "product_sku",
            "source_branch",
            "source_branch_name",
            "destination_branch",
            "destination_branch_name",
            "quantity",
            "adjustment_previous_quantity",
            "entry_date",
            "notes",
            "reverses_movement",
            "created_by",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Shared validation mixin
# ---------------------------------------------------------------------------

class _QuantityValidationMixin:
    """
    Validates that:
    1. Quantity is positive.
    2. Unit-type products receive whole numbers.
    """
    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def _validate_unit_quantity(self, product_id, quantity):
        """
        If the product uses whole units (not weight), enforce integer quantity.
        Called from validate() after both fields are available.
        """
        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return  # FK validation will catch this first
        if product.unit_type == "unit" and quantity % 1 != 0:
            raise serializers.ValidationError(
                {"quantity": "This product uses whole units. Quantity must be an integer."}
            )


# ---------------------------------------------------------------------------
# Write serializers — one per movement type
# ---------------------------------------------------------------------------

class IngresoSerializer(_QuantityValidationMixin, serializers.Serializer):
    """POST /api/v1/movements/ingreso/"""
    product    = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    branch     = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    quantity   = serializers.DecimalField(max_digits=12, decimal_places=3)
    entry_date = serializers.DateField()
    notes      = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        return super().validate_quantity(value)

    def validate(self, data):
        self._validate_unit_quantity(data["product"].id, data["quantity"])
        return data


class VentaSerializer(_QuantityValidationMixin, serializers.Serializer):
    """POST /api/v1/movements/venta/"""
    product  = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    branch   = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    notes    = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        return super().validate_quantity(value)

    def validate(self, data):
        self._validate_unit_quantity(data["product"].id, data["quantity"])
        return data


class TransferenciaSerializer(_QuantityValidationMixin, serializers.Serializer):
    """POST /api/v1/movements/transferencia/"""
    product           = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    source_branch      = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    destination_branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    quantity           = serializers.DecimalField(max_digits=12, decimal_places=3)
    notes              = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        return super().validate_quantity(value)

    def validate(self, data):
        if data["source_branch"] == data["destination_branch"]:
            raise serializers.ValidationError(
                {"destination_branch": "Source and destination branches must be different."}
            )
        self._validate_unit_quantity(data["product"].id, data["quantity"])
        return data


class AjusteSerializer(_QuantityValidationMixin, serializers.Serializer):
    """
    POST /api/v1/movements/ajuste/
    new_quantity is the ABSOLUTE target value, not a delta.
    """
    product      = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    branch       = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    new_quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    notes        = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_new_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError("New quantity cannot be negative.")
        return value

    def validate(self, data):
        # For adjustment, validate unit integrity on new_quantity
        if data["new_quantity"] > 0:
            self._validate_unit_quantity(data["product"].id, data["new_quantity"])
        return data


class DevolucionSerializer(_QuantityValidationMixin, serializers.Serializer):
    """POST /api/v1/movements/devolucion/"""
    product             = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    branch              = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    quantity            = serializers.DecimalField(max_digits=12, decimal_places=3)
    original_movement   = serializers.PrimaryKeyRelatedField(
        queryset=StockMovement.objects.filter(movement_type=MovementType.VENTA),
        required=False,
        allow_null=True,
        default=None,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        return super().validate_quantity(value)

    def validate(self, data):
        self._validate_unit_quantity(data["product"].id, data["quantity"])

        # If original movement is referenced, verify it belongs to the same branch
        original = data.get("original_movement")
        if original and original.source_branch != data["branch"]:
            raise serializers.ValidationError(
                {"original_movement": "The original sale did not occur at this branch."}
            )
        return data


class DonacionSerializer(_QuantityValidationMixin, serializers.Serializer):
    """POST /api/v1/movements/donacion/"""
    product  = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    branch   = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    notes    = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        return super().validate_quantity(value)

    def validate(self, data):
        self._validate_unit_quantity(data["product"].id, data["quantity"])
        return data


# ---------------------------------------------------------------------------
# Transfer action serializers
# ---------------------------------------------------------------------------

class ConfirmTransferSerializer(serializers.Serializer):
    """Body is empty — the transfer ID comes from the URL."""
    pass


class CancelTransferSerializer(serializers.Serializer):
    """Body is empty — the transfer ID comes from the URL."""
    pass
