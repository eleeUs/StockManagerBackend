import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="cost_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Unit acquisition cost. Used for inventory valuation. Admin-only visibility.",
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="sale_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Unit sale price. Visible to all authenticated users.",
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
    ]
