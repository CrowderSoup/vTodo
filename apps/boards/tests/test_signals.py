import pytest

from apps.boards.models import Board, Column
from apps.users.models import User


@pytest.mark.django_db
def test_board_created_on_new_user():
    user = User.objects.create_user()
    assert Board.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_four_default_columns_created():
    user = User.objects.create_user()
    board = user.board
    assert board.columns.count() == 4


@pytest.mark.django_db
def test_default_column_filter_configs():
    user = User.objects.create_user()
    slugs = set()
    for col in user.board.columns.all():
        statuses = col.filter_config.get("statuses", [])
        slugs.update(statuses)
    assert slugs == {"backlog", "todo", "in_progress", "done"}


@pytest.mark.django_db
def test_default_column_order():
    user = User.objects.create_user()
    columns = list(user.board.columns.order_by("order"))
    slugs = [col.filter_config.get("statuses", [None])[0] for col in columns]
    assert slugs == ["backlog", "todo", "in_progress", "done"]


@pytest.mark.django_db
def test_board_not_created_on_update():
    user = User.objects.create_user()
    initial_count = Board.objects.filter(user=user).count()
    user.display_name = "Updated"
    user.save()
    assert Board.objects.filter(user=user).count() == initial_count
