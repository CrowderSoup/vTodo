import pytest
from django.urls import reverse

from apps.users.models import User


@pytest.fixture
def logged_in_client(client, db):
    user = User.objects.create_user()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_settings_post_saves_default_status(logged_in_client):
    client, user = logged_in_client
    default_status = user.task_statuses.get(slug="done")

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "",
            "daily_summary_time": "08:00",
            "default_status": str(default_status.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_status_id == default_status.pk


@pytest.mark.django_db
def test_settings_post_rejects_default_status_from_another_user(logged_in_client):
    client, user = logged_in_client
    other_user = User.objects.create_user()
    other_status = other_user.task_statuses.first()

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "",
            "daily_summary_time": "08:00",
            "default_status": str(other_status.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_status_id is None


@pytest.mark.django_db
def test_settings_includes_shared_confirm_modal(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("users:settings"))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id="confirm-modal"' in content
    assert 'id="confirm-modal-cancel"' in content
