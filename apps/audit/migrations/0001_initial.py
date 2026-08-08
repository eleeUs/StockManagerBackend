import django.db.models.deletion
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model_name", models.CharField(max_length=50)),
                ("object_id", models.PositiveIntegerField()),
                ("action", models.CharField(choices=[("create", "Create"), ("update", "Update"), ("deactivate", "Deactivate")], max_length=20)),
                ("changes", models.JSONField(encoder=DjangoJSONEncoder)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="audit_log_entries",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["model_name", "object_id", "created_at"], name="audit_model_object_created_idx"),
        ),
    ]
