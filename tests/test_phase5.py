"""
tests/test_phase5.py

Tests for health check, rate limiting, password change,
and request ID propagation.

Run: pytest tests/test_phase5.py -v
"""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tests.factories import AdminFactory, BranchFactory, SellerFactory

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealthCheck:
    """
    /health/ is kept as a permanent alias of /health/ready/ (see
    config/urls.py) — these tests confirm that alias contract still
    holds. Dedicated liveness/readiness behavior is covered separately
    below by TestLiveness and TestReadiness.
    """

    def test_health_returns_200_when_db_ok(self, api_client):
        """GET /health/ returns 200 when the database is reachable."""
        response = api_client.get("/health/")
        assert response.status_code == 200
        assert response.data["status"] == "ok"
        assert response.data["database"] == "ok"

    def test_health_requires_no_authentication(self, api_client):
        """
        Health endpoint must be accessible without a token.
        Monitoring systems and load balancers do not authenticate.
        """
        # api_client is unauthenticated by default
        response = api_client.get("/health/")
        assert response.status_code == 200

    def test_health_returns_503_when_db_unavailable(self, api_client):
        """GET /health/ returns 503 when the database is unreachable."""
        with patch(
            "core.views._check_database",
            return_value="unavailable",
        ):
            response = api_client.get("/health/")

        assert response.status_code == 503
        assert response.data["status"] == "error"
        assert response.data["database"] == "unavailable"

    def test_health_response_includes_both_fields(self, api_client):
        """Response shape must always include 'status' and 'database'."""
        response = api_client.get("/health/")
        assert "status" in response.data
        assert "database" in response.data


