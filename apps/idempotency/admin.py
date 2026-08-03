from django.contrib import admin
from .models import IdempotencyKey


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display  = ("key", "endpoint", "user", "response_status", "created_at", "expires_at")
    list_filter   = ("endpoint", "response_status")
    search_fields = ("key", "user__email")
    # Rows are a system-generated cache, never hand-edited — only
    # inspectable for debugging, and prunable via the
    # cleanup_idempotency_keys management command (Part 3).
    readonly_fields = (
        "user", "key", "endpoint", "request_hash",
        "response_status", "response_body", "created_at", "expires_at",
    )

    def has_add_permission(self, request):
        return False
