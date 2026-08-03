import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # User has a nullable FK to Branch — Branch must exist first
        ("branches", "0001_initial"),
        # PermissionsMixin uses auth.Group and auth.Permission
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                # AbstractBaseUser fields
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                # PermissionsMixin field
                ("is_superuser", models.BooleanField(
                    default=False,
                    help_text="Designates that this user has all permissions without explicitly assigning them.",
                    verbose_name="superuser status",
                )),
                # Custom fields
                ("email", models.EmailField(max_length=254, unique=True)),
                ("full_name", models.CharField(max_length=150)),
                ("role", models.CharField(
                    choices=[("admin", "Admin"), ("seller", "Seller")],
                    default="seller",
                    max_length=10,
                )),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                # FK to Branch — nullable for admins
                ("branch", models.ForeignKey(
                    blank=True,
                    help_text="Required for sellers. Leave blank for admins.",
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="sellers",
                    to="branches.branch",
                )),
                # PermissionsMixin M2M fields
                ("groups", models.ManyToManyField(
                    blank=True,
                    help_text="The groups this user belongs to.",
                    related_name="user_set",
                    related_query_name="user",
                    to="auth.group",
                    verbose_name="groups",
                )),
                ("user_permissions", models.ManyToManyField(
                    blank=True,
                    help_text="Specific permissions for this user.",
                    related_name="user_set",
                    related_query_name="user",
                    to="auth.permission",
                    verbose_name="user permissions",
                )),
            ],
            options={
                "verbose_name": "User",
                "verbose_name_plural": "Users",
                "ordering": ["full_name"],
            },
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(role="admin", branch__isnull=True) |
                    models.Q(role="seller", branch__isnull=False)
                ),
                name="user_branch_matches_role",
            ),
        ),
    ]
