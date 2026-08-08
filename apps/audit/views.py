from rest_framework import generics
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes

from core.permissions import IsAdmin
from core.pagination import StandardPagination
from .models import AuditLog
from .serializers import AuditLogSerializer


@extend_schema_view(
    get=extend_schema(
        tags=["Audit"],
        summary="List audit log entries",
        description=(
            "Records changes to Product, Branch, and User made through the "
            "API's admin-only update endpoints (BUSINESS_RULES §13). Does "
            "NOT include changes made via the Django admin or a shell "
            "session — see AuditLog's model docstring for why."
        ),
        parameters=[
            OpenApiParameter("model", OpenApiTypes.STR, OpenApiParameter.QUERY,
                              description="Filter by model name, e.g. 'Product'."),
            OpenApiParameter("object_id", OpenApiTypes.INT, OpenApiParameter.QUERY,
                              description="Filter by the audited object's id."),
        ],
    )
)
class AuditLogListView(generics.ListAPIView):
    """GET /api/v1/audit-log/"""
    permission_classes = [IsAdmin]
    serializer_class    = AuditLogSerializer
    pagination_class    = StandardPagination

    def get_queryset(self):
        qs = AuditLog.objects.select_related("changed_by")

        model_name = self.request.query_params.get("model")
        if model_name:
            qs = qs.filter(model_name=model_name)

        object_id = self.request.query_params.get("object_id")
        if object_id:
            qs = qs.filter(object_id=object_id)

        return qs
