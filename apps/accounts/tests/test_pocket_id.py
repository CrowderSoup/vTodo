from pathlib import Path

import pytest
from django.conf import settings

from apps.accounts.pocket_id import (
    discover_provider_paths,
    pocket_id_callback_path,
    pocket_id_provider_settings,
)


def test_pocket_id_provider_absent_unless_all_env_vars_are_set():
    assert pocket_id_provider_settings("", "", "") is None
    assert pocket_id_provider_settings("https://id.example.com", "client", "") is None
    assert pocket_id_provider_settings("https://id.example.com", "", "secret") is None
    assert pocket_id_provider_settings("", "client", "secret") is None
    assert pocket_id_provider_settings("  ", "client", "secret") is None


def test_pocket_id_provider_uses_authorization_code_with_pkce():
    provider = pocket_id_provider_settings("https://id.example.com/", "client-id", "client-secret")
    assert provider["OAUTH_PKCE_ENABLED"] is True
    assert provider["SCOPE"] == ["openid", "profile", "email"]
    app = provider["APPS"][0]
    assert app["provider_id"] == "pocket-id"
    assert app["name"] == "Pocket ID"
    assert app["client_id"] == "client-id"
    assert app["secret"] == "client-secret"
    assert app["settings"]["server_url"] == "https://id.example.com"
    assert app["settings"]["oauth_pkce_enabled"] is True


def test_settings_register_pocket_id_only_when_configured():
    configured = bool(
        settings.POCKET_ID_URL.strip()
        and settings.POCKET_ID_CLIENT_ID.strip()
        and settings.POCKET_ID_CLIENT_SECRET.strip()
    )
    assert settings.POCKET_ID_ENABLED is configured
    installed = "allauth.socialaccount.providers.openid_connect" in settings.INSTALLED_APPS
    assert installed is configured
    assert ("openid_connect" in settings.SOCIALACCOUNT_PROVIDERS) is configured
    if configured:
        provider = settings.SOCIALACCOUNT_PROVIDERS["openid_connect"]
        assert provider["OAUTH_PKCE_ENABLED"] is True
        app = provider["APPS"][0]
        assert app["provider_id"] == "pocket-id"
        assert app["settings"]["oauth_pkce_enabled"] is True


def test_google_callback_path_matches_the_documented_accounts_prefix():
    paths = discover_provider_paths("allauth.socialaccount.providers.google")
    assert paths.get("google_callback") == "/accounts/google/login/callback/", paths


def test_readme_documents_the_pocket_id_callback_allauth_serves():
    readme = (Path(__file__).resolve().parents[3] / "README.md").read_text()
    callback = pocket_id_callback_path()
    assert callback in readme
    assert "POCKET_ID_URL" in readme
    assert "POCKET_ID_CLIENT_ID" in readme
    assert "POCKET_ID_CLIENT_SECRET" in readme


def test_allauth_reads_the_pkce_settings_we_set():
    import inspect

    from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider

    source = inspect.getsource(OAuth2Provider)
    pkce_lines = [line.strip() for line in source.splitlines() if "pkce" in line.lower()]
    blob = "\n".join(pkce_lines)
    assert "OAUTH_PKCE_ENABLED" in blob or "oauth_pkce_enabled" in blob, blob


@pytest.mark.django_db
def test_provider_absent_from_login_matches_disabled_flag(client, settings):
    settings.POCKET_ID_ENABLED = False
    # Importing the flag's effect: an unset provider must not add a button.
    # The registration itself is covered by test_settings_register_pocket_id_only_when_configured.
    from django.urls import reverse

    response = client.get(reverse("accounts:login"))
    assert b"Sign in with Pocket ID" not in response.content
