from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class IdempotencyKey(models.Model):
    """
    Caches the response of a stock-mutating request so that a network-level
    retry (client timeout, dropped connection) replays the original result
    instead of re-executing the operation — e.g. a repeated 'venta' POST
    must not sell the same stock twice.

    DESIGN — no status/state-machine field, on purpose:
    A row is written here ONLY after the wrapped business operation
    committed successfully. The mixin that writes these rows (Part 2)
    wraps the whole request — header validation, the lock on this table,
    AND the call into the view's business logic — inside a single
    transaction.atomic() block. If the business operation raises a domain
    exception, the entire transaction rolls back, and this row rolls back
    with it (Django turns the inner transaction.atomic() calls made by the
    service layer into savepoints of the same outer transaction).

    The consequence: a row existing for a given (user, key, endpoint) is
    proof, by construction, that a request with that exact body already
    succeeded. There's nothing to represent "processing" — a request that
    is currently running either hasn't reached this table yet, or hasn't
    committed yet, in which case select_for_update() blocks a concurrent
    lookup until it does one or the other. See apps/idempotency/services.py
    and docs/phase8_prompt.md for the full rollback-semantics rationale
    and the DRF-specific trap (dispatch() swallows exceptions internally,
    so rollback must be triggered explicitly on 4xx responses, not relied
    upon via a propagated exception).
    """
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )
    # Client-supplied value from the Idempotency-Key header (e.g. a UUID).
    key = models.CharField(max_length=255)
    # request.path — scopes a key to the specific endpoint it was used on,
    # so the same key value can't accidentally collide across two
    # different operations if a client's key generation isn't unique
    # enough on its own.
    endpoint = models.CharField(max_length=255)
    # sha256 hex digest of the request body. Lets us tell "legitimate
    # replay of the same request" apart from "this key was reused for a
    # different request" — the latter is a client bug and must be
    # rejected (409), never silently served the wrong cached response.
    request_hash = models.CharField(max_length=64)

    response_status = models.PositiveSmallIntegerField()
    # DjangoJSONEncoder (not the plain json default) so a stored
    # response containing Decimal/date/datetime/UUID values — anything a
    # DRF serializer can legitimately produce in .data — never raises a
    # TypeError on save. DRF DecimalFields already serialize to str by
    # default, but this is cheap insurance against a future serializer
    # that doesn't.
    response_body = models.JSONField(encoder=DjangoJSONEncoder)

    created_at = models.DateTimeField(auto_now_add=True)
    # Rows are pruned by the cleanup_idempotency_keys management command
    # (Part 3) rather than kept forever.
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key", "endpoint"],
                name="idempotency_key_unique_per_user_endpoint",
            ),
        ]
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"{self.endpoint} · {self.key} (user={self.user_id})"