@pytest.mark.django_db
class TestLiveness:
    """
    GET /health/live/ — process-alive check only. Must never depend on
    the database: a DB outage is a reason to pull this instance out of
    a load balancer (readiness), never a reason to restart the process
    (liveness) — restarting fixes nothing and can turn a transient DB
    blip into a fleet-wide crash-loop. See core/views.py::LivenessView.
    """

    def test_liveness_returns_200(self, api_client):
        response = api_client.get("/health/live/")
        assert response.status_code == 200
        assert response.data["status"] == "ok"

    def test_liveness_ignores_database_state(self, api_client):
        """
        The key property this whole split exists for: liveness must
        stay 200 even when the database is down.
        """
        with patch(
            "core.views._check_database",
            return_value="unavailable",
        ):
            response = api_client.get("/health/live/")

        assert response.status_code == 200
        assert response.data["status"] == "ok"

    def test_liveness_requires_no_authentication(self, api_client):
        response = api_client.get("/health/live/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestReadiness:
    """
    GET /health/ready/ — same DB-checking behavior /health/ has always
    had, just reachable under its own explicit name too.
    """

    def test_readiness_returns_200_when_db_ok(self, api_client):
        response = api_client.get("/health/ready/")
        assert response.status_code == 200
        assert response.data["status"] == "ok"
        assert response.data["database"] == "ok"

    def test_readiness_returns_503_when_db_unavailable(self, api_client):
        with patch(
            "core.views._check_database",
            return_value="unavailable",
        ):
            response = api_client.get("/health/ready/")

        assert response.status_code == 503
        assert response.data["status"] == "error"
        assert response.data["database"] == "unavailable"

    def test_readiness_requires_no_authentication(self, api_client):
        response = api_client.get("/health/ready/")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Login rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoginRateLimit:
    def test_login_succeeds_within_rate_limit(self, api_client):
        """Valid login credentials return 200 within the rate limit."""
        user = AdminFactory()
        user.set_password("correctpassword")
        user.save()

        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": user.email,
                "password": "correctpassword",
            },
            format="json",
        )

        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_throttled_after_limit(self, db):
        """
        Excessive login attempts from the same IP return 429.
        We mock the throttle's allow_request to simulate the rate
        being exceeded without actually waiting.
        """
        client = APIClient()
        # Set a consistent REMOTE_ADDR so all requests count against the same IP
        client.defaults["REMOTE_ADDR"] = "192.168.1.100"

        with (
            patch(
                "core.views.LoginRateThrottle.allow_request",
                return_value=False,
            ),
            patch(
                "core.views.LoginRateThrottle.wait",
                return_value=60,
            ),
        ):
            response = client.post(
                "/api/v1/auth/login/",
                {
                    "email": "any@test.com",
                    "password": "any",
                },
                format="json",
            )

        assert response.status_code == 429

    def test_login_throttle_not_applied_to_other_endpoints(self, db):
        """
        LoginRateThrottle must only apply to the login endpoint.
        Other endpoints use the standard AnonRateThrottle/UserRateThrottle.
        """
        client = APIClient()
        with patch(
            "core.views.LoginRateThrottle.allow_request",
            return_value=False,
        ):
            # Health check should not be affected by login throttle
            response = client.get("/health/")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangePassword:
    def setup_method(self):
        self.branch = BranchFactory()
        self.user = SellerFactory(branch=self.branch)
        self.user.set_password("OldPassword1!")
        self.user.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_change_password_succeeds_with_correct_current(self):
        """Valid current password + new password returns 204."""
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPassword1!",
                "new_password": "NewPassword2@",
                "confirm_password": "NewPassword2@",
            },
            format="json",
        )

        assert response.status_code == 204

    def test_password_is_actually_changed_in_db(self):
        """After a successful change, old password no longer authenticates."""
        self.client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPassword1!",
                "new_password": "NewPassword2@",
                "confirm_password": "NewPassword2@",
            },
            format="json",
        )

        self.user.refresh_from_db()
        assert self.user.check_password("NewPassword2@") is True
        assert self.user.check_password("OldPassword1!") is False

    def test_wrong_current_password_returns_400(self):
        """Incorrect current password is rejected with 400."""
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "WrongPassword!",
                "new_password": "NewPassword2@",
                "confirm_password": "NewPassword2@",
            },
            format="json",
        )

        assert response.status_code == 400

    def test_mismatched_new_passwords_returns_400(self):
        """new_password and confirm_password must match."""
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPassword1!",
                "new_password": "NewPassword2@",
                "confirm_password": "DifferentPassword3#",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "confirm_password" in response.data

    def test_same_password_returns_400(self):
        """New password must differ from current password."""
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPassword1!",
                "new_password": "OldPassword1!",
                "confirm_password": "OldPassword1!",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "new_password" in response.data

    def test_short_new_password_returns_400(self):
        """New password must be at least 8 characters."""
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPassword1!",
                "new_password": "short",
                "confirm_password": "short",
            },
            format="json",
        )

        assert response.status_code == 400

    def test_unauthenticated_cannot_change_password(self):
        """Change password requires authentication."""
        client = APIClient()  # unauthenticated
        response = client.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": "OldPassword1!",
                "new_password": "NewPassword2@",
                "confirm_password": "NewPassword2@",
            },
            format="json",
        )

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestID:
    def test_response_includes_x_request_id_header(self, api_client):
        """Every response must include an X-Request-ID header."""
        response = api_client.get("/health/")
        assert "X-Request-ID" in response

    def test_custom_request_id_is_propagated(self, api_client):
        """
        If the client sends X-Request-ID, the same value is returned.
        This allows distributed tracing across services.
        """
        custom_id = "trace-abc-123"
        response = api_client.get("/health/", HTTP_X_REQUEST_ID=custom_id)
        assert response["X-Request-ID"] == custom_id

    def test_server_generates_id_when_not_provided(self, api_client):
        """If no X-Request-ID is sent, the server generates a UUID."""
        response = api_client.get("/health/")
        request_id = response["X-Request-ID"]

        import uuid

        # Must be a valid UUID string
        uuid.UUID(request_id)  # raises ValueError if invalid
