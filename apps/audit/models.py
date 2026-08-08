from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditLog(models.Model):
    """
    Records who changed what on Product, Branch, and User — the three
    models identified in the Phase 8 roadmap as needing traceability
    beyond what StockMovement already provides for stock itself.

    DESIGN — (model_name, object_id) pair instead of GenericForeignKey:
    Django's ContentType + GenericForeignKey is the "idiomatic" way to
    reference an arbitrary model generically, but it adds a join against
    django_content_type for every query and a layer of indirection this
    project doesn't need — there are exactly three models being audited,
    known upfront, not an open-ended set. This mirrors the project's
    existing preference for explicit, simple fields over Django/DRF's
    more automatic features elsewhere (e.g. avoiding `depth=` on
    ModelSerializer.Meta — see phase6_prompt.md's conventions section).

    DESIGN — captured explicitly in the view layer, not via signals:
    pre_save/post_save signals have no reliable access to the current
    request.user without thread-local state, which is its own source of
    fragility (and specifically: it wouldn't work at all during
    seed_dev_data or a data migration, where there is no request). Capture
    happens explicitly in AuditedUpdateMixin.perform_update(), at the one
    point request.user is already known with certainty. The trade-off:
    changes made via the Django admin or a shell session are NOT
    captured. Accepted deliberately — admin/shell access already requires
    superuser trust distinct from API access, and what matters here is
    "what did a user of the system do through the API."
    """
    ACTION_CHOICES = [
        ("create", "Create"),
        ("update", "Update"),
        ("deactivate", "Deactivate"),
    ]

    model_name = models.CharField(max_length=50)   # "Product", "Branch", "User"
    object_id  = models.PositiveIntegerField()
    action     = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="audit_log_entries",
    )
    # {"field_name": {"old": ..., "new": ...}, ...} — only fields that
    # actually changed, not the full object state before/after.
    changes    = models.JSONField(encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["model_name", "object_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} {self.model_name}#{self.object_id} by user {self.changed_by_id}"
