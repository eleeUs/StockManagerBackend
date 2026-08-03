import decimal
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stock",
            name="reorder_point",
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(decimal.Decimal("0"))],
            ),
        ),
    ]
