from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.users.urls import management_urlpatterns as user_management_urlpatterns
from core.views import LivenessView, ReadinessView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Health checks — no auth, used by Docker and load balancers.
    # /health/ is kept as a permanent alias of /health/ready/ for
    # backward compatibility with whatever already points at it
    # (Docker Compose healthcheck, an uptime monitor, a prod LB) —
    # aliasing costs nothing and avoids having to coordinate a cutover
    # across infra we don't fully control the timing of. See
    # docs/phase-9-bugfix-plan.md for why liveness and readiness are
    # split instead of the single combined check this used to be.
    path("health/", ReadinessView.as_view(), name="health-check"),
    path("health/live/", LivenessView.as_view(), name="health-live"),
    path("health/ready/", ReadinessView.as_view(), name="health-ready"),
    # API v1
    path(
        "api/v1/",
        include(
            [
                # Auth
                path("auth/", include("apps.users.urls")),
                # User management (admin only) — sibling of auth/, not nested
                path("users/", include(user_management_urlpatterns)),
                # Resources
                path("branches/", include("apps.branches.urls")),
                path("products/", include("apps.products.urls")),
                path("suppliers/", include("apps.suppliers.urls")),
                # Stock & Movements
                path("", include("apps.movements.urls")),
                # Reports (read-only aggregations; models-less app)
                path("reports/", include("apps.reports.urls")),
                # Audit trail (Phase 8)
                path("audit-log/", include("apps.audit.urls")),
                # OpenAPI schema + Swagger UI
                path("schema/", SpectacularAPIView.as_view(), name="schema"),
                path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
            ]
        ),
    ),
]
