from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from core.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Health check — no auth, used by Docker and load balancers
    path("health/", HealthCheckView.as_view(), name="health-check"),

    # API v1
    path("api/v1/", include([
        # Auth
        path("auth/", include("apps.users.urls")),

        # Resources
        path("branches/", include("apps.branches.urls")),
        path("products/", include("apps.products.urls")),

        # Stock & Movements
        path("", include("apps.movements.urls")),

        # Reports (read-only aggregations; models-less app)
        path("reports/", include("apps.reports.urls")),

        # OpenAPI schema + Swagger UI
        path("schema/", SpectacularAPIView.as_view(),                             name="schema"),
        path("docs/",   SpectacularSwaggerView.as_view(url_name="schema"),        name="swagger-ui"),
    ])),
]
