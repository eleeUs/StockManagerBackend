from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.permissions import IsAdmin
from core.views import LoginRateThrottle
from .models import User
from .serializers import (
    UserSerializer,
    CreateUserSerializer,
    UpdateUserSerializer,
    ChangePasswordSerializer,
)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/
    Returns access and refresh JWT tokens.
    Throttled to 5 attempts per minute per IP (LoginRateThrottle).
    """
    permission_classes = []
    throttle_classes   = [LoginRateThrottle]


class RefreshTokenView(TokenRefreshView):
    """
    POST /api/v1/auth/refresh/
    Exchanges a valid refresh token for a new access token.
    """
    permission_classes = []


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Blacklists the provided refresh token, effectively invalidating
    the session. The access token will expire on its own.
    Requires: { "refresh": "<token>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response(
                    {"error": "missing_token", "detail": "Refresh token is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception:
            return Response(
                {"error": "invalid_token", "detail": "Token is invalid or already blacklisted."},
                status=status.HTTP_400_BAD_REQUEST,
            )


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

class UserListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/users/  → List all users (admin only)
    POST /api/v1/users/  → Create a new user (admin only)
    """
    permission_classes = [IsAdmin]
    queryset = User.objects.select_related("branch").order_by("full_name")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreateUserSerializer
        return UserSerializer


class UserDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/users/{id}/  → Retrieve user detail
    PATCH /api/v1/users/{id}/  → Partial update (admin only)

    Sellers can retrieve their own profile.
    Only admins can retrieve any user or perform updates.
    """
    queryset = User.objects.select_related("branch")

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return UpdateUserSerializer
        return UserSerializer

    def get_object(self):
        # Sellers can only retrieve their own profile
        obj = super().get_object()
        if self.request.user.role == "seller" and obj.pk != self.request.user.pk:
            self.permission_denied(self.request)
        return obj


class MeView(generics.RetrieveAPIView):
    """
    GET /api/v1/auth/me/
    Returns the profile of the currently authenticated user.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/

    Allows any authenticated user to change their own password.
    Requires the current password for verification — this prevents
    a stolen session token from being used to lock out the real user.

    On success the response is 204 No Content. The client should
    discard existing tokens and prompt the user to log in again,
    because token rotation is not automatic on password change.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
