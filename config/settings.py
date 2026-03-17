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
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # Local apps — users first because AUTH_USER_MODEL depends on it
    "apps.users.apps.UsersConfig",
    "apps.indieauth.apps.IndieAuthConfig",
    "apps.emailauth.apps.EmailAuthConfig",
    "apps.boards.apps.BoardsConfig",
    "apps.tasks.apps.TasksConfig",
    "apps.integrations.apps.IntegrationsConfig",
    "apps.micropub.apps.MicropubConfig",
    # Django contrib
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "django_htmx",
    "whitenoise.runserver_nostatic",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "apps.api.apps.ApiConfig",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "vtodo API",
    "DESCRIPTION": "REST API for the vtodo personal task manager.",
    "VERSION": "1.0.0",
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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

# Cache (Redis for OTP rate limiting and endpoint caching)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CELERY_BROKER_URL", default="redis://localhost:6379/0"),
    }
}

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_BEAT_SCHEDULE = {
    "send-daily-summaries": {
        "task": "apps.micropub.tasks.send_daily_summaries",
        "schedule": 3600.0,  # runs hourly; task filters by user's chosen hour
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
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="vtodo <noreply@example.com>")

# IndieAuth client identity URL
INDIEAUTH_CLIENT_ID = env("INDIEAUTH_CLIENT_ID", default="http://localhost:8000/")

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
