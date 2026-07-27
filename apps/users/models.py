from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model using email as the login identifier.

    CRITICAL: This model must be defined and AUTH_USER_MODEL must be set
    in settings BEFORE running the first `migrate`. Changing the user
    model after initial migrations requires a full database reset.

    Role rules (BUSINESS_RULES §1):
    - admin: no branch required, operates across all branches.
    - seller: branch is mandatory, operates only on their assigned branch,
              but can read stock from any branch.
    """

    class Role(models.TextChoices):
        ADMIN  = "admin",  "Admin"
        SELLER = "seller", "Seller"

    email     = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role      = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.SELLER,
    )

    # Sellers are always assigned to one branch.
    # Admins have null branch — they operate on all branches.
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sellers",
        help_text="Required for sellers. Leave blank for admins.",
    )

    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name        = "User"
        verbose_name_plural = "Users"
        ordering            = ["full_name"]
        constraints = [
            # A seller must have a branch assigned.
            # An admin must not have a branch assigned.
            # Enforced at the DB level — also validated in the serializer.
            models.CheckConstraint(
                check=(
                    models.Q(role="admin", branch__isnull=True) |
                    models.Q(role="seller", branch__isnull=False)
                ),
                name="user_branch_matches_role",
            )
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}> [{self.role}]"

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_seller(self):
        return self.role == self.Role.SELLER
