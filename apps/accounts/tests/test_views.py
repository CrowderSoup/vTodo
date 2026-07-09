import pytest
from django.urls import reverse

from apps.users.models import User


@pytest.mark.django_db
def test_login_renders_for_anonymous_user(client):
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    assert b"Sign in" in response.content


@pytest.mark.django_db
def test_login_redirects_authenticated_user(client):
    user = User.objects.create_user()
    client.force_login(user)
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 302
    assert response["Location"] == "/board/"


@pytest.mark.django_db
def test_logout_clears_session_and_redirects(client):
    user = User.objects.create_user()
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:login")
    assert "_auth_user_id" not in client.session
