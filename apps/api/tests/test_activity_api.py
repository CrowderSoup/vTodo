import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks.models import Task, TaskActivity, TaskComment
from apps.users.models import User


@pytest.fixture
def api_client_for():
    def _make(user, **headers):
        token, _ = Token.objects.get_or_create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}", **headers)
        return client

    return _make


def _rows(task_pk):
    return list(TaskActivity.objects.filter(task_pk=task_pk).order_by("pk"))


@pytest.mark.django_db
def test_api_create_records_created_with_api_source(api_client_for):
    user = User.objects.create_user()
    response = api_client_for(user).post(reverse("task-list"), {"title": "Via API"}, format="json")
    (row,) = _rows(response.data["id"])
    assert (row.action, row.source, row.actor) == ("created", "api", user)


@pytest.mark.django_db
def test_mcp_client_header_marks_source_mcp(api_client_for):
    user = User.objects.create_user()
    client = api_client_for(user, HTTP_X_VTODO_CLIENT="mcp")
    response = client.post(reverse("task-list"), {"title": "Via MCP"}, format="json")
    assert _rows(response.data["id"])[0].source == "mcp"


@pytest.mark.django_db
def test_oauth_token_marks_source_mcp(oauth_client_for):
    user = User.objects.create_user(username="oauth-activity")
    client = oauth_client_for(user)
    response = client.post(reverse("task-list"), {"title": "Via OAuth"}, format="json")
    assert response.status_code == 201
    assert _rows(response.data["id"])[0].source == "mcp"


@pytest.mark.django_db
def test_patch_records_fields_and_status_once(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Old", status="todo")
    api_client_for(user).patch(
        reverse("task-detail", args=[task.pk]),
        {"title": "New", "status": "in_progress"},
        format="json",
    )
    got = [(r.action, r.field) for r in _rows(task.pk)]
    assert got == [("updated", "title"), ("moved", "status")]


@pytest.mark.django_db
def test_patch_archive_records_archived(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    api_client_for(user).patch(reverse("task-detail", args=[task.pk]), {"is_archived": True}, format="json")
    assert [r.action for r in _rows(task.pk)] == ["archived"]


@pytest.mark.django_db
def test_move_action_records(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T", status="todo")
    api_client_for(user).post(reverse("task-move", args=[task.pk]), {"new_status": "done"}, format="json")
    assert [(r.action, r.new_value) for r in _rows(task.pk)] == [("moved", "done")]


@pytest.mark.django_db
def test_api_delete_records_deleted(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    pk = task.pk
    api_client_for(user).delete(reverse("task-detail", args=[pk]))
    assert [r.action for r in _rows(pk)] == ["deleted"]


@pytest.mark.django_db
def test_api_comment_sets_author_and_ignores_client_author(api_client_for):
    user = User.objects.create_user()
    other = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    response = api_client_for(user).post(
        reverse("task-comments", args=[task.pk]), {"body": "hi", "author": other.pk}, format="json"
    )
    assert response.status_code == 201
    assert response.data["author"] == user.pk
    assert TaskComment.objects.get().author == user
    assert [r.action for r in _rows(task.pk)] == ["commented"]


@pytest.mark.django_db
def test_api_comment_delete_records(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    comment = TaskComment.objects.create(task=task, body="x")
    api_client_for(user).delete(reverse("taskcomment-detail", args=[comment.pk]))
    assert [r.action for r in _rows(task.pk)] == ["comment_deleted"]


@pytest.mark.django_db
def test_activity_endpoint_lists_history_oldest_first(api_client_for):
    user = User.objects.create_user(display_name="Aaron")
    client = api_client_for(user)
    task = Task.objects.create(user=user, title="T", status="todo")
    client.post(reverse("task-move", args=[task.pk]), {"new_status": "in_progress"}, format="json")
    client.patch(reverse("task-detail", args=[task.pk]), {"title": "T2"}, format="json")

    response = client.get(reverse("task-activity", args=[task.pk]))

    assert response.status_code == 200
    assert [(e["action"], e["field"]) for e in response.data] == [("moved", "status"), ("updated", "title")]
    first = response.data[0]
    assert first["task"] == task.pk
    assert first["actor_name"] == "Aaron"
    assert first["source"] == "api"


@pytest.mark.django_db
def test_activity_endpoint_is_scoped_to_owner(api_client_for):
    owner = User.objects.create_user()
    other = User.objects.create_user()
    task = Task.objects.create(user=owner, title="T")
    response = api_client_for(other).get(reverse("task-activity", args=[task.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_activity_endpoint_lists_history_of_a_deleted_task(api_client_for):
    user = User.objects.create_user()
    client = api_client_for(user)
    task_id = client.post(reverse("task-list"), {"title": "Gone"}, format="json").data["id"]
    client.delete(reverse("task-detail", args=[task_id]))

    response = client.get(reverse("task-activity", args=[task_id]))

    assert response.status_code == 200
    assert [e["action"] for e in response.data] == ["created", "deleted"]


@pytest.mark.django_db
def test_activity_of_a_deleted_task_is_scoped_to_owner(api_client_for):
    owner = User.objects.create_user()
    other = User.objects.create_user()
    owner_client = api_client_for(owner)
    task_id = owner_client.post(reverse("task-list"), {"title": "Gone"}, format="json").data["id"]
    owner_client.delete(reverse("task-detail", args=[task_id]))

    response = api_client_for(other).get(reverse("task-activity", args=[task_id]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_activity_endpoint_lists_nothing_for_a_task_without_history(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    response = api_client_for(user).get(reverse("task-activity", args=[task.pk]))
    assert (response.status_code, response.data) == (200, [])


@pytest.mark.django_db
def test_activity_endpoint_404s_for_a_non_numeric_id(api_client_for):
    user = User.objects.create_user()
    response = api_client_for(user).get(reverse("task-activity", args=["abc"]))
    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("task_id", [str(2**63), str(10**30), "-1"])
def test_activity_endpoint_404s_for_an_out_of_range_id(api_client_for, task_id):
    user = User.objects.create_user()
    response = api_client_for(user).get(reverse("task-activity", args=[task_id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_activity_endpoint_is_read_only(api_client_for):
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="T")
    response = api_client_for(user).post(reverse("task-activity", args=[task.pk]), {}, format="json")
    assert response.status_code == 405
