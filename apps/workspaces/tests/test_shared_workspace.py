import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.emailauth.models import EmailIdentity
from apps.tasks.models import Task, TaskStatus
from apps.tasks.selectors import move_task
from apps.users.models import User
from apps.workspaces.access import SESSION_KEY
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.services import create_shared_workspace


def _login(client, user, workspace):
    client.force_login(user)
    session = client.session
    session[SESSION_KEY] = workspace.pk
    session.save()
    return client


@pytest.mark.django_db
def test_shared_workspace_has_its_own_board_and_statuses(client):
    user = User.objects.create_user()
    client.force_login(user)

    response = client.post(reverse("workspaces:create"), {"name": "Family"})

    assert response.status_code == 302
    shared = Workspace.objects.get(kind=Workspace.KIND_SHARED, name="Family")
    assert shared.owner_id is None
    assert Membership.objects.get(workspace=shared, user=user).role == Membership.ROLE_OWNER
    personal = Workspace.objects.get(owner=user)
    assert shared.board.user_id == user.pk
    assert shared.board.pk != personal.board.pk
    personal_slugs = set(personal.statuses.values_list("slug", flat=True))
    shared_slugs = set(shared.statuses.values_list("slug", flat=True))
    assert shared_slugs == personal_slugs
    assert set(shared.statuses.values_list("pk", flat=True)).isdisjoint(
        personal.statuses.values_list("pk", flat=True)
    )
    assert client.session[SESSION_KEY] == shared.pk


@pytest.mark.django_db
def test_board_shows_only_the_active_workspace(client):
    user = User.objects.create_user()
    personal = Workspace.objects.get(owner=user)
    shared = create_shared_workspace(user=user, name="Family")
    Task.objects.create(user=user, workspace=personal, title="Personal only", status="todo")
    Task.objects.create(user=user, workspace=shared, title="Shared only", status="todo")

    _login(client, user, personal)
    personal_page = client.get(reverse("boards:board"))
    assert personal_page.status_code == 200
    assert b"Personal only" in personal_page.content
    assert b"Shared only" not in personal_page.content

    _login(client, user, shared)
    shared_page = client.get(reverse("boards:board"))
    assert b"Shared only" in shared_page.content
    assert b"Personal only" not in shared_page.content


@pytest.mark.django_db
def test_roles_and_membership(client):
    owner = User.objects.create_user()
    member = User.objects.create_user()
    viewer = User.objects.create_user()
    EmailIdentity.objects.create(user=member, email="member@example.com", verified=True)
    EmailIdentity.objects.create(user=viewer, email="viewer@example.com", verified=True)
    shared = create_shared_workspace(user=owner, name="Family")

    _login(client, owner, shared)
    added = client.post(
        reverse("workspaces:member-add"),
        {"email": "Member@example.com", "role": Membership.ROLE_MEMBER},
        follow=True,
    )
    assert added.status_code == 200
    assert Membership.objects.get(workspace=shared, user=member).role == Membership.ROLE_MEMBER
    client.post(
        reverse("workspaces:member-add"),
        {"email": "viewer@example.com", "role": Membership.ROLE_VIEWER},
    )

    missing = client.post(
        reverse("workspaces:member-add"),
        {"email": "nobody@example.com", "role": Membership.ROLE_MEMBER},
        follow=True,
    )
    assert b"No one with that email" in missing.content
    assert shared.memberships.count() == 3

    outsider = User.objects.create_user()
    _login(client, outsider, shared)
    denied = client.post(reverse("workspaces:switch"), {"workspace": shared.pk})
    assert denied.status_code == 404

    _login(client, viewer, shared)
    forbidden = client.post(
        reverse("boards:task-panel-create"),
        {"title": "Nope", "lane": ""},
    )
    assert forbidden.status_code == 403
    assert not Task.objects.filter(title="Nope").exists()

    _login(client, member, shared)
    created = client.post(
        reverse("boards:task-panel-create"),
        {"title": "From a member", "lane": ""},
    )
    assert created.status_code == 200
    task = Task.objects.get(title="From a member")
    assert task.workspace_id == shared.pk
    assert task.user_id == member.pk

    status_denied = client.post(reverse("users:status-create"), {"name": "Waiting"})
    assert status_denied.status_code == 403
    assert not TaskStatus.objects.filter(name="Waiting").exists()

    _login(client, owner, shared)
    status_ok = client.post(reverse("users:status-create"), {"name": "Waiting"})
    assert status_ok.status_code == 200
    assert TaskStatus.objects.get(name="Waiting").workspace_id == shared.pk
    assert not TaskStatus.objects.filter(user=owner, workspace__kind="personal", name="Waiting").exists()


