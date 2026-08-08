from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsAdmin
from apps.audit.mixins import AuditedUpdateMixin
from .models import Branch
from .serializers import BranchSerializer


class BranchListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/branches/  → List branches
    POST /api/v1/branches/  → Create branch (admin only)

    Both roles can list branches.
    Sellers need branch visibility to check stock availability
    at other branches (BUSINESS_RULES §1.2).
    """
    serializer_class = BranchSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        # Admins see all branches including inactive ones.
        # Sellers only see active branches.
        qs = Branch.objects.all()
        if self.request.user.role == "seller":
            qs = qs.filter(is_active=True)
        return qs


class BranchDetailView(AuditedUpdateMixin, generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/branches/{id}/  → Retrieve branch detail
    PATCH /api/v1/branches/{id}/  → Update branch (admin only)

    Branches are never deleted — deactivate via is_active=False.
    Updates are recorded in the audit trail (BUSINESS_RULES §13).
    """
    queryset          = Branch.objects.all()
    serializer_class   = BranchSerializer
    audit_model_name   = "Branch"

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAdmin()]
        return [IsAuthenticated()]
