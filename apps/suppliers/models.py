from django.db import models


class Supplier(models.Model):
    """
    An external party that stock is formally received from via an
    INGRESO movement (BUSINESS_RULES §9).

    Deletion policy: never hard-deleted, same rationale as Branch and
    Product — historical movement records reference suppliers and must
    remain valid. PROTECT on the StockMovement.supplier FK enforces this
    at the database level. Deactivate via is_active=False instead.
    """
    name          = models.CharField(max_length=150, unique=True)
    contact_name  = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Supplier"
        verbose_name_plural = "Suppliers"
        ordering            = ["name"]

    def __str__(self):
        return self.name
