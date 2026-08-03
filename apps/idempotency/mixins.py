"""
apps/idempotency/mixins.py

IdempotentMutationMixin — NOT applied to any view yet (that's Part 2 of
Phase 8, see docs/phase8_prompt.md). Built and tested in isolation here.

WHY THIS HOOKS post(), NOT dispatch() OR initial():

DRF's APIView.dispatch() always calls self.initial(request, *args, **kwargs)
— which runs authentication and permission_classes checks — BEFORE calling
the handler method (post()). A handler is only ever invoked after initial()
has already succeeded; if a permission check fails, initial() raises and
dispatch()'s own try/except turns that into a 403 without post() ever
running.

That ordering is exactly what BUSINESS_RULES requires: a seller hitting an
admin-only endpoint must get 403, not 400 for a missing Idempotency-Key
header — the endpoint's idempotency requirement shouldn't be revealed to a
caller who isn't authorized to call it at all.

Overriding dispatch() or initial() ourselves would mean reimplementing (or
very carefully re-delegating) DRF's own permission-checking flow, which is
fragile and easy to get subtly wrong. Overriding post() gets the correct
ordering for free, with zero DRF internals touched: by the time our post()
runs, initial() has already succeeded.

The trade-off: every view that uses this mixin must implement
perform_mutation() instead of post() directly (Part 2 renames post() to
perform_mutation() on the nine write views). That's a one-line rename per
view — a small, mechanical cost for not having to reimplement DRF's
request-dispatch internals.
"""
from django.conf import settings
from django.db import transaction
from rest_framework.response import Response

from apps.idempotency.services import IdempotencyService
from core.exceptions import IdempotencyKeyRequiredError

IDEMPOTENCY_KEY_HEADER = "HTTP_IDEMPOTENCY_KEY"


class IdempotentMutationMixin:
    """
    Mix into an APIView subclass, before it in the MRO, e.g.:

        class VentaView(IdempotentMutationMixin, APIView):
            def perform_mutation(self, request, *args, **kwargs):
                ...  # what used to be post()

    Do NOT define post() on a view that uses this mixin — this mixin's
    post() IS the entry point; perform_mutation() is what a subclass
    implements instead.
    """

    def post(self, request, *args, **kwargs):
        key = request.META.get(IDEMPOTENCY_KEY_HEADER)

        if not key:
            if getattr(settings, "IDEMPOTENCY_KEY_REQUIRED", True):
                raise IdempotencyKeyRequiredError(
                    "This endpoint requires an Idempotency-Key header."
                )
            # IDEMPOTENCY_KEY_REQUIRED=False and no header sent — behave
            # exactly as if this mixin weren't applied at all.
            return self.perform_mutation(request, *args, **kwargs)

        endpoint = request.path
        request_hash = IdempotencyService.hash_body(request.data)

        with transaction.atomic():
            cached_row, created = IdempotencyService.get_or_create_and_lock(
                user=request.user,
                key=key,
                endpoint=endpoint,
                request_hash=request_hash,
            )

            if not created:
                # Legitimate replay: a prior request with this exact key
                # AND body already succeeded. Return the cached result
                # without touching perform_mutation() at all — the
                # business operation must not run twice.
                return Response(cached_row.response_body, status=cached_row.response_status)

            response = self.perform_mutation(request, *args, **kwargs)

            if response.status_code >= 400:
                # The business operation failed WITHOUT raising (e.g.
                # VentaView returns an explicit 403 for the seller/
                # wrong-branch case rather than raising). transaction.atomic()
                # only rolls back automatically on a propagated exception,
                # so a failure returned as a Response needs an explicit
                # rollback here — otherwise the IdempotencyKey row created
                # above by get_or_create_and_lock() would commit anyway,
                # permanently blocking a legitimate retry after the
                # underlying condition is fixed (e.g. stock replenished).
                transaction.set_rollback(True)
                return response

            IdempotencyService.store_response(
                user=request.user,
                key=key,
                endpoint=endpoint,
                response_status=response.status_code,
                response_body=response.data,
            )
            return response

    def perform_mutation(self, request, *args, **kwargs):
        raise NotImplementedError(
            f"{self.__class__.__name__} uses IdempotentMutationMixin but "
            f"does not implement perform_mutation()."
        )
