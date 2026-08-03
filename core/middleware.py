"""
core/middleware.py

RequestIDMiddleware assigns a unique UUID to every HTTP request.

The ID is:
  - Read from the incoming X-Request-ID header if present
    (allows tracing across services in a microservice setup).
  - Generated fresh via uuid4 if not provided.
  - Stored in thread-local storage so it is accessible from the
    logging filter without passing it through every function call.
  - Written to the X-Request-ID response header so clients can
    correlate their request with server-side logs.

When a user reports an error, they can share the X-Request-ID from
their browser's network inspector and you can grep the exact request
from production logs in seconds.

Usage in logs:
  Every log record automatically includes request_id via RequestIDFilter
  (registered in LOGGING settings). Format example:
    INFO 2026-01-15 14:23:01 views [req=a3f2c1d0] VENTA: product=5 qty=3

Usage in code:
    from core.middleware import get_request_id
    logger.info("Something happened", extra={"request_id": get_request_id()})
"""
import logging
import threading
import uuid

_thread_local = threading.local()


def get_request_id() -> str | None:
    """
    Returns the request ID for the current thread.
    Returns None outside of a request context.
    """
    return getattr(_thread_local, "request_id", None)


class RequestIDMiddleware:
    """
    Django middleware that assigns a UUID to every request.
    Must be near the top of MIDDLEWARE so all subsequent middleware
    and views have access to request.request_id.
    """

    HEADER_IN  = "HTTP_X_REQUEST_ID"   # Django converts hyphens to underscores
    HEADER_OUT = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Honour an upstream-provided ID; generate one if absent
        request_id = request.META.get(self.HEADER_IN) or str(uuid.uuid4())

        # Attach to request object for use in views
        request.request_id = request_id

        # Attach to thread-local for use in logging filter
        _thread_local.request_id = request_id

        response = self.get_response(request)

        # Propagate to response so clients can correlate
        response[self.HEADER_OUT] = request_id

        # Clean up thread-local to avoid leaking between requests
        # in a threaded server (gunicorn sync workers reuse threads)
        _thread_local.request_id = None

        return response


class RequestIDFilter(logging.Filter):
    """
    Logging filter that injects the current request ID into every log record.

    Register in LOGGING settings under 'filters' and attach to all handlers
    that should include the request ID in their format string.

    Log format example:
        "%(levelname)s %(asctime)s %(module)s [req=%(request_id)s] %(message)s"
    """

    def filter(self, record):
        record.request_id = get_request_id() or "-"
        return True