@pytest.mark.django_db
def test_default_status_stays_on_its_workspace(client):
    user = User.objects.create_user()
    personal = Workspace.objects.get(owner=user)
    shared = create_shared_workspace(user=user, name="Family")
    shared_done = shared.statuses.get(slug="done")

    _login(client, user, shared)
    response = client.post(
        reverse("users:settings"),
        {"display_name": "Ada", "default_status": str(shared_done.pk), "timezone": "UTC"},
    )
    assert response.status_code == 302
    shared.refresh_from_db()
    user.refresh_from_db()
    assert shared.default_status_id == shared_done.pk
    assert user.default_status_id is None
    personal.refresh_from_db()
    assert personal.default_status_id is None


@pytest.mark.django_db
def test_bad_timezone_does_not_change_the_shared_default(client):
    user = User.objects.create_user(display_name="Ada", timezone="UTC")
    personal = Workspace.objects.get(owner=user)
    shared = create_shared_workspace(user=user, name="Family")
    todo = shared.statuses.get(slug="todo")
    shared.default_status = todo
    shared.save(update_fields=["default_status"])

    _login(client, user, shared)
    response = client.post(
        reverse("users:settings"),
        {"display_name": "Grace", "default_status": "", "timezone": "Not/AZone"},
        follow=True,
    )

    user.refresh_from_db()
    shared.refresh_from_db()
    personal.refresh_from_db()
    assert response.status_code == 200
    assert user.display_name == "Ada"
    assert user.timezone == "UTC"
    assert user.default_status_id is None
    assert shared.default_status_id == todo.pk
    assert personal.default_status_id is None
    assert any("recognized timezone" in message.message for message in response.context["messages"])


@pytest.mark.django_db
def test_recurrence_stays_in_the_shared_workspace():
    user = User.objects.create_user()
    shared = create_shared_workspace(user=user, name="Family")
    task = Task.objects.create(
        user=user,
        workspace=shared,
        title="Family chore",
        status="todo",
        recurrence_days=7,
    )

    move_task(user, task, "done")

    spawned = Task.objects.get(title="Family chore", status="backlog")
    assert spawned.workspace_id == shared.pk
    assert spawned.pk != task.pk


@pytest.mark.django_db
def test_api_follows_the_workspace_header():
    user = User.objects.create_user()
    personal = Workspace.objects.get(owner=user)
    shared = create_shared_workspace(user=user, name="Family")
    Task.objects.create(user=user, workspace=personal, title="Personal only", status="todo")
    Task.objects.create(user=user, workspace=shared, title="Shared only", status="todo")
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    personal_titles = {row["title"] for row in client.get(reverse("task-list")).data}
    assert personal_titles == {"Personal only"}

    client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}",
        HTTP_X_WORKSPACE_ID=str(shared.pk),
    )
    shared_titles = {row["title"] for row in client.get(reverse("task-list")).data}
    assert shared_titles == {"Shared only"}

    created = client.post(reverse("task-list"), {"title": "Via API", "status": "todo"}, format="json")
    assert created.status_code == 201
    assert Task.objects.get(title="Via API").workspace_id == shared.pk

    outsider = User.objects.create_user()
    other_token, _ = Token.objects.get_or_create(user=outsider)
    client.credentials(
        HTTP_AUTHORIZATION=f"Token {other_token.key}",
        HTTP_X_WORKSPACE_ID=str(shared.pk),
    )
    assert client.get(reverse("task-list")).status_code == 404


@pytest.mark.django_db
def test_last_owner_cannot_be_removed(client):
    user = User.objects.create_user()
    shared = create_shared_workspace(user=user, name="Family")
    membership = Membership.objects.get(workspace=shared, user=user)
    _login(client, user, shared)

    response = client.post(reverse("workspaces:member-remove", args=[membership.pk]), follow=True)

    assert response.status_code == 200
    assert Membership.objects.filter(pk=membership.pk).exists()
    assert b"needs an owner" in response.content


def _team():
    owner = User.objects.create_user()
    member = User.objects.create_user()
    viewer = User.objects.create_user()
    shared = create_shared_workspace(user=owner, name="Family")
    Membership.objects.create(workspace=shared, user=member, role=Membership.ROLE_MEMBER)
    Membership.objects.create(workspace=shared, user=viewer, role=Membership.ROLE_VIEWER)
    return shared, owner, member, viewer


