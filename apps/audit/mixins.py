"""
apps/audit/mixins.py

AuditedUpdateMixin — mix into a generics.RetrieveUpdateAPIView (or
UpdateAPIView) subclass to automatically record an AuditLog row for
every PATCH/PUT that actually changes something.

Hooks perform_update(), the standard DRF extension point UpdateModelMixin
provides specifically for this kind of side effect — called after
serializer.is_valid() but wrapping serializer.save(), so request.user is
already known and the old instance state is still available before the
write happens.
"""
import decimal
import datetime

from apps.audit.models import AuditLog


def _json_safe(value):
    """
    Converts a model field's Python value into something AuditLog.changes
    (a JSONField) can store without help from a custom encoder at read
    time — done here, not left to DjangoJSONEncoder alone, because a
    ForeignKey's Python value is a related model INSTANCE (e.g. a Branch
    object), which DjangoJSONEncoder has no idea how to serialize. Every
    other type it already handles (Decimal, date, datetime, UUID), this
    only adds the FK case on top.
    """
    if value is None:
        return None
    if hasattr(value, "pk"):  # related model instance (e.g. a Branch FK)
        return value.pk
    if isinstance(value, (decimal.Decimal, datetime.date, datetime.datetime)):
        return str(value)
    return value


class AuditedUpdateMixin:
    """
    Set audit_model_name on the concrete view, e.g.:

        class ProductDetailView(AuditedUpdateMixin, generics.RetrieveUpdateAPIView):
            audit_model_name = "Product"
    """
    audit_model_name = None

    def perform_update(self, serializer):
        if self.audit_model_name is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} uses AuditedUpdateMixin but does "
                f"not set audit_model_name."
            )

        instance = serializer.instance
        # Snapshot only the fields this request is actually touching —
        # not the whole object — so untouched fields never show up as a
        # false "no-op change" in the diff below.
        old_values = {
            field: getattr(instance, field)
            for field in serializer.validated_data.keys()
        }

        updated_instance = serializer.save()

        changes = {}
        for field, old_value in old_values.items():
            new_value = getattr(updated_instance, field)
            if old_value != new_value:
                changes[field] = {
                    "old": _json_safe(old_value),
                    "new": _json_safe(new_value),
                }

        if not changes:
            # Request succeeded but every field already had this value —
            # nothing to audit.
            return

        action = "update"
        if "is_active" in changes and changes["is_active"]["new"] is False:
            action = "deactivate"

        AuditLog.objects.create(
            model_name=self.audit_model_name,
            object_id=updated_instance.pk,
            action=action,
            changed_by=self.request.user,
            changes=changes,
        )
