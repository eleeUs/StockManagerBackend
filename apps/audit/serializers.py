from rest_framework import serializers
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source="changed_by.full_name", read_only=True)

    class Meta:
        model  = AuditLog
        fields = [
            "id",
            "model_name",
            "object_id",
            "action",
            "changed_by",
            "changed_by_name",
            "changes",
            "created_at",
        ]
        read_only_fields = fields
