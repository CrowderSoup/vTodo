import pytest

from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus
from apps.tasks.services import provision_statuses
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
    owner = User.objects.create_user()
    personal = TaskStatus.objects.filter(user=owner).order_by("order")
    personal.filter(slug="in_progress").update(color="#ff0000")

    new_user = User.objects.create_user()
    TaskStatus.objects.filter(user=new_user).delete()
    provision_statuses(user=new_user, copy_from_user=owner)

    copied_statuses = list(TaskStatus.objects.filter(user=new_user).order_by("order"))
    personal_statuses = list(personal)
    assert [(s.name, s.slug, s.order, s.is_done, s.color) for s in copied_statuses] == [
        (s.name, s.slug, s.order, s.is_done, s.color) for s in personal_statuses
    ]
