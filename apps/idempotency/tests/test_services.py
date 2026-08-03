"""
apps/idempotency/tests/test_services.py

Part 1 scope only: tests apps/idempotency/ entirely in isolation. No HTTP
client, no existing view — IdempotentMutationMixin isn't wired into
anything yet (that's Part 2). See docs/phase8_prompt.md.
"""
import threading

import pytest
from django.db import transaction
from django.test import TestCase, TransactionTestCase

from tests.factories import AdminFactory
from apps.idempotency.models import IdempotencyKey
from apps.idempotency.services import IdempotencyService
from core.exceptions import IdempotencyKeyConflictError, InsufficientStockError


class TestHashBody(TestCase):
    """Deterministic, order-independent hashing of the request body."""

    def test_same_content_different_key_order_hashes_identically(self):
        h1 = IdempotencyService.hash_body({"a": 1, "b": 2})
        h2 = IdempotencyService.hash_body({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_content_hashes_differently(self):
        h1 = IdempotencyService.hash_body({"quantity": 1})
        h2 = IdempotencyService.hash_body({"quantity": 2})
        assert h1 != h2

    def test_empty_body_does_not_raise(self):
        # Should never happen for a POST in this project, but hash_body
        # must not blow up on it — None/{} are equally "no content".
        assert IdempotencyService.hash_body(None) == IdempotencyService.hash_body({})


class TestGetOrCreateAndLock(TestCase):

    def setUp(self):
        self.user = AdminFactory()
        self.key = "11111111-1111-1111-1111-111111111111"
        self.endpoint = "/api/v1/movements/venta/"
        self.hash = IdempotencyService.hash_body({"product": 1, "quantity": "5"})

    def test_first_call_returns_created_true(self):
        with transaction.atomic():
            row, created = IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint=self.endpoint,
                request_hash=self.hash,
            )
        assert created is True
        assert row is None

    def test_replay_with_matching_hash_returns_cached_row(self):
        with transaction.atomic():
            IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint=self.endpoint,
                request_hash=self.hash,
            )
            IdempotencyService.store_response(
                user=self.user, key=self.key, endpoint=self.endpoint,
                response_status=201, response_body={"id": 42},
            )

        with transaction.atomic():
            row, created = IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint=self.endpoint,
                request_hash=self.hash,
            )

        assert created is False
        assert row.response_status == 201
        assert row.response_body == {"id": 42}

    def test_replay_with_different_hash_raises_conflict(self):
        with transaction.atomic():
            IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint=self.endpoint,
                request_hash=self.hash,
            )
            IdempotencyService.store_response(
                user=self.user, key=self.key, endpoint=self.endpoint,
                response_status=201, response_body={"id": 42},
            )

        different_hash = IdempotencyService.hash_body({"product": 1, "quantity": "999"})
        with pytest.raises(IdempotencyKeyConflictError):
            with transaction.atomic():
                IdempotencyService.get_or_create_and_lock(
                    user=self.user, key=self.key, endpoint=self.endpoint,
                    request_hash=different_hash,
                )

    def test_same_key_different_endpoint_does_not_collide(self):
        # A client's key generation not being globally unique shouldn't
        # cause a false conflict across two unrelated operations.
        with transaction.atomic():
            _, created_first = IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint="/api/v1/movements/venta/",
                request_hash=self.hash,
            )
        with transaction.atomic():
            _, created_second = IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint="/api/v1/movements/ingreso/",
                request_hash=self.hash,
            )
        assert created_first is True
        assert created_second is True


class TestRollbackSemantics(TestCase):
    """
    The design this whole app depends on: a row must never persist for a
    business operation that didn't actually succeed. See the docstring on
    apps/idempotency/models.py::IdempotencyKey for the full rationale.
    """

    def setUp(self):
        self.user = AdminFactory()
        self.key = "22222222-2222-2222-2222-222222222222"
        self.endpoint = "/api/v1/movements/venta/"
        self.hash = IdempotencyService.hash_body({"product": 1})

    def test_row_does_not_persist_if_wrapped_operation_raises(self):
        """
        Simulates exactly what Part 2's mixin does: get_or_create_and_lock()
        followed by the business operation, all inside one
        transaction.atomic() block. If the business operation raises,
        the whole block must roll back, taking the not-yet-committed
        IdempotencyKey row down with it.
        """
        with pytest.raises(InsufficientStockError):
            with transaction.atomic():
                row, created = IdempotencyService.get_or_create_and_lock(
                    user=self.user, key=self.key, endpoint=self.endpoint,
                    request_hash=self.hash,
                )
                assert created is True
                raise InsufficientStockError("not enough stock")

        assert not IdempotencyKey.objects.filter(
            user=self.user, key=self.key, endpoint=self.endpoint
        ).exists()

    def test_retry_after_rolled_back_failure_is_a_fresh_attempt(self):
        """
        A retry with the same key after a genuine failure must be allowed
        to actually re-run the business logic — it is not a replay of a
        cached response, because no response was ever cached.
        """
        with pytest.raises(InsufficientStockError):
            with transaction.atomic():
                IdempotencyService.get_or_create_and_lock(
                    user=self.user, key=self.key, endpoint=self.endpoint,
                    request_hash=self.hash,
                )
                raise InsufficientStockError("not enough stock")

        # Retry: same key, same hash. Must be created=True again, not a
        # replay — the first attempt never committed.
        with transaction.atomic():
            row, created = IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint=self.endpoint,
                request_hash=self.hash,
            )
        assert created is True
        assert row is None

    def test_row_persists_when_operation_succeeds(self):
        """Control case: the row IS there when the block commits cleanly."""
        with transaction.atomic():
            IdempotencyService.get_or_create_and_lock(
                user=self.user, key=self.key, endpoint=self.endpoint,
                request_hash=self.hash,
            )
            IdempotencyService.store_response(
                user=self.user, key=self.key, endpoint=self.endpoint,
                response_status=201, response_body={"id": 1},
            )

        assert IdempotencyKey.objects.filter(
            user=self.user, key=self.key, endpoint=self.endpoint
        ).exists()


class TestConcurrentIdempotencyKey(TransactionTestCase):
    """
    Two requests with the same key arriving at almost the same time (e.g.
    a double-tap on a submit button) must not both execute the business
    operation. Real threads + TransactionTestCase, same pattern as
    TestConcurrentVenta in apps/movements/tests/test_services.py — a
    shared connection wrapped in one transaction (plain TestCase) can't
    exercise real cross-transaction locking.
    """

    def setUp(self):
        self.user = AdminFactory()
        self.key = "33333333-3333-3333-3333-333333333333"
        self.endpoint = "/api/v1/movements/venta/"
        self.hash = IdempotencyService.hash_body({"product": 1, "quantity": "5"})

    def test_only_one_concurrent_caller_gets_created_true(self):
        created_flags = []

        def attempt():
            with transaction.atomic():
                row, created = IdempotencyService.get_or_create_and_lock(
                    user=self.user, key=self.key, endpoint=self.endpoint,
                    request_hash=self.hash,
                )
                if created:
                    IdempotencyService.store_response(
                        user=self.user, key=self.key, endpoint=self.endpoint,
                        response_status=201, response_body={"ok": True},
                    )
                created_flags.append(created)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert created_flags.count(True) == 1, f"Expected exactly 1 created=True, got {created_flags}"
        assert created_flags.count(False) == 1, f"Expected exactly 1 created=False, got {created_flags}"
        assert IdempotencyKey.objects.filter(
            user=self.user, key=self.key, endpoint=self.endpoint
        ).count() == 1
