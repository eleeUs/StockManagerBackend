"""
apps/idempotency/tests/test_cleanup_command.py
"""
import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from tests.factories import AdminFactory
from apps.idempotency.models import IdempotencyKey


def _make_key(user, key, delta):
    return IdempotencyKey.objects.create(
        user=user,
        key=key,
        endpoint="/api/v1/movements/venta/",
        request_hash="deadbeef",
        response_status=201,
        response_body={"id": 1},
        expires_at=timezone.now() + delta,
    )


@pytest.mark.django_db
class TestCleanupIdempotencyKeysCommand:

    def test_no_expired_rows_reports_nothing_to_do(self):
        user = AdminFactory()
        _make_key(user, "still-valid", timedelta(hours=1))

        out = io.StringIO()
        call_command("cleanup_idempotency_keys", stdout=out)

        assert "No expired idempotency keys found" in out.getvalue()
        assert IdempotencyKey.objects.count() == 1

    def test_deletes_only_expired_rows(self):
        user = AdminFactory()
        _make_key(user, "expired", timedelta(hours=-1))
        _make_key(user, "still-valid", timedelta(hours=1))

        out = io.StringIO()
        call_command("cleanup_idempotency_keys", stdout=out)

        assert "Deleted 1 expired idempotency key" in out.getvalue()
        remaining = list(IdempotencyKey.objects.values_list("key", flat=True))
        assert remaining == ["still-valid"]

    def test_dry_run_does_not_delete(self):
        user = AdminFactory()
        _make_key(user, "expired", timedelta(hours=-1))

        out = io.StringIO()
        call_command("cleanup_idempotency_keys", "--dry-run", stdout=out)

        assert "[dry-run] Would delete 1" in out.getvalue()
        assert IdempotencyKey.objects.count() == 1
