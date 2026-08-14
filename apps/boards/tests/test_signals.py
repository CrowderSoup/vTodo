import pytest

from apps.boards.models import Board
from apps.tasks.models import TaskStatus
from apps.users.models import User


@pytest.mark.django_db
def test_board_created_on_new_user():
    user = User.objects.create_user()
    assert Board.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_no_columns_auto_created():
    """Columns are now opt-in custom lanes -- statuses alone define the board's
    default lanes, so a fresh board has none."""
    user = User.objects.create_user()
    board = Board.objects.get(user=user)
    assert board.columns.count() == 0


@pytest.mark.django_db
def test_four_default_statuses_created():
    user = User.objects.create_user()
    slugs = set(TaskStatus.objects.filter(user=user).values_list("slug", flat=True))
    assert slugs == {"backlog", "todo", "in_progress", "done"}


@pytest.mark.django_db
def test_default_status_order():
    user = User.objects.create_user()
    statuses = list(TaskStatus.objects.filter(user=user).order_by("order"))
    assert [s.slug for s in statuses] == ["backlog", "todo", "in_progress", "done"]


@pytest.mark.django_db
def test_board_not_created_on_update():
    user = User.objects.create_user()
    initial_count = Board.objects.filter(user=user).count()
    user.display_name = "Updated"
    user.save()
    assert Board.objects.filter(user=user).count() == initial_count
