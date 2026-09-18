from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse

from apps.integrations import views
from apps.integrations.models import ExternalLink, GoogleCalendarConnection
from apps.tasks.models import Task
from apps.users.models import User


@pytest.fixture
def logged_in_client(client, db):
    user = User.objects.create_user()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_connect_redirects_to_google_with_expected_params(logged_in_client):
    client, _ = logged_in_client

    response = client.get(reverse("integrations:google-calendar-connect"))

    assert response.status_code == 302
    parsed = urlparse(response.url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == views.GOOGLE_AUTH_URL
    query = parse_qs(parsed.query)
    assert query["scope"] == [views.CALENDAR_SCOPE]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"][0] == client.session[views.STATE_SESSION_KEY]


@pytest.mark.django_db
def test_callback_creates_connection(logged_in_client, monkeypatch):
    client, user = logged_in_client
    session = client.session
    session[views.STATE_SESSION_KEY] = "expected-state"
    session.save()

    monkeypatch.setattr(views, "exchange_code", lambda code, redirect_uri: {"refresh_token": "rt-123"})

    class FakeClient:
        def __init__(self, connection):
            pass

        def create_calendar(self, summary):
            return "cal-abc"

    monkeypatch.setattr(views, "GoogleCalendarClient", FakeClient)

    response = client.get(
        reverse("integrations:google-calendar-callback"), {"code": "auth-code", "state": "expected-state"}
    )

    assert response.status_code == 302
    connection = GoogleCalendarConnection.objects.get(user=user)
    assert connection.calendar_id == "cal-abc"
    assert connection.get_refresh_token() == "rt-123"
    assert connection.is_active is True


@pytest.mark.django_db
def test_callback_rejects_mismatched_state(logged_in_client):
    client, user = logged_in_client
    session = client.session
    session[views.STATE_SESSION_KEY] = "expected-state"
    session.save()

    response = client.get(
        reverse("integrations:google-calendar-callback"), {"code": "auth-code", "state": "wrong-state"}
    )

    assert response.status_code == 302
    assert not GoogleCalendarConnection.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_callback_without_refresh_token_shows_error(logged_in_client, monkeypatch):
    client, user = logged_in_client
    session = client.session
    session[views.STATE_SESSION_KEY] = "expected-state"
    session.save()

    monkeypatch.setattr(views, "exchange_code", lambda code, redirect_uri: {})

    response = client.get(
        reverse("integrations:google-calendar-callback"), {"code": "auth-code", "state": "expected-state"}
    )

    assert response.status_code == 302
    assert not GoogleCalendarConnection.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_disconnect_deletes_connection_and_links(logged_in_client, monkeypatch):
    client, user = logged_in_client
    GoogleCalendarConnection.objects.create(user=user, calendar_id="cal-abc", refresh_token_encrypted="x")
    task = Task.objects.create(user=user, title="Renew passport")
    ExternalLink.objects.create(task=task, provider=ExternalLink.Provider.GOOGLE_CALENDAR, external_id="evt-1")

    class FakeClient:
        def __init__(self, connection):
            pass

        def delete_calendar(self, calendar_id):
            pass

    monkeypatch.setattr(views, "GoogleCalendarClient", FakeClient)
    monkeypatch.setattr(views, "revoke", lambda refresh_token: None)

    response = client.post(reverse("integrations:google-calendar-disconnect"))

    assert response.status_code == 302
    assert not GoogleCalendarConnection.objects.filter(user=user).exists()
    assert not ExternalLink.objects.filter(provider=ExternalLink.Provider.GOOGLE_CALENDAR).exists()


@pytest.mark.django_db
def test_disconnect_without_connection_is_noop(logged_in_client):
    client, _ = logged_in_client

    response = client.post(reverse("integrations:google-calendar-disconnect"))

    assert response.status_code == 302
