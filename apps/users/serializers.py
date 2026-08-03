from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """
    Read serializer for user data.
    Password is write-only and never returned in responses.
    """
    class Meta:
        model  = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "branch",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CreateUserSerializer(serializers.ModelSerializer):
    """
    Write serializer for creating users.
    Only admins reach this endpoint (enforced at the view level).
    """
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model  = User
        fields = ["email", "full_name", "role", "branch", "password"]

    def validate(self, data):
        role   = data.get("role")
        branch = data.get("branch")

        # Mirror the DB-level constraint at the serializer level
        # so the error is caught before hitting the database.
        if role == User.Role.SELLER and branch is None:
            raise serializers.ValidationError(
                {"branch": "Branch is required for sellers."}
            )
        if role == User.Role.ADMIN and branch is not None:
            raise serializers.ValidationError(
                {"branch": "Admins must not be assigned to a branch."}
            )
        return data

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UpdateUserSerializer(serializers.ModelSerializer):
    """
    Write serializer for partial updates to an existing user.
    Password updates are handled separately via a dedicated endpoint.
    """
    class Meta:
        model  = User
        fields = ["full_name", "role", "branch", "is_active"]

    def validate(self, data):
        # Merge incoming data with existing instance data
        # to validate the final state, not just the changed fields.
        role   = data.get("role", self.instance.role)
        branch = data.get("branch", self.instance.branch)

        if role == User.Role.SELLER and branch is None:
            raise serializers.ValidationError(
                {"branch": "Branch is required for sellers."}
            )
        if role == User.Role.ADMIN and branch is not None:
            raise serializers.ValidationError(
                {"branch": "Admins must not be assigned to a branch."}
            )
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """
    Validates and applies a password change for the authenticated user.

    Validation rules:
    - current_password must match the stored hash (checked via check_password).
    - new_password must be at least 8 characters.
    - confirm_password must match new_password exactly.
    - new_password must differ from current_password.

    save() calls set_password() which applies the configured hasher (Argon2id)
    and saves only the password and updated_at fields.
    """
    current_password  = serializers.CharField(write_only=True, min_length=1)
    new_password      = serializers.CharField(write_only=True, min_length=8)
    confirm_password  = serializers.CharField(write_only=True, min_length=8)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        if data["new_password"] == data["current_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must differ from current password."}
            )
        return data

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user
