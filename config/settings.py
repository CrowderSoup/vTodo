from pathlib import Path

import environ

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)

BASE_DIR = Path(__file__).resolve().parent.parent

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-change-me-in-production")
# Fernet key for encrypting third-party integration credentials at rest.
# No default: a missing key must fail startup loudly rather than
# silently encrypting real user credentials with a key checked into source control.
# Generate one with:
# `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
INTEGRATIONS_ENCRYPTION_KEY = env("INTEGRATIONS_ENCRYPTION_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Emails granted admin access (see apps.users.selectors.is_admin) -- matched against
# verified EmailIdentity emails, which are always stored lower-cased.
ADMIN_EMAILS = [e.strip().lower() for e in env.list("ADMIN_EMAILS", default=[])]

# Trust the X-Forwarded-Proto header from reverse proxies (e.g. DO App Platform)
# so that request.build_absolute_uri() generates https:// URLs correctly.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    # The app sits behind a TLS-terminating proxy (see SECURE_PROXY_SSL_HEADER
    # above), so it's safe to mark cookies secure-only and enable HSTS here.
    #
    # Kamal-proxy already terminates TLS and redirects http->https at the edge
    # (see proxy.ssl in config/deploy.yml), so SECURE_SSL_REDIRECT defaults off
    # to avoid a redundant/incorrect redirect if SECURE_PROXY_SSL_HEADER isn't
    # seen (e.g. CI, or Kamal's healthcheck reaching the app directly). Flip it
    # on via env if the proxy setup ever changes.
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    # CSRF_COOKIE_HTTPONLY stays off: static/app.js reads the csrftoken cookie
    # to send X-CSRFToken on htmx requests.
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    # Preload only means anything on a registrable domain; crowdersoup.com
    # (webstead) already sends it, and that covers this subdomain.
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

INSTALLED_APPS = [
    # Local apps — users first because AUTH_USER_MODEL depends on it
    "apps.users.apps.UsersConfig",
    "apps.workspaces.apps.WorkspacesConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.emailauth.apps.EmailAuthConfig",
    "apps.teams.apps.TeamsConfig",
    "apps.boards.apps.BoardsConfig",
    "apps.tasks.apps.TasksConfig",
    "apps.integrations.apps.IntegrationsConfig",
    "apps.siteadmin.apps.SiteAdminConfig",
    # Django contrib
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "django_htmx",
    "whitenoise.runserver_nostatic",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "apps.api.apps.ApiConfig",
    "oauth2_provider",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]

SITE_ID = 1

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Settings → API token, plus the per-device tokens the Android app
        # gets from Google sign-in (apps.api.models.DeviceToken).
        "apps.api.authentication.ApiTokenAuthentication",
        # Remote MCP clients' OAuth tokens, forwarded by mcp_server. Listed
        # before SessionAuthentication so a 401 still advertises a scheme.
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.api.permissions.OAuthTokenHasTasksScope",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Only the anonymous Google sign-in exchange is throttled (see
    # apps.api.views.GoogleSignInView). kamal-proxy is the one proxy in front
    # of the app, so the client is the last X-Forwarded-For hop; without this
    # DRF keys on the whole header, which the client controls.
    "NUM_PROXIES": env.int("DRF_NUM_PROXIES", default=1),
    "DEFAULT_THROTTLE_RATES": {
        "google_sign_in": env("GOOGLE_SIGN_IN_RATE", default="20/hour"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "vtodo API",
    "DESCRIPTION": "REST API for the vtodo personal task manager.",
    "VERSION": "1.0.0",
}

# OAuth 2.1 authorization server (django-oauth-toolkit) — lets remote MCP
# clients (Claude Desktop/Code) authorize against a vtodo account instead of
# using a shared static token. See mcp_server/server.py and
# apps/api/views.py:WhoAmIView for the resource-server side of this.
OAUTH2_PROVIDER = {
    "PKCE_REQUIRED": True,
    "SCOPES": {
        "tasks": "Read and write your vtodo tasks, statuses, and comments",
    },
    "DEFAULT_SCOPES": ["tasks"],
    "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
    "REFRESH_TOKEN_EXPIRE_SECONDS": 60 * 60 * 24 * 30,
    "ROTATE_REFRESH_TOKEN": True,
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    # MCP clients (e.g. Claude) self-register via RFC 7591 before any user is
    # logged in, so registration can't require an authenticated session —
    # this is the toolkit's "open registration" permission class.
    "DCR_ENABLED": True,
    "DCR_REGISTRATION_PERMISSION_CLASSES": ("oauth2_provider.dcr.AllowAllDCRPermission",),
    # MCP only ever uses authorization_code + PKCE (S256) — lock out the
    # other grant types and weaker PKCE method rather than leave them
    # reachable with no caller needing them.
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
    # RFC 8707: tokens minted for mcp_server's resource (VTODO_MCP_PUBLIC_URL)
    # are forwarded by it to this API, which lives on a different host. Accept
    # that one audience on /api/v1/ only -- see
    # apps/api/views.py:validate_api_resource_token.
    "RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR": "apps.api.views.validate_api_resource_token",
}

# mcp_server's public resource identifier, the audience of the OAuth tokens
# it forwards to the API. Same value as the mcp role's VTODO_MCP_PUBLIC_URL.
VTODO_MCP_RESOURCE_URL = env("VTODO_MCP_PUBLIC_URL", default="")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.users.middleware.TimezoneMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.siteadmin.context_processors.admin_status",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

AUTH_USER_MODEL = "users.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/board/"
LOGOUT_REDIRECT_URL = "/login/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

def cache_config(broker_url):
    """Redis when a broker is configured. In-memory when it is not.

    The web process uses the cache for invite rate limiting only. Leaving
    CELERY_BROKER_URL unset lets the board run without Redis. Production sets
    the variable, and the Celery worker still needs Redis for Google Calendar
    sync.
    """
    if broker_url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": broker_url,
            }
        }
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "vtodo-local",
        }
    }


