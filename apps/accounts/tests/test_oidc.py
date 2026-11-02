from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.accounts.oidc import (
    discover_provider_paths,
    oidc_callback_path,
    oidc_provider_settings,
)


def test_oidc_provider_absent_unless_all_env_vars_are_set():
    assert oidc_provider_settings("", "", "") is None
    assert oidc_provider_settings("https://id.example.com", "client", "") is None
    assert oidc_provider_settings("https://id.example.com", "", "secret") is None
    assert oidc_provider_settings("", "client", "secret") is None
    assert oidc_provider_settings("  ", "client", "secret") is None


def test_oidc_provider_uses_authorization_code_with_pkce():
    provider = oidc_provider_settings("https://id.example.com/", "client-id", "client-secret")
    assert provider["OAUTH_PKCE_ENABLED"] is True
    assert provider["SCOPE"] == ["openid", "profile", "email"]
    app = provider["APPS"][0]
    assert app["provider_id"] == "oidc"
    assert app["name"] == "SSO"
    assert app["client_id"] == "client-id"
    assert app["secret"] == "client-secret"
    assert app["settings"]["server_url"] == "https://id.example.com"
    assert app["settings"]["oauth_pkce_enabled"] is True


def test_oidc_provider_takes_a_configured_id_and_name():
    provider = oidc_provider_settings("https://id.example.com", "client", "secret", "pocket-id", " Pocket ID ")
    app = provider["APPS"][0]
    assert app["provider_id"] == "pocket-id"
    assert app["name"] == "Pocket ID"


def test_blank_id_and_name_fall_back_to_defaults():
    app = oidc_provider_settings("https://id.example.com", "client", "secret", "  ", "")["APPS"][0]
    assert app["provider_id"] == "oidc"
    assert app["name"] == "SSO"


@pytest.mark.parametrize("provider_id", ["Pocket-ID", "pocket id", "pocket/id", "-oidc"])
def test_provider_id_must_be_a_lower_case_slug(provider_id):
    with pytest.raises(ImproperlyConfigured):
        oidc_provider_settings("https://id.example.com", "client", "secret", provider_id)


def test_settings_register_oidc_only_when_configured():
    configured = bool(
        settings.OIDC_URL.strip() and settings.OIDC_CLIENT_ID.strip() and settings.OIDC_CLIENT_SECRET.strip()
    )
    assert settings.OIDC_ENABLED is configured
    installed = "allauth.socialaccount.providers.openid_connect" in settings.INSTALLED_APPS
    assert installed is configured
    assert ("openid_connect" in settings.SOCIALACCOUNT_PROVIDERS) is configured
    if configured:
        provider = settings.SOCIALACCOUNT_PROVIDERS["openid_connect"]
        assert provider["OAUTH_PKCE_ENABLED"] is True
        app = provider["APPS"][0]
        assert app["provider_id"] == settings.OIDC_PROVIDER_ID
        assert app["settings"]["oauth_pkce_enabled"] is True


def test_google_callback_path_matches_the_documented_accounts_prefix():
    paths = discover_provider_paths("allauth.socialaccount.providers.google")
    assert paths.get("google_callback") == "/accounts/google/login/callback/", paths


def test_callback_path_follows_the_provider_id(settings):
    settings.OIDC_PROVIDER_ID = "pocket-id"
    assert oidc_callback_path() == "/accounts/oidc/pocket-id/login/callback/"
    settings.OIDC_PROVIDER_ID = "oidc"
    assert oidc_callback_path() == "/accounts/oidc/oidc/login/callback/"


def test_readme_documents_the_oidc_callback_allauth_serves():
    readme = (Path(__file__).resolve().parents[3] / "README.md").read_text()
    assert "/accounts/oidc/<OIDC_PROVIDER_ID>/login/callback/" in readme
    for name in ("OIDC_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_PROVIDER_ID", "OIDC_NAME"):
        assert name in readme


def test_allauth_reads_the_pkce_settings_we_set():
    import inspect

    from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider

    source = inspect.getsource(OAuth2Provider)
    pkce_lines = [line.strip() for line in source.splitlines() if "pkce" in line.lower()]
    blob = "\n".join(pkce_lines)
    assert "OAUTH_PKCE_ENABLED" in blob or "oauth_pkce_enabled" in blob, blob


@pytest.mark.django_db
def test_provider_absent_from_login_matches_disabled_flag(client, settings):
    settings.OIDC_ENABLED = False
    # Importing the flag's effect: an unset provider must not add a button.
    # The registration itself is covered by test_settings_register_oidc_only_when_configured.
    from django.urls import reverse

    response = client.get(reverse("accounts:login"))
    assert b"Sign in with SSO" not in response.content
