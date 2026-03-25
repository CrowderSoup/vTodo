import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from apps.boards.models import Board
from apps.boards.views import _render_markdown
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
# Board columns / TaskPanelCreateView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_board_uses_lane_menu_for_add_task(logged_in_client):
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    first_column = board.columns.first()
    response = client.get(reverse("boards:board"))
    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="add-task-form"' not in content
    assert f'{reverse("boards:task-panel-create")}?column={first_column.pk}' in content


@pytest.mark.django_db
def test_board_renders_fab_for_task_creation(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("boards:board"))
    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="board-fab"' in content
    assert f'hx-get="{reverse("boards:task-panel-create")}"' in content


@pytest.mark.django_db
def test_board_includes_shared_confirm_modal(logged_in_client):
    client, _ = logged_in_client
    response = client.get(reverse("boards:board"))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id="confirm-modal"' in content
    assert 'id="confirm-modal-confirm"' in content


@pytest.mark.django_db
def test_task_panel_create_renders_without_comments_form(logged_in_client):
    client, user = logged_in_client
    first_column = user.board.columns.first()
    response = client.get(reverse("boards:task-panel-create"))
    content = response.content.decode()
    assert response.status_code == 200
    assert response.context["selected_column_id"] == first_column.pk
    assert response.context["selected_status"] == first_column.default_status(user)
    assert 'id="task-comment-form"' not in content
    assert "Create task" in content


@pytest.mark.django_db
def test_task_panel_create_uses_default_column_when_user_has_one(logged_in_client):
    client, user = logged_in_client
    default_column = user.board.columns.get(label="In Progress")
    user.default_column = default_column
    user.save(update_fields=["default_column"])

    response = client.get(reverse("boards:task-panel-create"))
    assert response.status_code == 200
    assert response.context["selected_column_id"] == default_column.pk
    assert response.context["selected_status"] == "in_progress"


@pytest.mark.django_db
def test_task_panel_create_explicit_column_overrides_default_column(logged_in_client):
    client, user = logged_in_client
    user.default_column = user.board.columns.get(label="Done")
    user.save(update_fields=["default_column"])
    explicit_column = user.board.columns.get(label="To Do")

    response = client.get(f'{reverse("boards:task-panel-create")}?column={explicit_column.pk}')
    assert response.status_code == 200
    assert response.context["selected_column_id"] == explicit_column.pk
    assert response.context["selected_status"] == "todo"


@pytest.mark.django_db
def test_task_panel_create_creates_task_and_refreshes_board(logged_in_client):
    client, user = logged_in_client
    default_column = user.board.columns.get(label="In Progress")
    user.default_column = default_column
    user.save(update_fields=["default_column"])

    response = client.post(
        reverse("boards:task-panel-create"),
        {
            "title": "Panel created task",
            "notes": "Fresh context",
            "tags": "ops, urgent",
            "due_date": "",
            "recurrence_days": "",
            "recurrence_from": "completion",
        },
    )
    content = response.content.decode()
    task = Task.objects.get(user=user, title="Panel created task")

    assert response.status_code == 200
    assert task.status == "in_progress"
    assert task.notes == "Fresh context"
    assert task.tags == ["ops", "urgent"]
    assert 'hx-swap-oob="innerHTML"' in content
    assert 'id="board-content"' in content
    assert 'id="task-comment-form"' in content


@pytest.mark.django_db
def test_task_panel_create_missing_title_returns_422(logged_in_client):
    client, user = logged_in_client
    response = client.post(reverse("boards:task-panel-create"), {"title": ""})
    content = response.content.decode()
    assert response.status_code == 422
    assert "Add a title before creating the task." in content
    assert not Task.objects.filter(user=user).exists()


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


@pytest.mark.django_db
def test_task_detail_hides_status_select(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="My task", status="todo")
    response = client.get(reverse("boards:task-detail", kwargs={"pk": task.pk}))
    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="task-status-select"' not in content


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


@pytest.mark.django_db
def test_task_panel_renders_status_select(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Panel task", status="todo")
    response = client.get(reverse("boards:task-panel", kwargs={"pk": task.pk}))
    content = response.content.decode()
    assert response.status_code == 200
    assert f'id="task-panel-status-{task.pk}"' in content
    assert 'hx-target="#task-panel-content"' in content


@pytest.mark.django_db
def test_task_move_from_panel_refreshes_panel_and_board(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Panel task", status="todo")
    response = client.post(
        reverse("boards:task-move", kwargs={"pk": task.pk}),
        {"new_status": "in_progress"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="task-panel-content",
    )
    content = response.content.decode()
    task.refresh_from_db()

    assert response.status_code == 200
    assert task.status == "in_progress"
    assert 'id="board-content"' in content
    assert 'hx-swap-oob="innerHTML"' in content
    assert f'id="task-panel-status-{task.pk}"' in content
    assert 'id="task-comment-form"' in content


@pytest.mark.django_db
def test_render_markdown_wraps_task_list_checkboxes():
    html = _render_markdown("- [x] Ship polish\n- [ ] Follow up")
    assert 'class="rendered-checkbox-line rendered-checkbox-line--checked"' in html
    assert 'class="rendered-checkbox-label">Ship polish</span>' in html
    assert 'class="rendered-checkbox-line">' in html
    assert 'class="rendered-checkbox-label">Follow up</span>' in html


@pytest.mark.django_db
def test_render_markdown_wraps_paragraph_checkboxes():
    html = _render_markdown("[ ] Share the board")
    assert html == (
        '<p class="rendered-checkbox-line">'
        '<span class="rendered-checkbox" aria-hidden="true"></span>'
        '<span class="rendered-checkbox-label">Share the board</span>'
        "</p>"
    )


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
