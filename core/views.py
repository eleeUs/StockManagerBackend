"""
core/views.py

Health check endpoints (liveness + readiness) and login rate throttle.
"""

from django.db import connection
from django.db.utils import OperationalError
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView


def _check_database() -> str:
    """
    Trivial SELECT 1 — costs nothing but proves the connection pool is
    alive and the DB is accepting queries. Does NOT verify data
    integrity or schema correctness. Shared by ReadinessView (and, via
    it, the legacy /health/ alias) — LivenessView never calls this.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return "ok"
    except OperationalError:
        return "unavailable"


class LivenessView(APIView):
    """
    GET /health/live/

    Answers exactly one question: is this process alive enough to
    handle a request at all? No dependencies are checked — not the
    database, nothing external. If this view runs and returns a
    response, the process is alive; if the process is actually dead or
    hung, the caller sees a connection failure or timeout, which is
    itself the failure signal an orchestrator needs.

    This is deliberately NOT the same check as readiness. A liveness
    probe answers "should this process be restarted?" — and a slow or
    temporarily unreachable database is never a reason to restart the
    process; restarting does nothing to fix the database, adds
    process-startup load on top of an already-struggling DB, and (with
    every replica hitting the same external outage at once) can turn a
    transient DB blip into a crash-loop across the whole fleet. See
    docs/commits.md / phase-9 history for the incident that prompted
    this split — /health/ used to do the DB check unconditionally and
    was wired to both liveness and readiness probes.

    No authentication required — monitoring systems must be able to
    call this endpoint without a token.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class ReadinessView(APIView):
    """
    GET /health/ready/  (also served at GET /health/ — see config/urls.py)

    Verifies that the API process is running AND the database is
    reachable. This is the check allowed to fail when the database is
    down — that's the point: a readiness failure tells a load balancer
    to pull this instance out of rotation, not to restart it.

    No authentication required — monitoring systems must be able to
    call this endpoint without a token.

    Responses:
      200 {"status": "ok",    "database": "ok"}
      503 {"status": "error", "database": "unavailable"}
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        db_status = _check_database()
        overall = db_status == "ok"

        return Response(
            {
                "status": "ok" if overall else "error",
                "database": db_status,
            },
            status=status.HTTP_200_OK if overall else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


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