@pytest.mark.django_db
def test_viewers_do_not_get_drag_handles(client):
    shared, owner, member, viewer = _team()
    Task.objects.create(user=owner, workspace=shared, title="Visible", status="todo")

    _login(client, viewer, shared)
    board = client.get(reverse("boards:board")).content
    calendar = client.get(reverse("calendar:calendar")).content
    assert b'draggable="true"' not in board
    assert b"col-drag-handle" not in board
    assert b'draggable="true"' not in calendar
    assert b"calendar-drop-zone" not in calendar

    _login(client, member, shared)
    member_board = client.get(reverse("boards:board")).content
    assert b'draggable="true"' in member_board
    assert b"col-drag-handle" not in member_board

    _login(client, owner, shared)
    owner_board = client.get(reverse("boards:board")).content
    assert b'class="col-drag-handle" draggable="true"' in owner_board


@pytest.mark.django_db
def test_deleting_the_creator_keeps_the_shared_board():
    shared, owner, member, _viewer = _team()
    task = Task.objects.create(user=owner, workspace=shared, title="Owner's", status="todo")
    status_count = shared.statuses.count()

    owner.delete()

    shared.refresh_from_db()
    assert shared.board.user_id is None
    assert shared.statuses.count() == status_count
    task.refresh_from_db()
    assert task.user_id is None
    assert Membership.objects.get(workspace=shared, user=member).role == Membership.ROLE_OWNER


@pytest.mark.django_db
def test_deleting_a_member_keeps_their_shared_tasks():
    shared, _owner, member, _viewer = _team()
    task = Task.objects.create(user=member, workspace=shared, title="Member's", status="todo")
    personal_task = Task.objects.create(
        user=member, workspace=Workspace.objects.get(owner=member), title="Private", status="todo"
    )

    member.delete()

    task.refresh_from_db()
    assert task.user_id is None
    assert task.workspace_id == shared.pk
    assert not Task.objects.filter(pk=personal_task.pk).exists()


@pytest.mark.django_db
def test_deleting_the_last_owner_hands_off_or_removes_the_workspace():
    owner = User.objects.create_user()
    viewer = User.objects.create_user()
    with_viewer = create_shared_workspace(user=owner, name="Family")
    Membership.objects.create(workspace=with_viewer, user=viewer, role=Membership.ROLE_VIEWER)
    alone = create_shared_workspace(user=owner, name="Solo")

    owner.delete()

    assert Membership.objects.get(workspace=with_viewer, user=viewer).role == Membership.ROLE_OWNER
    assert not Workspace.objects.filter(pk=alone.pk).exists()


@pytest.mark.django_db
def test_calendar_sync_only_covers_personal_tasks():
    from apps.integrations.google_calendar.sync import user_tasks_qs

    shared, owner, member, _viewer = _team()
    Task.objects.create(user=owner, workspace=shared, title="Shared, by owner", status="todo")
    Task.objects.create(user=member, workspace=shared, title="Shared, by member", status="todo")
    Task.objects.create(
        user=owner, workspace=Workspace.objects.get(owner=owner), title="Personal", status="todo"
    )

    assert set(user_tasks_qs(owner).values_list("title", flat=True)) == {"Personal"}


@pytest.mark.django_db
def test_only_the_author_or_an_owner_deletes_a_comment(client):
    from apps.tasks.models import TaskComment

    shared, owner, member, _viewer = _team()
    other = User.objects.create_user()
    Membership.objects.create(workspace=shared, user=other, role=Membership.ROLE_MEMBER)
    task = Task.objects.create(user=owner, workspace=shared, title="T", status="todo")
    owners = TaskComment.objects.create(task=task, author=owner, body="owner's")
    members = TaskComment.objects.create(task=task, author=member, body="member's")
    url = lambda comment: reverse("boards:task-comment-delete", args=[task.pk, comment.pk])

    _login(client, other, shared)
    assert client.post(url(members)).status_code == 403
    token, _ = Token.objects.get_or_create(user=other)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}", HTTP_X_WORKSPACE_ID=str(shared.pk))
    assert api.delete(f"/api/v1/comments/{members.pk}/").status_code == 403
    assert TaskComment.objects.filter(pk=members.pk).exists()

    _login(client, member, shared)
    assert client.post(url(owners)).status_code == 403
    assert client.post(url(members)).status_code == 200
    assert not TaskComment.objects.filter(pk=members.pk).exists()

    _login(client, owner, shared)
    other_comment = TaskComment.objects.create(task=task, author=other, body="other's")
    assert client.post(url(other_comment)).status_code == 200
    assert not TaskComment.objects.filter(pk=other_comment.pk).exists()
