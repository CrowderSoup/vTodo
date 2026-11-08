from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.boards.models import Board
from apps.tasks.claims import MAX_LEASE, MIN_LEASE
from apps.tasks.models import Task, TaskActivity, TaskStatus
from apps.users.agents import create_agent
from apps.users.models import User
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.services import create_shared_workspace


def _agent_api(raw, workspace=None):
    client = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"Token {raw}"}
    if workspace is not None:
        headers["HTTP_X_WORKSPACE_ID"] = str(workspace.pk)
    client.credentials(**headers)
    return client


def _human_api(user, workspace=None):
    token, _ = Token.objects.get_or_create(user=user)
    return _agent_api(token.key, workspace)


@pytest.fixture
def aaron():
    return User.objects.create_user(display_name="Aaron")


@pytest.fixture
def coder(aaron):
    agent, raw = create_agent(parent=aaron, name="Coder")
    return agent, raw


def _task(owner, title="Do it", status="todo", workspace=None, **kwargs):
    workspace = workspace or Workspace.objects.get(owner=owner)
    return Task.objects.create(user=owner, workspace=workspace, title=title, status=status, **kwargs)


# ── Agents ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_an_agent_has_no_workspace_of_its_own(aaron, coder):
    agent, raw = coder

    assert agent.is_agent
    assert agent.parent == aaron
    assert agent.account == aaron
    assert not Workspace.objects.filter(owner=agent).exists()
    assert not Membership.objects.filter(user=agent).exists()
    assert not Board.objects.filter(user=agent).exists()
    assert not TaskStatus.objects.filter(user=agent).exists()
    assert raw.startswith("vtd_")


@pytest.mark.django_db
def test_an_agent_cannot_have_agents(coder):
    agent, _raw = coder

    with pytest.raises(ValidationError):
        create_agent(parent=agent, name="Sub")


@pytest.mark.django_db
def test_an_agent_works_in_its_parents_personal_workspace(aaron, coder):
    _agent, raw = coder
    _task(aaron, "Parent's task")
    client = _agent_api(raw)

    titles = {row["title"] for row in client.get(reverse("task-list")).data}
    created = client.post(reverse("task-list"), {"title": "From the agent"}, format="json")

    assert titles == {"Parent's task"}
    assert created.status_code == 201
    assert Task.objects.get(pk=created.data["id"]).workspace == Workspace.objects.get(owner=aaron)
    # A member, not an owner: statuses stay the parent's to change.
    assert client.post(reverse("taskstatus-list"), {"name": "Blocked"}, format="json").status_code == 403


@pytest.mark.django_db
def test_agent_roles_follow_the_parent_capped_at_member(aaron, coder):
    _agent, raw = coder
    owned = create_shared_workspace(user=aaron, name="Owned")
    viewing = create_shared_workspace(user=User.objects.create_user(), name="Viewing")
    Membership.objects.create(workspace=viewing, user=aaron, role=Membership.ROLE_VIEWER)
    elsewhere = create_shared_workspace(user=User.objects.create_user(), name="Elsewhere")

    rows = {row["name"]: row for row in _agent_api(raw).get(reverse("workspace-list")).data}
    assert set(rows) == {"Personal", "Owned", "Viewing"}
    assert rows["Owned"]["role"] == "member"
    assert rows["Viewing"]["role"] == "viewer"
    assert rows["Personal"]["role"] == "member"

    in_owned = _agent_api(raw, owned)
    assert in_owned.post(reverse("task-list"), {"title": "Yes"}, format="json").status_code == 201
    assert in_owned.post(reverse("taskstatus-list"), {"name": "No"}, format="json").status_code == 403

    in_viewing = _agent_api(raw, viewing)
    assert in_viewing.get(reverse("task-list")).status_code == 200
    assert in_viewing.post(reverse("task-list"), {"title": "No"}, format="json").status_code == 403

    assert _agent_api(raw, elsewhere).get(reverse("task-list")).status_code == 404


@pytest.mark.django_db
def test_deleting_the_parent_deletes_its_agents(aaron, coder):
    agent, _raw = coder

    aaron.delete()

    assert not User.objects.filter(pk=agent.pk).exists()


# ── Assignment ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_assign_a_task_to_an_agent(aaron, coder):
    agent, _raw = coder
    task = _task(aaron)

    response = _human_api(aaron).patch(
        reverse("task-detail", args=[task.pk]), {"assignee": agent.pk}, format="json"
    )

    assert response.status_code == 200
    assert response.data["assignee"] == agent.pk
    assert response.data["assignee_name"] == "Coder"
    task.refresh_from_db()
    assert task.assignee == agent
    row = TaskActivity.objects.get(task=task, field="assignee")
    assert (row.old_value, row.new_value) == ("", "Coder")


