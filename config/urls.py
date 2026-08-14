from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from oauth2_provider.urls import metadata_urlpatterns as oauth2_metadata_urlpatterns

urlpatterns = [
    path("up/", lambda request: HttpResponse("OK")),
    path("", RedirectView.as_view(url="/login/", permanent=False)),
    # Combined login page — Email OTP + Google OAuth tabs
    path("login/", include("apps.accounts.urls", namespace="accounts")),
    path("accounts/", include("allauth.urls")),
    path("auth/email/", include("apps.emailauth.urls", namespace="emailauth")),
    path("board/", include("apps.boards.urls", namespace="boards")),
    path("settings/", include("apps.users.urls", namespace="users")),
    path("teams/", include("apps.teams.urls", namespace="teams")),
    # OAuth 2.1 authorization server, for remote MCP clients (Claude) — see
    # config/settings.py:OAUTH2_PROVIDER. RFC 8414 well-known metadata is
    # mounted twice per django-oauth-toolkit's own guidance: once at the
    # domain root (strict form) and once under o/ (fallback form clients
    # also probe for), both pointing at the same o/ issuer.
    path(
        "",
        include((oauth2_metadata_urlpatterns, "oauth2_provider"), namespace="oauth2_metadata"),
    ),
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
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
