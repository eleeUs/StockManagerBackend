from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),

    # API v1
    path("api/v1/", include([
        # Auth
        path("auth/", include("apps.users.urls")),

        # Resources
        path("branches/", include("apps.branches.urls")),
        path("products/", include("apps.products.urls")),

        # Stock & Movements
        path("", include("apps.movements.urls")),

        # OpenAPI schema + Swagger UI (disable in production if needed)
        path("schema/", SpectacularAPIView.as_view(), name="schema"),
        path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ])),
]
