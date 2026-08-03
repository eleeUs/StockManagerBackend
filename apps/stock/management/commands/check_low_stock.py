"""
Management command: check_low_stock

Scans Stock rows against their configured reorder_point and reports any
that are at or below it. The project intentionally has no Celery/async
task queue (see phase6_prompt.md "Do not" list), so this is designed to
be invoked on a schedule externally — cron, a k8s CronJob, etc. — rather
than as a background task.

Rows with reorder_point=None are skipped entirely: null means "no alert
configured for this row", not "use some global default" (BUSINESS_RULES §11).

Usage:
    python manage.py check_low_stock
    python manage.py check_low_stock --webhook-url https://hooks.example.com/low-stock
"""
import json
import logging
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand
from django.db.models import F

from apps.stock.models import Stock

logger = logging.getLogger("apps.stock")


class Command(BaseCommand):
    help = "Check stock rows against their reorder_point and report low-stock alerts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--webhook-url",
            default=None,
            help="Optional URL to POST a JSON payload of low-stock rows to.",
        )

    def handle(self, *args, **options):
        low_stock = (
            Stock.objects
            .select_related("product", "branch")
            .filter(reorder_point__isnull=False, quantity__lte=F("reorder_point"))
            .order_by("branch__name", "product__name")
        )

        if not low_stock.exists():
            self.stdout.write(self.style.SUCCESS("No low-stock rows found."))
            return

        rows = []
        for stock in low_stock:
            rows.append({
                "product_sku":   stock.product.sku,
                "product_name":  stock.product.name,
                "branch_id":     stock.branch_id,
                "branch_name":   stock.branch.name,
                "quantity":      str(stock.quantity),
                "reorder_point": str(stock.reorder_point),
            })
            logger.warning(
                "LOW STOCK: product=%s branch=%s qty=%s reorder_point=%s",
                stock.product.sku, stock.branch.name, stock.quantity, stock.reorder_point,
            )
            self.stdout.write(
                self.style.WARNING(
                    f"  [!] {stock.branch.name:12} | {stock.product.sku:10} | "
                    f"qty={stock.quantity} <= reorder_point={stock.reorder_point}"
                )
            )

        self.stdout.write(self.style.WARNING(f"\n{len(rows)} low-stock row(s) found.\n"))

        webhook_url = options.get("webhook_url")
        if webhook_url:
            self._send_webhook(webhook_url, rows)

    def _send_webhook(self, url, rows):
        """
        stdlib-only POST — no new dependency added just for this. If the
        webhook needs richer behaviour (retries, auth headers) later,
        that's the point to reach for `requests`, not before.
        """
        payload = json.dumps({"low_stock": rows}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                self.stdout.write(self.style.SUCCESS(f"Webhook notified: HTTP {response.status}"))
        except urllib.error.URLError as exc:
            logger.error("Failed to notify low-stock webhook: %s", exc)
            self.stdout.write(self.style.ERROR(f"Webhook notification failed: {exc}"))
