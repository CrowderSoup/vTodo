import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from apps.boards.models import Board
from apps.tasks.models import Task, TaskStatus
from apps.users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def user_with_board(db):
    user = User.objects.create_user()
    return user


@pytest.fixture
def logged_in_client(client, user_with_board):
    client.force_login(user_with_board)
    return client, user_with_board


# ---------------------------------------------------------------------------
# BoardView — new stat context variables
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_board_context_has_stat_keys(logged_in_client):
    """Board context includes the new stat keys added in the UI pass."""
    client, _ = logged_in_client
    response = client.get(reverse("boards:board"))
    assert response.status_code == 200
    for key in ("today", "total_task_count", "visible_task_count", "done_task_count",
                "due_today_count", "overdue_count", "active_filter_count"):
        assert key in response.context, f"missing context key: {key}"


@pytest.mark.django_db
def test_board_context_counts_with_no_tasks(logged_in_client):
    """All counts are zero when the user has no tasks."""
    client, _ = logged_in_client
    response = client.get(reverse("boards:board"))
    assert response.context["total_task_count"] == 0
    assert response.context["visible_task_count"] == 0
    assert response.context["done_task_count"] == 0
    assert response.context["due_today_count"] == 0
    assert response.context["overdue_count"] == 0
    assert response.context["active_filter_count"] == 0


@pytest.mark.django_db
def test_board_total_task_count(logged_in_client):
    """total_task_count reflects all non-archived tasks."""
    client, user = logged_in_client
    Task.objects.create(user=user, title="T1", status="todo")
    Task.objects.create(user=user, title="T2", status="todo")
    Task.objects.create(user=user, title="Archived", status="todo", is_archived=True)
    response = client.get(reverse("boards:board"))
    assert response.context["total_task_count"] == 2


@pytest.mark.django_db
def test_board_done_task_count(logged_in_client):
    """done_task_count counts tasks that have completed_at set."""
    client, user = logged_in_client
    Task.objects.create(user=user, title="Open", status="todo")
    Task.objects.create(user=user, title="Done", status="done", completed_at=timezone.now())
    response = client.get(reverse("boards:board"))
    assert response.context["done_task_count"] == 1


@pytest.mark.django_db
def test_board_due_today_count(logged_in_client):
    """due_today_count counts incomplete tasks due today."""
    client, user = logged_in_client
    today = timezone.localdate()
    Task.objects.create(user=user, title="Due today", status="todo", due_date=today)
    Task.objects.create(user=user, title="Due tomorrow", status="todo", due_date=today + timedelta(days=1))
    Task.objects.create(user=user, title="Done today", status="done", due_date=today, completed_at=timezone.now())
    response = client.get(reverse("boards:board"))
    assert response.context["due_today_count"] == 1


@pytest.mark.django_db
def test_board_overdue_count(logged_in_client):
    """overdue_count counts incomplete tasks with a past due date."""
    client, user = logged_in_client
    yesterday = timezone.localdate() - timedelta(days=1)
    Task.objects.create(user=user, title="Overdue", status="todo", due_date=yesterday)
    Task.objects.create(user=user, title="No due date", status="todo")
    Task.objects.create(user=user, title="Overdue but done", status="done", due_date=yesterday, completed_at=timezone.now())
    response = client.get(reverse("boards:board"))
    assert response.context["overdue_count"] == 1


@pytest.mark.django_db
def test_board_active_filter_count_with_tag_filter(logged_in_client):
    """active_filter_count increments for each active tag filter."""
    client, _ = logged_in_client
    session = client.session
    session["board_filter"] = {"tags": ["urgent", "bug"], "due": "", "hidden_columns": []}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["active_filter_count"] == 2


@pytest.mark.django_db
def test_board_active_filter_count_with_due_filter(logged_in_client):
    """active_filter_count increments by 1 when a due filter is set."""
    client, _ = logged_in_client
    session = client.session
    session["board_filter"] = {"tags": [], "due": "today", "hidden_columns": []}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["active_filter_count"] == 1


@pytest.mark.django_db
def test_board_active_filter_count_combined(logged_in_client):
    """active_filter_count sums tags + due + hidden_columns."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    column_pk = board.columns.first().pk
    session = client.session
    session["board_filter"] = {"tags": ["x"], "due": "overdue", "hidden_columns": [column_pk]}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["active_filter_count"] == 3


# ---------------------------------------------------------------------------
# TaskCreateView — today in task card context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_create_includes_today_in_context(logged_in_client):
    """Creating a task returns a card partial that has today in its context."""
    client, _ = logged_in_client
    response = client.post(reverse("boards:task-create"), {"title": "New task", "status": "todo"})
    assert response.status_code == 200
    assert "today" in response.context


@pytest.mark.django_db
def test_task_create_missing_title_returns_422(logged_in_client):
    """Creating a task without a title returns 422."""
    client, _ = logged_in_client
    response = client.post(reverse("boards:task-create"), {"title": "", "status": "todo"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# TaskDetailView — today in task card context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_detail_includes_today_in_context(logged_in_client):
    """Task detail partial includes today in context."""
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="My task", status="todo")
    response = client.get(reverse("boards:task-detail", kwargs={"pk": task.pk}))
    assert response.status_code == 200
    assert "today" in response.context


# ---------------------------------------------------------------------------
# TaskPanelView — today in panel context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_panel_includes_today_in_context(logged_in_client):
    """Task panel partial includes today in context."""
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Panel task", status="todo")
    response = client.get(reverse("boards:task-panel", kwargs={"pk": task.pk}))
    assert response.status_code == 200
    assert "today" in response.context


# ---------------------------------------------------------------------------
# TaskUpdateView — today in task card context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_update_includes_today_in_context(logged_in_client):
    """Updating a task returns a card partial that has today in its context."""
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Old title", status="todo")
    response = client.post(
        reverse("boards:task-update", kwargs={"pk": task.pk}),
        {"title": "New title", "notes": "", "due_date": "", "tags": ""},
    )
    assert response.status_code == 200
    assert "today" in response.context


# ---------------------------------------------------------------------------
# TaskDeleteView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_delete_returns_empty_response(logged_in_client):
    """Deleting a task returns an empty 200 response."""
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Bye", status="todo")
    response = client.post(reverse("boards:task-delete", kwargs={"pk": task.pk}))
    assert response.status_code == 200
    assert not Task.objects.filter(pk=task.pk).exists()


# ---------------------------------------------------------------------------
# Auth — unauthenticated access redirects
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_board_requires_login(client):
    """Anonymous requests to the board are redirected to login."""
    response = client.get(reverse("boards:board"))
    assert response.status_code == 302
    assert "/login" in response["Location"] or "login" in response["Location"]
