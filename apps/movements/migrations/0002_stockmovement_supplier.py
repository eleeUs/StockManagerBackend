import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("suppliers", "0001_initial"),
        ("movements", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="supplier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movements",
                to="suppliers.supplier",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                check=models.Q(("supplier__isnull", True)) | models.Q(("movement_type", "ingreso")),
                name="movement_supplier_only_for_ingreso",
            ),
        ),
    ]
