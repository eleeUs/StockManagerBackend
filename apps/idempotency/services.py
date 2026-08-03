"""
apps/idempotency/services.py

Mirrors the concurrency pattern already established in
apps/movements/services.py: select_for_update() inside transaction.atomic()
to serialize concurrent access to the same row, and a get_or_create-style
helper to handle the race where two requests with the same key arrive at
almost the same time.

IMPORTANT: get_or_create_and_lock() must be called from inside a
transaction.atomic() block that the CALLER controls and that wraps the
entire request — see the "no status field" rationale in
apps/idempotency/models.py and docs/phase8_prompt.md. This service does
not open its own top-level transaction because the whole point is that
the idempotency row and the business mutation it's caching commit or
roll back together, as one unit, from a transaction opened by the mixin
in Part 2.
"""
import hashlib
import json
import logging
from datetime import timedelta

from django.utils import timezone

from apps.idempotency.models import IdempotencyKey
from core.exceptions import IdempotencyKeyConflictError

logger = logging.getLogger(__name__)

DEFAULT_TTL = timedelta(hours=24)


class IdempotencyService:

    @staticmethod
    def hash_body(data: dict) -> str:
        """
        sha256 hex digest of a canonical (sorted-key) JSON dump of the
        request body. Deterministic and order-independent — two dicts
        with the same keys/values in different insertion order hash the
        same, since insertion order is not part of the semantic content
        of the request.

        default=str handles any non-JSON-native values DRF's parsed
        request.data might still contain (e.g. Decimal, if a custom
        parser ever produces one) without raising.
        """
        canonical = json.dumps(data or {}, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def get_or_create_and_lock(
        cls,
        *,
        user,
        key: str,
        endpoint: str,
        request_hash: str,
    ):
        """
        MUST be called inside a transaction.atomic() block opened by the
        caller (see module docstring).

        Returns (row: IdempotencyKey | None, created: bool):

        - (None, True)   → no prior row for this (user, key, endpoint).
          The caller must proceed with the business operation and call
          store_response() with the same `key`/`endpoint` before the
          transaction commits.
        - (row, False)   → a prior row exists and has been locked with
          select_for_update(). Its data is final — a row only ever
          exists in a fully-committed, successful state (see
          apps/idempotency/models.py). The caller must NOT re-run the
          business operation; it must return the cached response as-is.

        Raises IdempotencyKeyConflictError if a prior row exists for this
        (user, key, endpoint) but its request_hash doesn't match — the
        client reused the key for a logically different request, which is
        never safe to silently replay.
        """
        row, created = IdempotencyKey.objects.select_for_update().get_or_create(
            user=user,
            key=key,
            endpoint=endpoint,
            defaults={
                "request_hash": request_hash,
                # Placeholder values — overwritten by store_response()
                # before commit. Not nullable by design (see model
                # docstring), so a value must exist here even transiently
                # within the same still-open transaction.
                "response_status": 0,
                "response_body": {},
                "expires_at": timezone.now() + DEFAULT_TTL,
            },
        )

        if created:
            return None, True

        if row.request_hash != request_hash:
            logger.warning(
                "Idempotency key reuse with different body: user=%s key=%s endpoint=%s",
                user.id, key, endpoint,
            )
            raise IdempotencyKeyConflictError(
                "This Idempotency-Key was already used with a different request."
            )

        return row, False

    @staticmethod
    def store_response(*, user, key: str, endpoint: str, response_status: int, response_body) -> None:
        """
        Populates the final response_status/response_body on the row
        created by get_or_create_and_lock() in this same transaction.
        Called by the mixin only after the wrapped business operation has
        actually succeeded (2xx) — never for an error response, since an
        error response must not be cached (see rollback semantics in
        apps/idempotency/models.py).
        """
        IdempotencyKey.objects.filter(user=user, key=key, endpoint=endpoint).update(
            response_status=response_status,
            response_body=response_body,
        )
