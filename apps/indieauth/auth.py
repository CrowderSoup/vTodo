"""
IndieAuth PKCE helpers: endpoint discovery, PKCE pair generation,
authorization URL construction, and token exchange.
Ported from PADD (microsub_client/auth.py) with scope changed to 'profile publish'.
"""
import hashlib
import re
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, urljoin

import requests
from requests.exceptions import RequestException

from django.core.cache import cache

from .outbound import (
    UnsafeOutboundURLError,
    normalize_url,
    parse_json_response,
    safe_request,
    validate_outbound_url,
)

ENDPOINTS_CACHE_TTL = 300  # 5 minutes


def _endpoints_cache_key(url: str) -> str:
    import hashlib
    return f"ia_endpoints:{hashlib.md5(url.encode()).hexdigest()}"


def _discover_endpoints_uncached(url: str) -> dict:
    """
    Fetch a user's URL and discover IndieAuth and Micropub endpoints.
    HTTP Link headers are checked first, then HTML <link> tags (which override).
    See: https://indieauth.spec.indieweb.org/#discovery
    """
    url = normalize_url(url, trailing_slash=True)

    endpoints = {
        "authorization_endpoint": None,
        "token_endpoint": None,
        "micropub": None,
    }

    try:
        resp = safe_request(
            url,
            send=requests.get,
            timeout=10,
            headers={"Accept": "text/html"},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except UnsafeOutboundURLError as exc:
        raise ValueError(str(exc)) from exc
    except RequestException as exc:
        raise ValueError(f"Could not fetch {url}: {exc}") from exc

    def _safe_endpoint(href: str) -> str | None:
        candidate = urljoin(url, href)
        try:
            return validate_outbound_url(candidate)
        except UnsafeOutboundURLError:
            return None

    # 1. Parse HTTP Link headers
    link_header = resp.headers.get("Link", "")
    for part in link_header.split(","):
        for rel in endpoints:
            pattern = rf'<([^>]+)>;\s*rel="{re.escape(rel)}"'
            match = re.search(pattern, part)
            if match:
                endpoints[rel] = _safe_endpoint(match.group(1))

    # 2. Parse HTML <link> tags (override headers per common practice)
    html = resp.text
    for rel in endpoints:
        # Try rel="..." href="..." attribute order
        pattern = rf'<link[^>]+rel="{re.escape(rel)}"[^>]+href="([^"]+)"'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            endpoints[rel] = _safe_endpoint(match.group(1))
            continue
        # Try href="..." rel="..." attribute order
        pattern = rf'<link[^>]+href="([^"]+)"[^>]+rel="{re.escape(rel)}"'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            endpoints[rel] = _safe_endpoint(match.group(1))

    return endpoints


def discover_endpoints(url: str) -> dict:
    """Discover IndieAuth endpoints for a URL. Cached for 5 minutes."""
    key = _endpoints_cache_key(url)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = _discover_endpoints_uncached(url)
    cache.set(key, result, ENDPOINTS_CACHE_TTL)
    return result


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate a PKCE code_verifier and S256 code_challenge.
    Returns (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorization_url(
    auth_endpoint: str,
    me: str,
    redirect_uri: str,
    state: str,
    client_id: str,
    code_challenge: str,
) -> str:
    """Build the IndieAuth authorization URL with PKCE."""
    params = {
        "me": me,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "profile publish",
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return auth_endpoint + "?" + urlencode(params)


def exchange_code_for_token(
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    client_id: str,
    code_verifier: str,
) -> dict:
    """
    Exchange an authorization code for an access token.
    Returns dict with at least 'access_token' and 'me' on success.
    Raises ValueError on failure.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    try:
        resp = safe_request(
            token_endpoint,
            send=requests.post,
            data=data,
            headers={"Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
        resp.raise_for_status()
    except UnsafeOutboundURLError as exc:
        raise ValueError(f"Token exchange failed: {exc}") from exc
    except RequestException as exc:
        raise ValueError(f"Token exchange failed: {exc}") from exc

    result = parse_json_response(resp, ValueError, "Token exchange failed")
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise ValueError(f"Token exchange failed: {error}")

    return result
