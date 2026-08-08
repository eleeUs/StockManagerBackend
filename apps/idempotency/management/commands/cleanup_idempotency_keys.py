"""
Management command: cleanup_idempotency_keys

Deletes IdempotencyKey rows past their expires_at. Same shape as
check_low_stock (Phase 7): cron-facing, no task queue, since the project
intentionally has none (see phase6_prompt.md).

Usage:
    python manage.py cleanup_idempotency_keys
    python manage.py cleanup_idempotency_keys --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.idempotency.models import IdempotencyKey


class Command(BaseCommand):
    help = "Delete IdempotencyKey rows past their expires_at."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        expired = IdempotencyKey.objects.filter(expires_at__lt=timezone.now())
        count = expired.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No expired idempotency keys found."))
            return

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(f"[dry-run] Would delete {count} expired idempotency key(s).")
            )
            return

        deleted, _ = expired.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired idempotency key(s)."))
