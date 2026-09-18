import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks.models import Task
from apps.users.models import User


@pytest.fixture
def api_client_for():
    def _make(user):
        token, _ = Token.objects.get_or_create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    return _make


@pytest.mark.django_db
def test_task_list_scoped_to_user(api_client_for):
    user = User.objects.create_user()
    other = User.objects.create_user()
    mine = Task.objects.create(user=user, title="Mine", status="todo")
    Task.objects.create(user=other, title="Theirs", status="todo")
    client = api_client_for(user)

    response = client.get(reverse("task-list"))

    titles = {t["title"] for t in response.data}
    assert titles == {mine.title}


@pytest.mark.django_db
def test_task_list_excludes_tags(api_client_for):
    user = User.objects.create_user()
    keep = Task.objects.create(user=user, title="Keep", status="todo", tags=["work"])
    Task.objects.create(user=user, title="Drop", status="todo", tags=["home"])
    client = api_client_for(user)

    response = client.get(reverse("task-list"), {"exclude_tags": "home"})

    titles = {t["title"] for t in response.data}
    assert titles == {"Keep"}
    assert keep.title in titles


@pytest.mark.django_db
def test_task_patch_can_set_is_archived(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Stale", status="done")
    client = api_client_for(user)

    response = client.patch(reverse("task-detail", kwargs={"pk": task.pk}), {"is_archived": True})

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.is_archived is True


@pytest.mark.django_db
def test_task_patch_can_set_calendar_and_recurrence_fields(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Standup", status="todo", due_date="2026-01-01")
    client = api_client_for(user)

    response = client.patch(
        reverse("task-detail", kwargs={"pk": task.pk}),
        {
            "due_time": "09:30",
            "duration_minutes": 15,
            "recurrence_days": 1,
            "recurrence_from": "due_date",
        },
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert str(task.due_time) == "09:30:00"
    assert task.duration_minutes == 15
    assert task.recurrence_days == 1
    assert task.recurrence_from == "due_date"


@pytest.mark.django_db
def test_task_patch_rejects_invalid_recurrence_from(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Standup", status="todo")
    client = api_client_for(user)

    response = client.patch(
        reverse("task-detail", kwargs={"pk": task.pk}), {"recurrence_from": "next_tuesday"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_task_reorder_updates_order(api_client_for):
    user = User.objects.create_user()
    a = Task.objects.create(user=user, title="A", status="todo", order=0)
    b = Task.objects.create(user=user, title="B", status="todo", order=1)
    client = api_client_for(user)

    response = client.post(reverse("task-reorder"), {"order": [b.pk, a.pk]}, format="json")

    assert response.status_code == 204
    a.refresh_from_db()
    b.refresh_from_db()
    assert b.order == 0
    assert a.order == 1


@pytest.mark.django_db
def test_task_reorder_ignores_tasks_not_visible_to_user(api_client_for):
    user = User.objects.create_user()
    other = User.objects.create_user()
    mine = Task.objects.create(user=user, title="Mine", status="todo", order=0)
    theirs = Task.objects.create(user=other, title="Theirs", status="todo", order=0)
    client = api_client_for(user)

    response = client.post(reverse("task-reorder"), {"order": [mine.pk, theirs.pk]}, format="json")

    assert response.status_code == 204
    theirs.refresh_from_db()
    assert theirs.order == 0


@pytest.mark.django_db
def test_status_reorder_updates_order(api_client_for):
    from apps.tasks.models import TaskStatus

    user = User.objects.create_user()
    s1 = TaskStatus.objects.create(user=user, name="Blocked", slug="blocked", order=10)
    s2 = TaskStatus.objects.create(user=user, name="Review", slug="review", order=11)
    client = api_client_for(user)

    response = client.post(reverse("taskstatus-reorder"), {"order": [s2.pk, s1.pk]}, format="json")

    assert response.status_code == 204
    s1.refresh_from_db()
    s2.refresh_from_db()
    assert s2.order == 0
    assert s1.order == 1


@pytest.mark.django_db
def test_status_reorder_rejects_another_users_statuses(api_client_for):
    from apps.tasks.models import TaskStatus

    user = User.objects.create_user()
    outsider = User.objects.create_user()
    mine = TaskStatus.objects.create(user=user, name="Blocked", slug="blocked", order=10)
    theirs = TaskStatus.objects.create(user=outsider, name="Blocked", slug="blocked", order=10)
    client = api_client_for(user)

    response = client.post(reverse("taskstatus-reorder"), {"order": [mine.pk, theirs.pk]}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_move_action_records_prior_status_on_completion(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="In flight", status="in_progress")
    client = api_client_for(user)

    response = client.post(reverse("task-move", kwargs={"pk": task.pk}), {"new_status": "done"})

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "done"
    assert task.previous_status == "in_progress"


@pytest.mark.django_db
def test_move_action_restores_prior_status_on_reopen(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="In flight", status="in_progress")
    client = api_client_for(user)
    client.post(reverse("task-move", kwargs={"pk": task.pk}), {"new_status": "done"})

    response = client.post(reverse("task-move", kwargs={"pk": task.pk}), {"new_status": "in_progress"})

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "in_progress"
    assert task.completed_at is None
    assert task.previous_status == ""


@pytest.mark.django_db
def test_status_list_scoped_to_user(api_client_for):
    from apps.tasks.models import TaskStatus

    user = User.objects.create_user()
    other = User.objects.create_user()
    TaskStatus.objects.create(user=user, name="Review", slug="review")
    TaskStatus.objects.create(user=other, name="Other's status", slug="others-status")
    client = api_client_for(user)

    response = client.get(reverse("taskstatus-list"))

    slugs = {s["slug"] for s in response.data}
    assert "review" in slugs
    assert "others-status" not in slugs
