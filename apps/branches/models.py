from django.db import models


class Branch(models.Model):
    """
    Represents a physical or logical location that holds stock.

    Deletion policy: branches are never hard-deleted.
    Deactivating a branch (is_active=False) is the correct approach
    because the movement history must remain intact.
    The PROTECT on_delete in related models enforces this at the DB level.
    """
    name       = models.CharField(max_length=100, unique=True)
    address    = models.CharField(max_length=255, blank=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Branch"
        verbose_name_plural = "Branches"
        ordering            = ["name"]

    def __str__(self):
        return self.name
