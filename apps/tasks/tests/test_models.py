import pytest

from apps.tasks.models import Task
from apps.users.models import User


@pytest.mark.django_db
def test_task_default_status_is_todo():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="My task")
    assert task.status == "todo"


@pytest.mark.django_db
def test_task_str():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Do the thing")
    assert str(task) == "Do the thing"


@pytest.mark.django_db
def test_task_status_transition():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Move me")
    task.status = "in_progress"
    task.save()
    task.refresh_from_db()
    assert task.status == "in_progress"


@pytest.mark.django_db
def test_task_completed_at_is_nullable():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Not done yet")
    assert task.completed_at is None


@pytest.mark.django_db
def test_task_tags_default_empty_list():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Tagged task")
    assert task.tags == []
