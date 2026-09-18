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
            "default_status": str(default_status.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_status_id == default_status.pk


@pytest.mark.django_db
def test_settings_post_cannot_set_avatar_url_manually(logged_in_client):
    client, user = logged_in_client
    default_status = user.task_statuses.get(slug="done")

    client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "avatar_url": "https://evil.example.com/not-my-avatar.jpg",
            "default_status": str(default_status.pk),
        },
    )

    user.refresh_from_db()
    assert user.avatar_url == ""


@pytest.mark.django_db
def test_settings_post_rejects_default_status_from_another_user(logged_in_client):
    client, user = logged_in_client
    other_user = User.objects.create_user()
    other_status = other_user.task_statuses.first()

    response = client.post(
        reverse("users:settings"),
        {
            "display_name": "",
            "default_status": str(other_status.pk),
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.default_status_id is None


@pytest.mark.django_db
def test_settings_calendar_shows_connect_link_when_disconnected(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("users:settings-calendar"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Connect Google Calendar" in content


@pytest.mark.django_db
def test_settings_calendar_shows_status_when_connected(logged_in_client):
    from apps.integrations.models import GoogleCalendarConnection

    client, user = logged_in_client
    GoogleCalendarConnection.objects.create(user=user, calendar_id="cal-abc", refresh_token_encrypted="x")

    response = client.get(reverse("users:settings-calendar"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Disconnect" in content
    assert "Connect Google Calendar" not in content


@pytest.mark.django_db
def test_settings_includes_shared_confirm_modal(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("users:settings"))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id="confirm-modal"' in content
    assert 'id="confirm-modal-cancel"' in content


# ---------------------------------------------------------------------------
# Column/status creation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_column_create_creates_on_personal_board(logged_in_client):
    from apps.boards.models import Board, Column

    client, user = logged_in_client

    response = client.post(
        reverse("users:column-create"),
        {"label": "Overdue", "due": "overdue"},
    )

    assert response.status_code == 200
    board = Board.objects.get(user=user)
    column = Column.objects.get(label="Overdue")
    assert column.board_id == board.pk
    assert column.filter_config["due"] == "overdue"


@pytest.mark.django_db
def test_status_create_creates_for_user(logged_in_client):
    from apps.tasks.models import TaskStatus

    client, user = logged_in_client

    response = client.post(reverse("users:status-create"), {"name": "Review"})

    assert response.status_code == 200
    assert TaskStatus.objects.filter(user=user, slug="review").exists()


@pytest.mark.django_db
def test_status_color_update_sets_color(logged_in_client):
    from apps.tasks.models import TaskStatus

    client, user = logged_in_client
    status = TaskStatus.objects.get(user=user, slug="todo")

    response = client.post(reverse("users:status-color-update", args=[status.pk]), {"color": "#ff0000"})

    assert response.status_code == 200
    status.refresh_from_db()
    assert status.color == "#ff0000"


@pytest.mark.django_db
def test_status_color_update_clears_color(logged_in_client):
    from apps.tasks.models import TaskStatus

    client, user = logged_in_client
    status = TaskStatus.objects.get(user=user, slug="todo")
    status.color = "#ff0000"
    status.save(update_fields=["color"])

    response = client.post(reverse("users:status-color-update", args=[status.pk]), {"color": ""})

    assert response.status_code == 200
    status.refresh_from_db()
    assert status.color == ""


@pytest.mark.django_db
def test_status_color_update_rejects_invalid_hex(logged_in_client):
    from apps.tasks.models import TaskStatus

    client, user = logged_in_client
    status = TaskStatus.objects.get(user=user, slug="todo")

    response = client.post(reverse("users:status-color-update", args=[status.pk]), {"color": "not-a-color"})

    assert response.status_code == 422
    status.refresh_from_db()
    assert status.color == ""


@pytest.mark.django_db
def test_status_color_update_rejects_another_users_status(logged_in_client):
    from apps.tasks.models import TaskStatus

    client, user = logged_in_client
    other = User.objects.create_user()
    other_status = TaskStatus.objects.get(user=other, slug="todo")

    response = client.post(reverse("users:status-color-update", args=[other_status.pk]), {"color": "#ff0000"})

    assert response.status_code == 404
    other_status.refresh_from_db()
    assert other_status.color == ""
