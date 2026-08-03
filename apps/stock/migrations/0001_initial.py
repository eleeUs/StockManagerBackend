import decimal
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("branches", "0001_initial"),
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Stock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.DecimalField(
                    decimal_places=3,
                    default=decimal.Decimal("0.000"),
                    max_digits=12,
                    validators=[django.core.validators.MinValueValidator(decimal.Decimal("0"))],
                )),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="stock_levels",
                    to="branches.branch",
                )),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="stock_levels",
                    to="products.product",
                )),
            ],
            options={
                "verbose_name": "Stock",
                "verbose_name_plural": "Stock",
            },
        ),
        migrations.AlterUniqueTogether(
            name="stock",
            unique_together={("product", "branch")},
        ),
        migrations.AddIndex(
            model_name="stock",
            index=models.Index(fields=["branch", "product"], name="idx_stock_branch_product"),
        ),
        migrations.AddIndex(
            model_name="stock",
            index=models.Index(fields=["product", "branch"], name="idx_stock_product_branch"),
        ),
        migrations.AddConstraint(
            model_name="stock",
            constraint=models.CheckConstraint(
                check=models.Q(quantity__gte=decimal.Decimal("0")),
                name="stock_quantity_non_negative",
            ),
        ),
    ]
