import pytest
from django.urls import reverse

from apps.users.models import User


@pytest.fixture
def logged_in_client(client, db):
    user = User.objects.create_user()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_settings_post_saves_default_column(logged_in_client):
    client, user = logged_in_client
    default_column = user.board.columns.get(label="Done")

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "",
            "daily_summary_time": "08:00",
            "default_column": str(default_column.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_column_id == default_column.pk


@pytest.mark.django_db
def test_settings_post_rejects_default_column_from_another_user(logged_in_client):
    client, user = logged_in_client
    other_user = User.objects.create_user()
    other_column = other_user.board.columns.first()

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "",
            "daily_summary_time": "08:00",
            "default_column": str(other_column.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_column_id is None
