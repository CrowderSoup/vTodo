import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks.models import Task, TaskComment, TaskStatus
from apps.users.models import User
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.services import create_shared_workspace


def _api(user, workspace=None):
    token, _ = Token.objects.get_or_create(user=user)
    headers = {"HTTP_AUTHORIZATION": f"Token {token.key}"}
    if workspace is not None:
        headers["HTTP_X_WORKSPACE_ID"] = str(workspace.pk)
    client = APIClient()
    client.credentials(**headers)
    return client


@pytest.fixture
def shared():
    owner = User.objects.create_user()
    workspace = create_shared_workspace(user=owner, name="Aaron & Azure")
    member = User.objects.create_user()
    viewer = User.objects.create_user()
    Membership.objects.create(workspace=workspace, user=member, role=Membership.ROLE_MEMBER)
    Membership.objects.create(workspace=workspace, user=viewer, role=Membership.ROLE_VIEWER)
    task = Task.objects.create(user=owner, workspace=workspace, title="Shared task", status="todo")
    return {"workspace": workspace, "owner": owner, "member": member, "viewer": viewer, "task": task}


@pytest.mark.django_db
def test_lists_the_callers_workspaces_with_roles(shared):
    other = create_shared_workspace(user=User.objects.create_user(), name="Not mine")

    response = _api(shared["member"]).get(reverse("workspace-list"))

    assert response.status_code == 200
    personal = Workspace.objects.get(owner=shared["member"])
    assert response.data == [
        {"id": personal.pk, "name": "Personal", "kind": "personal", "role": "owner",
         "can_write": True, "can_admin": True},
        {"id": shared["workspace"].pk, "name": "Aaron & Azure", "kind": "shared", "role": "member",
         "can_write": True, "can_admin": False},
    ]
    assert other.pk not in {row["id"] for row in response.data}


@pytest.mark.django_db
def test_workspace_list_needs_the_tasks_scope(shared, oauth_client_for):
    client = oauth_client_for(shared["member"], scope="read")

    assert client.get(reverse("workspace-list")).status_code == 403


@pytest.mark.django_db
def test_without_the_header_calls_stay_in_personal(shared, oauth_client_for):
    member = shared["member"]
    personal = Workspace.objects.get(owner=member)
    Task.objects.create(user=member, workspace=personal, title="Mine", status="todo")

    for client in (_api(member), oauth_client_for(member)):
        titles = {row["title"] for row in client.get(reverse("task-list")).data}
        assert "Mine" in titles
        assert "Shared task" not in titles
        created = client.post(reverse("task-list"), {"title": "New"}, format="json")
        assert created.status_code == 201
        assert Task.objects.get(pk=created.data["id"]).workspace_id == personal.pk
        slugs = {row["slug"] for row in client.get(reverse("taskstatus-list")).data}
        assert slugs == set(personal.statuses.values_list("slug", flat=True))


@pytest.mark.django_db
def test_oauth_token_follows_the_header(shared, oauth_client_for):
    client = oauth_client_for(shared["member"])
    client.credentials(
        HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
        HTTP_X_WORKSPACE_ID=str(shared["workspace"].pk),
    )

    titles = {row["title"] for row in client.get(reverse("task-list")).data}

    assert titles == {"Shared task"}


@pytest.mark.django_db
def test_viewer_can_read_but_not_change(shared):
    client = _api(shared["viewer"], shared["workspace"])
    task = shared["task"]

    assert client.get(reverse("task-list")).status_code == 200
    assert client.get(reverse("task-detail", args=[task.pk])).status_code == 200
    assert client.get(reverse("task-comments", args=[task.pk])).status_code == 200
    assert client.get(reverse("task-activity", args=[task.pk])).status_code == 200
    assert client.get(reverse("taskstatus-list")).status_code == 200

    assert client.post(reverse("task-list"), {"title": "No"}, format="json").status_code == 403
    assert client.patch(
        reverse("task-detail", args=[task.pk]), {"title": "No"}, format="json"
    ).status_code == 403
    assert client.post(
        reverse("task-move", args=[task.pk]), {"new_status": "done"}, format="json"
    ).status_code == 403
    assert client.post(
        reverse("task-comments", args=[task.pk]), {"body": "No"}, format="json"
    ).status_code == 403
    assert client.delete(reverse("task-detail", args=[task.pk])).status_code == 403
    assert client.post(reverse("taskstatus-list"), {"name": "No"}, format="json").status_code == 403

    task.refresh_from_db()
    assert task.title == "Shared task"
    assert task.status == "todo"
    assert not TaskComment.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_member_changes_tasks_but_not_statuses(shared):
    client = _api(shared["member"], shared["workspace"])
    task = shared["task"]

    created = client.post(reverse("task-list"), {"title": "From Gerald"}, format="json")
    assert created.status_code == 201
    assert Task.objects.get(pk=created.data["id"]).workspace_id == shared["workspace"].pk
    assert client.patch(
        reverse("task-detail", args=[task.pk]), {"title": "Renamed"}, format="json"
    ).status_code == 200
    assert client.post(
        reverse("task-move", args=[task.pk]), {"new_status": "done"}, format="json"
    ).status_code == 200
    assert client.post(
        reverse("task-comments", args=[task.pk]), {"body": "On it"}, format="json"
    ).status_code == 201

    assert client.post(reverse("taskstatus-list"), {"name": "Blocked"}, format="json").status_code == 403
    assert client.patch(
        reverse("taskstatus-detail", args=["todo"]), {"name": "Later"}, format="json"
    ).status_code == 403
    assert client.delete(reverse("taskstatus-detail", args=["todo"])).status_code == 403
    assert not TaskStatus.objects.filter(workspace=shared["workspace"], name="Blocked").exists()


@pytest.mark.django_db
def test_owner_changes_statuses(shared):
    client = _api(shared["owner"], shared["workspace"])

    response = client.post(reverse("taskstatus-list"), {"name": "Blocked"}, format="json")

    assert response.status_code == 201
    status = TaskStatus.objects.get(slug="blocked")
    assert status.workspace_id == shared["workspace"].pk
    assert client.patch(
        reverse("taskstatus-detail", args=["blocked"]), {"color": "#ff0000"}, format="json"
    ).status_code == 200


@pytest.mark.django_db
def test_shared_task_is_hidden_from_personal_calls(shared):
    client = _api(shared["member"])

    assert client.get(reverse("task-detail", args=[shared["task"].pk])).status_code == 404
