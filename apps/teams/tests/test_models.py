import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.teams.models import Team, TeamInvite, TeamMembership
from apps.users.models import User


@pytest.mark.django_db
def test_team_membership_unique_together():
    team = Team.objects.create(name="Rocketry")
    user = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=user)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TeamMembership.objects.create(team=team, user=user)


@pytest.mark.django_db
def test_invite_generate_sets_token_and_expiry():
    team = Team.objects.create(name="Rocketry")
    inviter = User.objects.create_user()
    invite = TeamInvite.generate(team, "a@example.com", inviter)
    assert invite.token
    assert invite.expires_at > timezone.now()
    assert invite.is_valid is True


@pytest.mark.django_db
def test_invite_invalid_once_accepted():
    team = Team.objects.create(name="Rocketry")
    inviter = User.objects.create_user()
    invite = TeamInvite.generate(team, "a@example.com", inviter)
    invite.accepted_at = timezone.now()
    invite.save()
    assert invite.is_valid is False


@pytest.mark.django_db
def test_invite_invalid_once_expired():
    team = Team.objects.create(name="Rocketry")
    inviter = User.objects.create_user()
    invite = TeamInvite.generate(team, "a@example.com", inviter)
    invite.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    invite.save()
    assert invite.is_valid is False
