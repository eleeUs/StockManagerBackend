from django.urls import path

from .views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshTokenView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    # Auth — mounted under api/v1/auth/ in config/urls.py
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshTokenView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
]

# User management (admin only) — mounted under api/v1/users/ directly in
# config/urls.py, as a sibling of auth/, NOT nested under it.
management_urlpatterns = [
    path("", UserListCreateView.as_view(), name="user-list-create"),
    path("<int:pk>/", UserDetailView.as_view(), name="user-detail"),
]
