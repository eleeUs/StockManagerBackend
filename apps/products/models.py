from django.db import models
from django.core.validators import MinValueValidator


class Category(models.Model):
    """
    Optional grouping for products.
    Using a separate table (not a CharField) allows renaming
    categories without a bulk update on the Product table.
    """
    name       = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Category"
        verbose_name_plural = "Categories"
        ordering            = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Represents a stockable item.

    unit_type determines how quantities are stored:
    - 'unit'   → whole numbers only (PositiveIntegerField in Stock)
    - 'weight' → fractional quantities allowed (DecimalField in Stock)

    SKU is the canonical external identifier for a product.
    Internal PK is used for all FK relationships.

    Deletion policy: products are never hard-deleted.
    Deactivating a product is the correct approach.
    PROTECT on_delete in Stock and StockMovement enforces this.
    """

    class UnitType(models.TextChoices):
        UNIT   = "unit",   "Unit (pieces)"
        WEIGHT = "weight", "Weight (kg/g)"

    sku        = models.CharField(max_length=50, unique=True)
    name       = models.CharField(max_length=150)
    category   = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    unit_type  = models.CharField(
        max_length=10,
        choices=UnitType.choices,
        default=UnitType.UNIT,
    )
    # Nullable: not every product has pricing loaded on day one. The
    # valuation report (BUSINESS_RULES §9) excludes rows with no
    # cost_price rather than silently treating them as zero-value stock.
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Unit acquisition cost. Used for inventory valuation. Admin-only visibility.",
    )
    sale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Unit sale price. Visible to all authenticated users.",
    )
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Product"
        verbose_name_plural = "Products"
        ordering            = ["name"]

    def __str__(self):
        return f"[{self.sku}] {self.name}"
