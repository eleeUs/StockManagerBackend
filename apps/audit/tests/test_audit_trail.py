"""
apps/audit/tests/test_audit_trail.py
"""
import pytest
from decimal import Decimal

from tests.factories import ProductFactory, BranchFactory, SellerFactory, CategoryFactory
from apps.audit.models import AuditLog


@pytest.mark.django_db
class TestProductAuditCapture:

    def test_update_creates_audit_log_entry(self, admin_client):
        client, admin = admin_client
        product = ProductFactory(name="Old Name")

        response = client.patch(f"/api/v1/products/{product.id}/", {"name": "New Name"})

        assert response.status_code == 200
        entry = AuditLog.objects.get(model_name="Product", object_id=product.id)
        assert entry.action == "update"
        assert entry.changed_by_id == admin.id
        assert entry.changes == {"name": {"old": "Old Name", "new": "New Name"}}

    def test_deactivation_is_recorded_as_deactivate_action(self, admin_client):
        client, admin = admin_client
        product = ProductFactory(is_active=True)

        client.patch(f"/api/v1/products/{product.id}/", {"is_active": False})

        entry = AuditLog.objects.get(model_name="Product", object_id=product.id)
        assert entry.action == "deactivate"

    def test_no_op_update_creates_no_entry(self, admin_client):
        client, admin = admin_client
        product = ProductFactory(name="Same Name")

        response = client.patch(f"/api/v1/products/{product.id}/", {"name": "Same Name"})

        assert response.status_code == 200
        assert not AuditLog.objects.filter(model_name="Product", object_id=product.id).exists()

    def test_fk_field_diff_stores_pk_not_object_repr(self, admin_client):
        client, admin = admin_client
        old_category = CategoryFactory()
        new_category = CategoryFactory()
        product = ProductFactory(category=old_category)

        client.patch(f"/api/v1/products/{product.id}/", {"category": new_category.id})

        entry = AuditLog.objects.get(model_name="Product", object_id=product.id)
        assert entry.changes["category"] == {"old": old_category.id, "new": new_category.id}

    def test_decimal_field_diff_is_json_safe(self, admin_client):
        client, admin = admin_client
        product = ProductFactory(cost_price=Decimal("10.00"))

        response = client.patch(f"/api/v1/products/{product.id}/", {"cost_price": "12.50"})

        assert response.status_code == 200
        entry = AuditLog.objects.get(model_name="Product", object_id=product.id)
        assert entry.changes["cost_price"] == {"old": "10.00", "new": "12.50"}


@pytest.mark.django_db
class TestBranchAuditCapture:

    def test_update_creates_audit_log_entry(self, admin_client):
        client, admin = admin_client
        branch = BranchFactory(name="Old Branch")

        client.patch(f"/api/v1/branches/{branch.id}/", {"name": "New Branch"})

        entry = AuditLog.objects.get(model_name="Branch", object_id=branch.id)
        assert entry.changes["name"] == {"old": "Old Branch", "new": "New Branch"}


@pytest.mark.django_db
class TestUserAuditCapture:

    def test_role_reassignment_creates_audit_log_entry(self, admin_client):
        client, admin = admin_client
        branch = BranchFactory()
        seller = SellerFactory(branch=branch, full_name="Old Name")

        client.patch(f"/api/v1/users/{seller.id}/", {"full_name": "New Name"})

        entry = AuditLog.objects.get(model_name="User", object_id=seller.id)
        assert entry.changes["full_name"] == {"old": "Old Name", "new": "New Name"}

    def test_password_change_endpoint_is_not_audited_by_this_mixin(self, admin_client):
        """
        Sanity check on scope: ChangePasswordView is a separate APIView,
        not a RetrieveUpdateAPIView, so AuditedUpdateMixin never applies
        to it — there is no risk of a password ever landing in
        AuditLog.changes. UpdateUserSerializer doesn't expose a password
        field at all (see apps/users/serializers.py), which is the other
        half of that guarantee.
        """
        from apps.users.serializers import UpdateUserSerializer
        assert "password" not in UpdateUserSerializer.Meta.fields


@pytest.mark.django_db
class TestAuditLogEndpoint:

    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/v1/audit-log/")
        assert response.status_code == 401

    def test_seller_cannot_access(self, seller_client):
        client, user, branch = seller_client
        response = client.get("/api/v1/audit-log/")
        assert response.status_code == 403

    def test_admin_sees_entries(self, admin_client):
        client, admin = admin_client
        product = ProductFactory(name="A")
        client.patch(f"/api/v1/products/{product.id}/", {"name": "B"})

        response = client.get("/api/v1/audit-log/")

        assert response.status_code == 200
        assert response.data["count"] >= 1

    def test_filter_by_model_and_object_id(self, admin_client):
        client, admin = admin_client
        product = ProductFactory(name="A")
        branch = BranchFactory(name="X")
        client.patch(f"/api/v1/products/{product.id}/", {"name": "B"})
        client.patch(f"/api/v1/branches/{branch.id}/", {"name": "Y"})

        response = client.get("/api/v1/audit-log/", {"model": "Product", "object_id": product.id})

        assert response.status_code == 200
        assert all(r["model_name"] == "Product" for r in response.data["results"])
        assert all(r["object_id"] == product.id for r in response.data["results"])
