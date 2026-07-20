from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

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
    path("integrations/", include("apps.integrations.urls", namespace="integrations")),
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
