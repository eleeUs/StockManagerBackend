from django.contrib import admin
from .models import Stock


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display  = ("product", "branch", "quantity", "updated_at")
    list_filter   = ("branch",)
    search_fields = ("product__name", "product__sku", "branch__name")
    readonly_fields = ("updated_at",)
