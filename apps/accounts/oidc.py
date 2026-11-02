"""Optional OpenID Connect sign-in, for any provider with discovery.

OIDC_URL, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET are all required. If any
is missing, the provider is left unregistered and the login page has no
button for it. OIDC_NAME is the label people see ("Sign in with
<name>"). OIDC_PROVIDER_ID is allauth's id for the provider: it is part of
the callback URL and is stored on every linked account, so changing it on
a live deploy orphans existing links.

The flow is authorization code with PKCE, via allauth's generic OpenID
Connect provider. ``server_url`` is the issuer (for example
https://id.example.com); allauth loads
``{server_url}/.well-known/openid-configuration`` from it.
"""

import re
from urllib.parse import urlencode

from django.core.exceptions import ImproperlyConfigured

_PROVIDER_GROUP = re.compile(r"\(\?P<(\w+)>[^)]+\)")
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")

DEFAULT_PROVIDER_ID = "oidc"
DEFAULT_NAME = "SSO"

_cached_paths: dict[str, tuple[str, str]] = {}


def oidc_provider_settings(
    url: str,
    client_id: str,
    client_secret: str,
    provider_id: str = DEFAULT_PROVIDER_ID,
    name: str = DEFAULT_NAME,
) -> dict | None:
    issuer = (url or "").strip().rstrip("/")
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not issuer or not client_id or not client_secret:
        return None
    provider_id = clean_provider_id(provider_id)
    return {
        # allauth's OAuth2 provider reads OAUTH_PKCE_ENABLED. The OpenID
        # Connect app settings also accept oauth_pkce_enabled. Set both so
        # the authorization-code login sends a PKCE challenge.
        "OAUTH_PKCE_ENABLED": True,
        "SCOPE": ["openid", "profile", "email"],
        "APPS": [
            {
                "provider_id": provider_id,
                "name": clean_name(name),
                "client_id": client_id,
                "secret": client_secret,
                "settings": {
                    "server_url": issuer,
                    "oauth_pkce_enabled": True,
                },
            }
        ],
    }


def clean_provider_id(provider_id: str) -> str:
    """Lower-case slug, because it goes in a URL and in the database."""
    value = (provider_id or "").strip() or DEFAULT_PROVIDER_ID
    if not _PROVIDER_ID.fullmatch(value):
        raise ImproperlyConfigured(
            f"OIDC_PROVIDER_ID must be lower-case letters, digits, '-' or '_', got {provider_id!r}."
        )
    return value


def clean_name(name: str) -> str:
    return (name or "").strip() or DEFAULT_NAME


def oidc_provider_id() -> str:
    from django.conf import settings

    return getattr(settings, "OIDC_PROVIDER_ID", DEFAULT_PROVIDER_ID)


def oidc_name() -> str:
    from django.conf import settings

    return getattr(settings, "OIDC_NAME", DEFAULT_NAME)


def oidc_login_url(next_url: str = "", process: str = "") -> str:
    from django.conf import settings

    if not getattr(settings, "OIDC_ENABLED", False):
        return ""
    login, _callback = oidc_paths()
    params = {}
    if process:
        params["process"] = process
    if next_url:
        params["next"] = next_url
    if not params:
        return login
    return f"{login}?{urlencode(params)}"


def oidc_callback_path() -> str:
    return oidc_paths()[1]


def oidc_login_path() -> str:
    return oidc_paths()[0]


def oidc_paths() -> tuple[str, str]:
    provider_id = oidc_provider_id()
    if provider_id not in _cached_paths:
        _cached_paths[provider_id] = _discover_oidc_paths(provider_id)
    return _cached_paths[provider_id]


def _route(pattern) -> str:
    """Django path() routes, or re_path() groups turned into ``{name}``."""
    route_pattern = getattr(pattern, "pattern", None)
    if route_pattern is None:
        return ""
    route = getattr(route_pattern, "_route", None)
    if route is not None:
        return route
    regex = getattr(route_pattern, "regex", None)
    if regex is None:
        return str(route_pattern)
    text = regex.pattern.lstrip("^")
    if text.endswith("\\Z"):
        text = text[: -len("\\Z")]
    text = text.rstrip("$")
    return _PROVIDER_GROUP.sub(r"{\1}", text)


def _walk_patterns(urlpatterns, prefix: str = "") -> dict:
    found = {}
    for pattern in urlpatterns:
        route = _route(pattern)
        nested = getattr(pattern, "url_patterns", None)
        if nested is not None:
            found.update(_walk_patterns(nested, prefix + route))
            continue
        name = getattr(pattern, "name", "") or ""
        found[name] = prefix + route
    return found


def discover_provider_paths(package: str, replacements: dict | None = None) -> dict:
    """Map allauth provider URL names to site paths under ``/accounts/``.

    allauth's own urlconf already includes the provider slug (``google/``,
    ``oidc/``), and the project mounts that urlconf at ``/accounts/``.
    """
    import importlib

    urls = importlib.import_module(package + ".urls")
    replacements = replacements or {}
    found = {}
    for name, route in _walk_patterns(urls.urlpatterns).items():
        for key, value in replacements.items():
            route = route.replace(key, value)
        path = "/accounts/" + route.lstrip("/")
        if not path.endswith("/"):
            path += "/"
        found[name] = path
    return found


def _discover_oidc_paths(provider_id: str) -> tuple[str, str]:
    paths = discover_provider_paths(
        "allauth.socialaccount.providers.openid_connect",
        {
            "<str:provider_id>": provider_id,
            "{provider_id}": provider_id,
        },
    )
    login = paths.get("openid_connect_login")
    callback = paths.get("openid_connect_callback")
    if not login or not callback:
        raise RuntimeError(f"Unexpected OpenID Connect routes: {paths}")
    return login, callback
