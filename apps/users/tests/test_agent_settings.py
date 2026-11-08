import re

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.api.models import DeviceToken
from apps.tasks.models import Task
from apps.users.agents import create_agent
from apps.users.models import User
from apps.workspaces.models import Workspace


def _token_in(response):
    match = re.search(r"(vtd_[A-Za-z0-9_-]+)", response.content.decode())
    return match.group(1) if match else None


def _works(raw):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {raw}")
    return client.get(reverse("task-list")).status_code == 200


@pytest.mark.django_db
def test_create_an_agent_and_see_its_token_once(client):
    user = User.objects.create_user()
    client.force_login(user)

    response = client.post(reverse("users:agent-create"), {"name": "Coder"})

    assert response.status_code == 200
    agent = User.objects.get(parent=user)
    assert agent.display_name == "Coder" and agent.is_agent
    raw = _token_in(response)
    assert raw and _works(raw)
    page = client.get(reverse("users:settings-api"))
    assert b"Coder" in page.content
    assert raw.encode() not in page.content


@pytest.mark.django_db
def test_blank_agent_name_is_refused(client):
    user = User.objects.create_user()
    client.force_login(user)

    response = client.post(reverse("users:agent-create"), {"name": "  "})

    assert b"Give the agent a name." in response.content
    assert not User.objects.filter(parent=user).exists()


@pytest.mark.django_db
def test_new_token_replaces_the_old_one(client):
    user = User.objects.create_user()
    agent, old = create_agent(parent=user, name="Coder")
    client.force_login(user)

    response = client.post(reverse("users:agent-token", args=[agent.pk]))

    new = _token_in(response)
    assert new and new != old
    assert _works(new)
    assert not _works(old)
    assert DeviceToken.objects.filter(user=agent).count() == 1


@pytest.mark.django_db
def test_only_your_own_agents_can_be_changed(client):
    owner = User.objects.create_user()
    agent, raw = create_agent(parent=owner, name="Coder")
    client.force_login(User.objects.create_user())

    assert client.post(reverse("users:agent-token", args=[agent.pk])).status_code == 404
    client.post(reverse("users:agent-delete", args=[agent.pk]))

    assert User.objects.filter(pk=agent.pk).exists()
    assert _works(raw)


@pytest.mark.django_db
def test_delete_an_agent(client):
    user = User.objects.create_user()
    agent, raw = create_agent(parent=user, name="Coder")
    client.force_login(user)

    response = client.post(reverse("users:agent-delete", args=[agent.pk]))

    assert response.status_code == 200
    assert not User.objects.filter(pk=agent.pk).exists()
    assert not _works(raw)


@pytest.mark.django_db
def test_assign_from_the_task_panel(client):
    user = User.objects.create_user()
    agent, _raw = create_agent(parent=user, name="Coder")
    stranger = User.objects.create_user()
    task = Task.objects.create(user=user, workspace=Workspace.objects.get(owner=user), title="T", status="todo")
    client.force_login(user)

    edit = client.get(reverse("boards:task-panel-edit", args=[task.pk]))
    assert b"data-assignee-picker" in edit.content
    assert b'"name": "Coder"' in edit.content

    data = {"title": "T", "notes": "", "tags": "", "recurrence_from": "completion"}
    response = client.post(reverse("boards:task-panel-update", args=[task.pk]), {**data, "assignee": agent.pk})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.assignee == agent

    panel = client.get(reverse("boards:task-panel", args=[task.pk]))
    assert b"Assigned to Coder" in panel.content

    bad = client.post(reverse("boards:task-panel-update", args=[task.pk]), {**data, "assignee": stranger.pk})
    assert bad.status_code == 422

    # The inline card form has no assignee field, so it leaves it alone.
    client.post(reverse("boards:task-update", args=[task.pk]), data)
    task.refresh_from_db()
    assert task.assignee == agent

    client.post(reverse("boards:task-panel-update", args=[task.pk]), {**data, "assignee": ""})
    task.refresh_from_db()
    assert task.assignee is None


def _options(response, field_id):
    import json

    match = re.search(
        rf'<script id="{field_id}-options" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.S,
    )
    return json.loads(match.group(1))


@pytest.mark.django_db
def test_picker_offers_writers_and_agents_with_you_first(client):
    from apps.workspaces.models import Membership
    from apps.workspaces.services import create_shared_workspace
    from apps.workspaces.access import SESSION_KEY

    owner = User.objects.create_user(display_name="Owner")
    shared = create_shared_workspace(user=owner, name="Family")
    me = User.objects.create_user(display_name="Me")
    viewer = User.objects.create_user(display_name="Viewer")
    Membership.objects.create(workspace=shared, user=me, role=Membership.ROLE_MEMBER)
    Membership.objects.create(workspace=shared, user=viewer, role=Membership.ROLE_VIEWER)
    agent, _raw = create_agent(parent=owner, name="Coder")
    task = Task.objects.create(user=owner, workspace=shared, title="T", status="todo")
    client.force_login(me)
    session = client.session
    session[SESSION_KEY] = shared.pk
    session.save()

    options = _options(client.get(reverse("boards:task-panel-edit", args=[task.pk])), "task-panel-assignee")

    assert options[0] == {"id": me.pk, "name": "Me", "agent": False, "me": True}
    assert {o["name"] for o in options} == {"Me", "Owner", "Coder"}
    assert next(o for o in options if o["name"] == "Coder")["agent"] is True

    create = client.get(reverse("boards:task-panel-create"))
    assert _options(create, "task-panel-create-assignee") == options


@pytest.mark.django_db
def test_assign_when_creating_a_task(client):
    user = User.objects.create_user()
    agent, _raw = create_agent(parent=user, name="Coder")
    stranger = User.objects.create_user()
    client.force_login(user)

    response = client.post(reverse("boards:task-panel-create"), {"title": "New", "assignee": agent.pk})
    assert response.status_code == 200
    assert Task.objects.get(title="New").assignee == agent

    bad = client.post(reverse("boards:task-panel-create"), {"title": "Bad", "assignee": stranger.pk})
    assert bad.status_code == 422
    assert b"Pick someone who can work in this workspace." in bad.content
    assert not Task.objects.filter(title="Bad").exists()

    client.post(reverse("boards:task-panel-create"), {"title": "Nobody", "assignee": ""})
    assert Task.objects.get(title="Nobody").assignee is None


@pytest.mark.django_db
def test_board_cards_show_the_assignee(client):
    user = User.objects.create_user()
    agent, _raw = create_agent(parent=user, name="Coder")
    Task.objects.create(user=user, workspace=Workspace.objects.get(owner=user), title="T",
                        status="todo", assignee=agent)
    client.force_login(user)

    board = client.get(reverse("boards:board"))

    assert b"@Coder" in board.content
