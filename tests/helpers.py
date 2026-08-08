"""
tests/helpers.py

Shared test helpers, alongside tests/factories.py.
"""
import uuid


def idempotent_post(client, url, data=None, **kwargs):
    """
    POST with an auto-generated Idempotency-Key header.

    Use this for any call to a stock-mutating endpoint in a test where
    key reuse isn't the point of the test — which is nearly all of them.
    A fresh UUID is generated per call by default, so two calls in the
    same test (e.g. create a transfer, then confirm it) never
    accidentally collide on the same key.

    Tests that specifically exercise replay/conflict behavior (see
    apps/movements/tests/test_idempotency_wiring.py) construct the
    Idempotency-Key header manually instead, since the whole point there
    is controlling whether the key repeats.
    """
    key = kwargs.pop("idempotency_key", None) or str(uuid.uuid4())
    return client.post(url, data, HTTP_IDEMPOTENCY_KEY=key, **kwargs)
