"""Optional Pocket ID OpenID Connect provider.

All three env vars are required. If any is missing, the provider is left
unregistered and the login page has no Pocket ID button.

The flow is authorization code with PKCE, via allauth's generic OpenID
Connect provider. ``server_url`` is the issuer (for example
https://id.crowdersoup.com); allauth loads
``{server_url}/.well-known/openid-configuration`` from it.
"""

import re
from urllib.parse import urlencode

_PROVIDER_GROUP = re.compile(r"\(\?P<(\w+)>[^)]+\)")

POCKET_ID_PROVIDER_ID = "pocket-id"

_cached_paths: tuple[str, str] | None = None


def pocket_id_provider_settings(url: str, client_id: str, client_secret: str) -> dict | None:
    issuer = (url or "").strip().rstrip("/")
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not issuer or not client_id or not client_secret:
        return None
    return {
        # allauth's OAuth2 provider reads OAUTH_PKCE_ENABLED. The OpenID
        # Connect app settings also accept oauth_pkce_enabled. Set both so
        # the authorization-code login sends a PKCE challenge.
        "OAUTH_PKCE_ENABLED": True,
        "SCOPE": ["openid", "profile", "email"],
        "APPS": [
            {
                "provider_id": POCKET_ID_PROVIDER_ID,
                "name": "Pocket ID",
                "client_id": client_id,
                "secret": client_secret,
                "settings": {
                    "server_url": issuer,
                    "oauth_pkce_enabled": True,
                },
            }
        ],
    }


def pocket_id_login_url(next_url: str = "", process: str = "") -> str:
    from django.conf import settings

    if not getattr(settings, "POCKET_ID_ENABLED", False):
        return ""
    login, _callback = pocket_id_paths()
    params = {}
    if process:
        params["process"] = process
    if next_url:
        params["next"] = next_url
    if not params:
        return login
    return f"{login}?{urlencode(params)}"


def pocket_id_callback_path() -> str:
    return pocket_id_paths()[1]


def pocket_id_login_path() -> str:
    return pocket_id_paths()[0]


def pocket_id_paths() -> tuple[str, str]:
    global _cached_paths
    if _cached_paths is None:
        _cached_paths = _discover_oidc_paths()
    return _cached_paths


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


def _discover_oidc_paths() -> tuple[str, str]:
    paths = discover_provider_paths(
        "allauth.socialaccount.providers.openid_connect",
        {
            "<str:provider_id>": POCKET_ID_PROVIDER_ID,
            "{provider_id}": POCKET_ID_PROVIDER_ID,
        },
    )
    login = paths.get("openid_connect_login")
    callback = paths.get("openid_connect_callback")
    if not login or not callback:
        raise RuntimeError(f"Unexpected OpenID Connect routes: {paths}")
    return login, callback
