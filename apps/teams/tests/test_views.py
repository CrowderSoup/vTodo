import pytest
from django.core import mail
from django.urls import reverse

from apps.emailauth.models import EmailIdentity
from apps.teams.models import Team, TeamInvite, TeamMembership
from apps.teams.views import INVITE_RATE_LIMIT
from apps.users.models import User


@pytest.fixture
def logged_in_client(client, db):
    user = User.objects.create_user()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_team_create_makes_owner_membership(logged_in_client):
    client, user = logged_in_client
    response = client.post(reverse("teams:create"), {"name": "Rocketry"})
    assert response.status_code == 302
    team = Team.objects.get(name="Rocketry")
    membership = TeamMembership.objects.get(team=team, user=user)
    assert membership.role == TeamMembership.ROLE_OWNER


@pytest.mark.django_db
def test_invite_create_sends_email_and_populates_outbox(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)

    response = client.post(reverse("teams:invite-create", args=[team.pk]), {"email": "a@example.com"})

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    invite = TeamInvite.objects.get(team=team, email="a@example.com")
    assert invite.token in mail.outbox[0].body


@pytest.mark.django_db
def test_invite_create_requires_owner(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_MEMBER)

    response = client.post(reverse("teams:invite-create", args=[team.pk]), {"email": "a@example.com"})

    assert response.status_code == 404
    assert not TeamInvite.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_invite_create_rate_limited(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)

    for _ in range(INVITE_RATE_LIMIT):
        client.post(reverse("teams:invite-create", args=[team.pk]), {"email": "a@example.com"})

    mail.outbox.clear()
    client.post(reverse("teams:invite-create", args=[team.pk]), {"email": "a@example.com"})
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_invite_accept_creates_membership(logged_in_client):
    client, user = logged_in_client
    EmailIdentity.objects.create(user=user, email="a@example.com", verified=True)
    owner = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=owner, role=TeamMembership.ROLE_OWNER)
    invite = TeamInvite.generate(team, "a@example.com", owner)

    response = client.post(reverse("teams:invite-accept", args=[invite.token]))

    assert response.status_code == 302
    assert TeamMembership.objects.filter(team=team, user=user).exists()
    invite.refresh_from_db()
    assert invite.accepted_at is not None


@pytest.mark.django_db
def test_invite_accept_rejects_email_mismatch(logged_in_client):
    client, user = logged_in_client
    owner = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=owner, role=TeamMembership.ROLE_OWNER)
    invite = TeamInvite.generate(team, "a@example.com", owner)

    response = client.post(reverse("teams:invite-accept", args=[invite.token]))

    assert response.status_code == 302
    assert not TeamMembership.objects.filter(team=team, user=user).exists()
    invite.refresh_from_db()
    assert invite.accepted_at is None


@pytest.mark.django_db
def test_invite_accept_get_flags_email_mismatch(logged_in_client):
    client, user = logged_in_client
    owner = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=owner, role=TeamMembership.ROLE_OWNER)
    invite = TeamInvite.generate(team, "a@example.com", owner)

    response = client.get(reverse("teams:invite-accept", args=[invite.token]))

    assert response.context["email_mismatch"] is True


@pytest.mark.django_db
def test_invite_accept_rejects_expired(logged_in_client):
    from django.utils import timezone

    client, user = logged_in_client
    owner = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=owner, role=TeamMembership.ROLE_OWNER)
    invite = TeamInvite.generate(team, "a@example.com", owner)
    invite.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    invite.save()

    client.post(reverse("teams:invite-accept", args=[invite.token]))

    assert not TeamMembership.objects.filter(team=team, user=user).exists()


@pytest.mark.django_db
def test_member_remove_requires_owner(logged_in_client):
    client, user = logged_in_client
    other = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_MEMBER)
    TeamMembership.objects.create(team=team, user=other, role=TeamMembership.ROLE_OWNER)

    response = client.post(reverse("teams:member-remove", args=[team.pk, other.pk]))

    assert response.status_code == 404
    assert TeamMembership.objects.filter(team=team, user=other).exists()


@pytest.mark.django_db
def test_member_remove_blocks_removing_last_owner(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)

    response = client.post(reverse("teams:member-remove", args=[team.pk, user.pk]))

    assert response.status_code == 302
    assert TeamMembership.objects.filter(team=team, user=user).exists()


@pytest.mark.django_db
def test_leave_blocks_sole_owner(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)

    response = client.post(reverse("teams:leave", args=[team.pk]))

    assert response.status_code == 302
    assert TeamMembership.objects.filter(team=team, user=user).exists()


@pytest.mark.django_db
def test_leave_allows_member(logged_in_client):
    client, user = logged_in_client
    owner = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=owner, role=TeamMembership.ROLE_OWNER)
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_MEMBER)

    response = client.post(reverse("teams:leave", args=[team.pk]))

    assert response.status_code == 302
    assert not TeamMembership.objects.filter(team=team, user=user).exists()


@pytest.mark.django_db
def test_delete_requires_owner(logged_in_client):
    client, user = logged_in_client
    other = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_MEMBER)
    TeamMembership.objects.create(team=team, user=other, role=TeamMembership.ROLE_OWNER)

    response = client.post(reverse("teams:delete", args=[team.pk]))

    assert response.status_code == 404
    assert Team.objects.filter(pk=team.pk).exists()


@pytest.mark.django_db
def test_delete_removes_team_and_nulls_task_team(logged_in_client):
    from apps.tasks.models import Task

    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user, role=TeamMembership.ROLE_OWNER)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")

    response = client.post(reverse("teams:delete", args=[team.pk]))

    assert response.status_code == 302
    assert not Team.objects.filter(pk=team.pk).exists()
    task.refresh_from_db()
    assert task.team_id is None