# Empty means "no Redis for the web process". The worker default below is only
# used when someone starts Celery without configuring a broker.
_celery_broker_url = env("CELERY_BROKER_URL", default="")
CACHES = cache_config(_celery_broker_url)

# Celery
CELERY_BROKER_URL = _celery_broker_url or "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_BEAT_SCHEDULE = {
    "sync-google-calendar-connections": {
        "task": "apps.integrations.tasks.sync_all_google_calendar_connections",
        "schedule": 600.0,  # 10 minutes
    },
}

# Email
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
# Use EMAIL_USE_SSL=True for port 465 (implicit SSL), EMAIL_USE_TLS=True for port 587 (STARTTLS).
# These are mutually exclusive — do not set both to True.
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="vtodo <noreply@example.com>")

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
        },
    },
}

# Google OAuth (django-allauth) — settings-based provider app, no DB SocialApp/admin needed.
# Exposed as plain settings too, since apps.integrations.google_calendar reuses the same
# registered OAuth client for its own (separate, incremental-consent) calendar connect flow.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": GOOGLE_CLIENT_ID,
            "secret": GOOGLE_CLIENT_SECRET,
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    },
}
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"
# The User model has no `email` field (email lives on apps.emailauth.EmailIdentity) —
# tell allauth's account app not to assume/sync one.
ACCOUNT_USER_MODEL_EMAIL_FIELD = None
# `username` is an opaque generated slug (see apps.users.models.UserManager), not something
# to show people — prefer the human-entered display name in allauth's messages/templates.
ACCOUNT_USER_DISPLAY = lambda user: user.display_name or user.username  # noqa: E731

# Content Security Policy (Django 6.0 built-in)
# See: https://docs.djangoproject.com/en/6.0/ref/middleware/#content-security-policy
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://unpkg.com", "'unsafe-inline'"],
        "style-src": ["'self'", "https://unpkg.com", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "https:"],
        "connect-src": ["'self'"],
        "font-src": ["'self'", "https://unpkg.com"],
    }
}

if DEBUG:
    try:
        import debug_toolbar  # noqa: F401

        INSTALLED_APPS += ["debug_toolbar"]
        MIDDLEWARE.insert(1, "debug_toolbar.middleware.DebugToolbarMiddleware")
        INTERNAL_IPS = ["127.0.0.1"]
    except ImportError:
        pass