@pytest.mark.django_db
def test_assignee_must_be_able_to_work_in_the_workspace(aaron, coder):
    agent, _raw = coder
    stranger = User.objects.create_user()
    stranger_agent, _ = create_agent(parent=stranger, name="Theirs")
    shared = create_shared_workspace(user=aaron, name="Shared")
    viewer = User.objects.create_user()
    Membership.objects.create(workspace=shared, user=viewer, role=Membership.ROLE_VIEWER)
    client = _human_api(aaron, shared)

    for bad in (stranger.pk, stranger_agent.pk, viewer.pk, 999999):
        response = client.post(reverse("task-list"), {"title": "X", "assignee": bad}, format="json")
        assert response.status_code == 400, bad

    response = client.post(reverse("task-list"), {"title": "X", "assignee": agent.pk}, format="json")
    assert response.status_code == 201


@pytest.mark.django_db
def test_assignees_lists_writers_and_their_agents(aaron, coder):
    agent, _raw = coder
    shared = create_shared_workspace(user=aaron, name="Shared")
    member = User.objects.create_user(display_name="Azure")
    member_agent, _ = create_agent(parent=member, name="Helper")
    viewer = User.objects.create_user(display_name="Viewer")
    Membership.objects.create(workspace=shared, user=member, role=Membership.ROLE_MEMBER)
    Membership.objects.create(workspace=shared, user=viewer, role=Membership.ROLE_VIEWER)

    rows = _human_api(aaron, shared).get(reverse("assignee-list")).data

    assert {row["id"] for row in rows} == {aaron.pk, member.pk, agent.pk, member_agent.pk}
    assert {row["kind"] for row in rows if row["id"] == agent.pk} == {"agent"}
    assert next(row for row in rows if row["id"] == agent.pk)["parent"] == aaron.pk


@pytest.mark.django_db
def test_task_list_filters(aaron, coder):
    agent, raw = coder
    mine = _task(aaron, "Agent's", assignee=agent)
    _task(aaron, "Unassigned")
    _task(aaron, "Aaron's", assignee=aaron)
    held = _task(aaron, "Held", assignee=agent, claimed_by=aaron,
                 claim_expires_at=timezone.now() + timedelta(minutes=5))
    lapsed = _task(aaron, "Lapsed", assignee=agent, claimed_by=aaron,
                   claim_expires_at=timezone.now() - timedelta(minutes=5))
    client = _agent_api(raw)

    def titles(params):
        return {row["title"] for row in client.get(reverse("task-list"), params).data}

    assert titles({"assignee": "me"}) == {"Agent's", "Held", "Lapsed"}
    assert titles({"assignee": str(aaron.pk)}) == {"Aaron's"}
    assert titles({"assignee": "none"}) == {"Unassigned"}
    assert titles({"assignee": "me", "claimable": "true"}) == {"Agent's", "Lapsed"}
    assert client.get(reverse("task-list"), {"assignee": "bob"}).status_code == 400
    row = client.get(reverse("task-detail", args=[lapsed.pk])).data
    assert row["claimed_by"] is None and row["claim_expires_at"] is None
    row = client.get(reverse("task-detail", args=[held.pk])).data
    assert row["claimed_by"] == aaron.pk
    assert mine.pk in {r["id"] for r in client.get(reverse("task-list")).data}


@pytest.mark.django_db
def test_deleting_an_agent_unassigns_its_tasks(aaron, coder):
    agent, _raw = coder
    task = _task(aaron, assignee=agent, claimed_by=agent,
                 claim_expires_at=timezone.now() + timedelta(minutes=5))

    agent.delete()

    task.refresh_from_db()
    assert task.assignee is None
    assert task.claimed_by is None


# ── Claims ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_claim_renew_and_conflict(aaron, coder):
    agent, raw = coder
    other, other_raw = create_agent(parent=aaron, name="Reviewer")
    task = _task(aaron, assignee=agent)
    url = reverse("task-claim", args=[task.pk])

    first = _agent_api(raw).post(url, {"lease_seconds": 600}, format="json")
    assert first.status_code == 200
    assert first.data["claimed_by"] == agent.pk
    assert first.data["claimed_by_name"] == "Coder"

    conflict = _agent_api(other_raw).post(url, format="json")
    assert conflict.status_code == 409
    assert conflict.data["claimed_by"] == agent.pk
    assert "Coder" in conflict.data["detail"]

    renewed = _agent_api(raw).post(url, {"lease_seconds": 1200}, format="json")
    assert renewed.status_code == 200
    task.refresh_from_db()
    assert task.claim_expires_at > timezone.now() + timedelta(seconds=1100)
    # A renewal isn't a new claim in the history.
    assert TaskActivity.objects.filter(task=task, action=TaskActivity.CLAIMED).count() == 1
    assert TaskActivity.objects.get(task=task, action=TaskActivity.CLAIMED).actor == agent


