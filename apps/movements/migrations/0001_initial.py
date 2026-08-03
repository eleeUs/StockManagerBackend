import decimal
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("branches", "0001_initial"),
        ("products", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("movement_type", models.CharField(
                    choices=[
                        ("ingreso",       "Entry"),
                        ("venta",         "Sale"),
                        ("transferencia", "Transfer"),
                        ("ajuste",        "Adjustment"),
                        ("devolucion",    "Return"),
                        ("donacion",      "Donation"),
                        ("reversal",      "Reversal"),
                    ],
                    max_length=15,
                )),
                ("status", models.CharField(
                    choices=[
                        ("confirmed", "Confirmed"),
                        ("pending",   "Pending"),
                        ("cancelled", "Cancelled"),
                    ],
                    default="confirmed",
                    max_length=10,
                )),
                ("quantity", models.DecimalField(
                    decimal_places=3,
                    max_digits=12,
                    validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.001"))],
                )),
                ("adjustment_previous_quantity", models.DecimalField(
                    blank=True,
                    decimal_places=3,
                    max_digits=12,
                    null=True,
                )),
                ("entry_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                # FK fields
                ("created_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="movements",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("destination_branch", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="incoming_movements",
                    to="branches.branch",
                )),
                ("source_branch", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="outgoing_movements",
                    to="branches.branch",
                )),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="movements",
                    to="products.product",
                )),
                # Self-referential OneToOneField for reversals
                ("reverses_movement", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="reversed_by",
                    to="movements.stockmovement",
                )),
            ],
            options={
                "verbose_name": "Stock Movement",
                "verbose_name_plural": "Stock Movements",
                "ordering": ["-created_at"],
            },
        ),
        # Indexes for common filter combinations
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["product", "-created_at"], name="idx_movement_product_date"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["source_branch", "-created_at"], name="idx_movement_source_date"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["destination_branch", "-created_at"], name="idx_movement_dest_date"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["movement_type", "-created_at"], name="idx_movement_type_date"),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["status", "movement_type"], name="idx_movement_status_type"),
        ),
        # DB-level business rule constraints
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                check=models.Q(quantity__gt=decimal.Decimal("0")),
                name="movement_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(status="confirmed") |
                    models.Q(movement_type="transferencia")
                ),
                name="movement_pending_cancelled_only_for_transfers",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                check=~models.Q(
                    source_branch=models.F("destination_branch"),
                    source_branch__isnull=False,
                    destination_branch__isnull=False,
                ),
                name="movement_source_dest_different",
            ),
        ),
    ]
