from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path("", RedirectView.as_view(url="/login/", permanent=False)),
    # Combined login page lives at the indieauth namespace root
    path("login/", include("apps.indieauth.urls", namespace="indieauth")),
    path("auth/email/", include("apps.emailauth.urls", namespace="emailauth")),
    path("board/", include("apps.boards.urls", namespace="boards")),
    path("settings/", include("apps.users.urls", namespace="users")),
    # REST API
    path("api/v1/", include("apps.api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    try:
        from debug_toolbar.toolbar import debug_toolbar_urls

        urlpatterns += debug_toolbar_urls()
    except ImportError:
        pass
