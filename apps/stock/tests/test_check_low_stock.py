"""
apps/stock/tests/test_check_low_stock.py

Tests the check_low_stock management command in isolation from any HTTP
layer — it's a cron-facing command, not an endpoint.
"""
import io
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from django.core.management import call_command

from tests.factories import StockFactory


@pytest.mark.django_db
class TestCheckLowStockCommand:
    def test_no_output_when_nothing_is_low(self):
        StockFactory(quantity=Decimal("100"), reorder_point=Decimal("10"))

        out = io.StringIO()
        call_command("check_low_stock", stdout=out)

        assert "No low-stock rows found" in out.getvalue()

    def test_rows_without_reorder_point_are_skipped(self):
        # reorder_point=None (the factory default) — quantity is low but
        # unconfigured, so it must not trigger an alert.
        StockFactory(quantity=Decimal("1"))

        out = io.StringIO()
        call_command("check_low_stock", stdout=out)

        assert "No low-stock rows found" in out.getvalue()

    def test_reports_row_at_or_below_reorder_point(self):
        stock = StockFactory(quantity=Decimal("5"), reorder_point=Decimal("10"))

        out = io.StringIO()
        call_command("check_low_stock", stdout=out)

        output = out.getvalue()
        assert stock.product.sku in output
        assert "1 low-stock row(s) found" in output

    def test_webhook_receives_json_payload(self):
        StockFactory(quantity=Decimal("5"), reorder_point=Decimal("10"))

        mock_response = MagicMock()
        mock_response.status = 200
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        out = io.StringIO()
        with patch("urllib.request.urlopen", return_value=mock_context) as mock_urlopen:
            call_command("check_low_stock", "--webhook-url", "https://hooks.test/alert", stdout=out)

        assert mock_urlopen.called
        sent_request = mock_urlopen.call_args[0][0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        assert len(payload["low_stock"]) == 1
        assert "Webhook notified" in out.getvalue()
