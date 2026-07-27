from django.contrib import admin
from .models import Branch


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display  = ("name", "address", "is_active", "created_at")
    list_filter   = ("is_active",)
    search_fields = ("name", "address")
