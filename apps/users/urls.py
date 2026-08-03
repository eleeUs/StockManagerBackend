from django.urls import path
from .views import (
    LoginView,
    RefreshTokenView,
    LogoutView,
    MeView,
    ChangePasswordView,
    UserListCreateView,
    UserDetailView,
)

urlpatterns = [
    # Auth
    path("login/",           LoginView.as_view(),          name="auth-login"),
    path("refresh/",         RefreshTokenView.as_view(),   name="auth-refresh"),
    path("logout/",          LogoutView.as_view(),          name="auth-logout"),
    path("me/",              MeView.as_view(),              name="auth-me"),
    path("change-password/", ChangePasswordView.as_view(),  name="auth-change-password"),

    # User management (admin only)
    path("../users/",          UserListCreateView.as_view(), name="user-list-create"),
    path("../users/<int:pk>/", UserDetailView.as_view(),     name="user-detail"),
]