@pytest.mark.django_db
def test_a_lapsed_claim_can_be_taken(aaron, coder):
    agent, raw = coder
    task = _task(aaron, claimed_by=aaron, claim_expires_at=timezone.now() - timedelta(seconds=1))

    response = _agent_api(raw).post(reverse("task-claim", args=[task.pk]), format="json")

    assert response.status_code == 200
    assert response.data["claimed_by"] == agent.pk


@pytest.mark.django_db
def test_lease_is_kept_within_bounds(aaron, coder):
    _agent, raw = coder
    task = _task(aaron)
    url = reverse("task-claim", args=[task.pk])
    client = _agent_api(raw)

    client.post(url, {"lease_seconds": 1}, format="json")
    task.refresh_from_db()
    assert task.claim_expires_at <= timezone.now() + MIN_LEASE

    client.post(url, {"lease_seconds": 10**9}, format="json")
    task.refresh_from_db()
    assert task.claim_expires_at <= timezone.now() + MAX_LEASE
    assert task.claim_expires_at > timezone.now() + MAX_LEASE - timedelta(minutes=1)

    assert client.post(url, {"lease_seconds": "soon"}, format="json").status_code == 400
    assert client.post(url, {"lease_seconds": True}, format="json").status_code == 400


@pytest.mark.django_db
def test_release(aaron, coder):
    agent, raw = coder
    other, other_raw = create_agent(parent=aaron, name="Reviewer")
    task = _task(aaron)
    _agent_api(raw).post(reverse("task-claim", args=[task.pk]), format="json")
    release = reverse("task-release", args=[task.pk])

    # Another agent can't take it away.
    assert _agent_api(other_raw).post(release).status_code == 409
    # A person can.
    response = _human_api(aaron).post(release)
    assert response.status_code == 200
    assert response.data["claimed_by"] is None
    task.refresh_from_db()
    assert task.claimed_by is None and task.claim_expires_at is None
    assert TaskActivity.objects.get(task=task, action=TaskActivity.RELEASED).actor == aaron
    # Releasing an unclaimed task is a no-op.
    assert _agent_api(raw).post(release).status_code == 200
    assert TaskActivity.objects.filter(task=task, action=TaskActivity.RELEASED).count() == 1


@pytest.mark.django_db
def test_finishing_a_task_releases_its_claim(aaron, coder):
    _agent, raw = coder
    task = _task(aaron)
    client = _agent_api(raw)
    client.post(reverse("task-claim", args=[task.pk]), format="json")

    response = client.post(reverse("task-move", args=[task.pk]), {"new_status": "done"}, format="json")

    assert response.status_code == 200
    assert response.data["claimed_by"] is None
    task.refresh_from_db()
    assert task.claimed_by is None


@pytest.mark.django_db
def test_a_viewer_cannot_claim(aaron):
    shared = create_shared_workspace(user=aaron, name="Shared")
    viewer = User.objects.create_user()
    Membership.objects.create(workspace=shared, user=viewer, role=Membership.ROLE_VIEWER)
    task = _task(aaron, workspace=shared)

    response = _human_api(viewer, shared).post(reverse("task-claim", args=[task.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_claim_next_hands_out_each_task_once(aaron, coder):
    agent, raw = coder
    other_agent, _ = create_agent(parent=aaron, name="Other")
    _task(aaron, "Done already", status="done", assignee=agent)
    _task(aaron, "Archived", assignee=agent, is_archived=True)
    _task(aaron, "Someone else's", assignee=other_agent)
    _task(aaron, "Held by Aaron", assignee=agent, claimed_by=aaron,
          claim_expires_at=timezone.now() + timedelta(minutes=5))
    second = _task(aaron, "Second", assignee=agent, order=2)
    first = _task(aaron, "First", assignee=agent, order=1)
    client = _agent_api(raw)
    url = reverse("task-claim-next")

    a = client.post(url, {"lease_seconds": 300}, format="json")
    b = client.post(url, format="json")
    c = client.post(url, format="json")

    assert (a.status_code, a.data["id"]) == (200, first.pk)
    assert (b.status_code, b.data["id"]) == (200, second.pk)
    assert c.status_code == 204
    first.refresh_from_db()
    assert first.claimed_by == agent


@pytest.mark.django_db
def test_claim_next_follows_the_workspace_header(aaron, coder):
    agent, raw = coder
    shared = create_shared_workspace(user=aaron, name="Shared")
    _task(aaron, "Personal", assignee=agent)
    shared_task = _task(aaron, "Shared", assignee=agent, workspace=shared)

    response = _agent_api(raw, shared).post(reverse("task-claim-next"), format="json")

    assert response.data["id"] == shared_task.pk
