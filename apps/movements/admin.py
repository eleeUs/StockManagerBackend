from django.contrib import admin
from .models import StockMovement


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display  = (
        "movement_type", "status", "product",
        "source_branch", "destination_branch", "supplier",
        "quantity", "created_by", "created_at",
    )
    list_filter   = ("movement_type", "status", "source_branch", "destination_branch")
    search_fields = ("product__name", "product__sku", "created_by__email")
    readonly_fields = (
        "movement_type", "status", "product",
        "source_branch", "destination_branch", "supplier",
        "quantity", "adjustment_previous_quantity",
        "entry_date", "reverses_movement",
        "created_by", "created_at", "notes",
    )

    # Movements are append-only — no adding or deleting via admin
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
