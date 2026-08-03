"""
core/views.py

Health check endpoint and login rate throttle.
"""
from django.db import connection
from django.db.utils import OperationalError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle


class HealthCheckView(APIView):
    """
    GET /health/

    Verifies that the API process is running and the database is reachable.
    Used by Docker healthchecks, load balancers, and uptime monitors.

    No authentication required — monitoring systems must be able to call
    this endpoint without a token.

    Responses:
      200 {"status": "ok",    "database": "ok"}
      503 {"status": "error", "database": "unavailable"}

    The database check executes a trivial SELECT 1 — it costs nothing
    but proves the connection pool is alive and the DB is accepting queries.
    It does NOT verify data integrity or schema correctness.
    """
    permission_classes     = [AllowAny]
    authentication_classes = []

    def get(self, request):
        db_status = self._check_database()
        overall   = db_status == "ok"

        return Response(
            {
                "status":   "ok" if overall else "error",
                "database": db_status,
            },
            status=status.HTTP_200_OK if overall else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _check_database() -> str:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return "ok"
        except OperationalError:
            return "unavailable"


class LoginRateThrottle(AnonRateThrottle):
    """
    Rate limiter for the login endpoint.

    Throttles by client IP address (not by user, since the user is not
    authenticated at login time). The scope 'login' maps to the rate
    defined in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'].

    Default rate: 5 attempts per minute per IP.

    Why 5/minute:
      - A legitimate user who misremembers their password will retry
        2-3 times before resetting. 5 gives comfortable headroom.
      - An attacker attempting dictionary attacks at this rate would
        take 833 hours to try 250,000 common passwords from a single IP.
        Combined with Argon2 hashing (~100ms per attempt server-side),
        the effective attack rate is negligible.

    In production behind a reverse proxy, ensure the proxy forwards the
    real client IP via X-Forwarded-For and configure Django's
    TRUSTED_PROXIES / USE_X_FORWARDED_HOST accordingly so throttling
    is not applied to the proxy's IP instead of the client's.
    """
    scope = "login"
