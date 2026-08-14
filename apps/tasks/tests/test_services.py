import pytest

from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus
from apps.tasks.services import provision_statuses
from apps.teams.models import Team
from apps.users.models import User


@pytest.mark.django_db
def test_provision_statuses_seeds_defaults_without_copy_source():
    user = User.objects.create_user()
    TaskStatus.objects.filter(user=user).delete()

    provision_statuses(user=user)

    slugs = set(TaskStatus.objects.filter(user=user).values_list("slug", flat=True))
    assert slugs == {slug for _, slug, _, _ in DEFAULT_STATUS_DEFS}


@pytest.mark.django_db
def test_provision_statuses_copies_from_user():
    """A new team's statuses mirror the creator's personal ones (name/order/color/
    is_done), not a hardcoded default -- so a team never starts out diverged from
    how its owner already works."""
    owner = User.objects.create_user()
    personal = TaskStatus.objects.filter(user=owner, team__isnull=True).order_by("order")
    personal.filter(slug="in_progress").update(color="#ff0000")

    team = Team.objects.create(name="Rocketry")
    provision_statuses(team=team, copy_from_user=owner)

    team_statuses = list(TaskStatus.objects.filter(team=team).order_by("order"))
    personal_statuses = list(personal)
    assert [(s.name, s.slug, s.order, s.is_done, s.color) for s in team_statuses] == [
        (s.name, s.slug, s.order, s.is_done, s.color) for s in personal_statuses
    ]


@pytest.mark.django_db
def test_provision_statuses_copy_source_ignores_teammates_other_teams():
    """Only the copy source's *personal* statuses are copied, never any team's."""
    owner = User.objects.create_user()
    other_team = Team.objects.create(name="Other")
    TaskStatus.objects.create(team=other_team, name="Weird", slug="weird", order=0)

    team = Team.objects.create(name="Rocketry")
    provision_statuses(team=team, copy_from_user=owner)

    assert not TaskStatus.objects.filter(team=team, slug="weird").exists()
