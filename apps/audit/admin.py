from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display  = ("model_name", "object_id", "action", "changed_by", "created_at")
    list_filter   = ("model_name", "action")
    search_fields = ("changed_by__email",)
    readonly_fields = ("model_name", "object_id", "action", "changed_by", "changes", "created_at")

    def has_add_permission(self, request):
        return False
