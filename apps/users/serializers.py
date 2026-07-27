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
