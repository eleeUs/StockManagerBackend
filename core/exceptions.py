from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


# ---------------------------------------------------------------------------
# Domain exceptions
# These are pure Python exceptions with no knowledge of HTTP.
# They are raised by the service layer and translated to HTTP
# responses by custom_exception_handler below.
# ---------------------------------------------------------------------------

class StockDomainError(Exception):
    """Base for all domain exceptions in the stock system."""
    pass


class InsufficientStockError(StockDomainError):
    """
    Raised when an operation would result in negative stock.
    Rule: stock can never go below zero (BUSINESS_RULES §2.1).
    """
    pass


class InvalidMovementError(StockDomainError):
    """
    Raised when a movement violates a business rule
    (e.g. same source and destination, zero quantity).
    """
    pass


class UnauthorizedMovementError(StockDomainError):
    """
    Raised when a user attempts an operation their role does not permit.
    This is a domain-level check — DRF permission classes handle
    HTTP-level authorization before the service is even called.
    """
    pass


class TransferAlreadyConfirmedError(StockDomainError):
    """
    Raised when trying to cancel a transfer that has already been confirmed.
    A confirmed transfer can only be reversed, not cancelled (BUSINESS_RULES §5).
    """
    pass


class ReturnExceedsSoldQuantityError(StockDomainError):
    """
    Raised when the quantity being returned exceeds the quantity
    originally sold in the referenced movement (BUSINESS_RULES §3.5).
    """
    pass


# ---------------------------------------------------------------------------
# DRF exception handler
# Maps domain exceptions to structured HTTP error responses.
# Registered in settings: REST_FRAMEWORK["EXCEPTION_HANDLER"]
# ---------------------------------------------------------------------------

_DOMAIN_EXCEPTION_MAP = {
    InsufficientStockError: (status.HTTP_400_BAD_REQUEST, "insufficient_stock"),
    InvalidMovementError: (status.HTTP_400_BAD_REQUEST, "invalid_movement"),
    UnauthorizedMovementError: (status.HTTP_403_FORBIDDEN, "unauthorized_movement"),
    TransferAlreadyConfirmedError: (status.HTTP_409_CONFLICT, "transfer_already_confirmed"),
    ReturnExceedsSoldQuantityError: (status.HTTP_400_BAD_REQUEST, "return_exceeds_sold_quantity"),
}


def custom_exception_handler(exc, context):
    """
    Error response format:
    {
        "error": "machine_readable_code",
        "detail": "Human readable message"
    }

    The "error" field is intended for the frontend to handle
    specific cases programmatically (show localized messages,
    redirect, etc.) without parsing free-form text.
    """
    for exc_class, (http_status, error_code) in _DOMAIN_EXCEPTION_MAP.items():
        if isinstance(exc, exc_class):
            return Response(
                {"error": error_code, "detail": str(exc)},
                status=http_status,
            )

    # Fall back to DRF's default handler for validation errors,
    # auth errors, etc.
    return exception_handler(exc, context)
