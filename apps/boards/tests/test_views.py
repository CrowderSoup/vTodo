import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from apps.boards.models import Board
from apps.boards.views import _render_markdown
from apps.tasks.models import Task, TaskStatus
from apps.teams.models import Team, TeamMembership
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


def _create_team_board(team):
    """Teams created directly via Team.objects.create() (bypassing TeamCreateView)
    don't get the shared board TeamCreateView normally provisions -- tests that need
    one set it up explicitly, same as they already do for TaskStatus."""
    from apps.boards.models import Board, Column

    board = Board.objects.create(team=team, name=team.name)
    Column.objects.create(board=board, label=team.name, filter_config={}, order=0)
    return board


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
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    session = client.session
    session["board_filter"] = {str(board.pk): {"tags": ["urgent", "bug"], "due": "", "hidden_columns": []}}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["active_filter_count"] == 2


@pytest.mark.django_db
def test_board_active_filter_count_with_due_filter(logged_in_client):
    """active_filter_count increments by 1 when a due filter is set."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    session = client.session
    session["board_filter"] = {str(board.pk): {"tags": [], "due": "today", "hidden_columns": []}}
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
    session["board_filter"] = {str(board.pk): {"tags": ["x"], "due": "overdue", "hidden_columns": [column_pk]}}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["active_filter_count"] == 3


@pytest.mark.django_db
def test_board_active_filter_count_with_exclude_tag_filter(logged_in_client):
    """active_filter_count increments for each active exclude-tag filter."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    session = client.session
    session["board_filter"] = {str(board.pk): {"tags": [], "exclude_tags": ["urgent", "bug"], "due": "", "hidden_columns": []}}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["active_filter_count"] == 2


@pytest.mark.django_db
def test_board_exclude_tag_filter_hides_matching_tasks(logged_in_client):
    """Tasks with an excluded tag are hidden from the board, others remain visible."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    Task.objects.create(user=user, title="Has tag", status="todo", tags=["urgent"])
    Task.objects.create(user=user, title="No tag", status="todo", tags=["misc"])
    session = client.session
    session["board_filter"] = {str(board.pk): {"tags": [], "exclude_tags": ["urgent"], "due": "", "hidden_columns": []}}
    session.save()
    response = client.get(reverse("boards:board"))
    assert response.context["visible_task_count"] == 1


@pytest.mark.django_db
def test_board_filter_add_exclude_tag_view_adds_tag(logged_in_client):
    """Posting to board-filter-exclude-tag appends the tag to the session's exclude list."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    response = client.post(reverse("boards:board-filter-exclude-tag"), {"tag": "urgent", "board_id": board.pk})
    assert response.status_code == 200
    assert client.session["board_filter"][str(board.pk)]["exclude_tags"] == ["urgent"]


@pytest.mark.django_db
def test_board_filter_add_exclude_tag_removes_from_include(logged_in_client):
    """Excluding a tag that is currently an include-filter removes it from the include list."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    session = client.session
    session["board_filter"] = {str(board.pk): {"tags": ["urgent"], "exclude_tags": [], "due": "", "hidden_columns": []}}
    session.save()
    response = client.post(reverse("boards:board-filter-exclude-tag"), {"tag": "urgent", "board_id": board.pk})
    assert response.status_code == 200
    board_filter = client.session["board_filter"][str(board.pk)]
    assert board_filter["tags"] == []
    assert board_filter["exclude_tags"] == ["urgent"]


@pytest.mark.django_db
def test_board_filter_add_tag_removes_from_exclude(logged_in_client):
    """Including a tag that is currently an exclude-filter removes it from the exclude list."""
    client, user = logged_in_client
    board = Board.objects.get(user=user)
    session = client.session
    session["board_filter"] = {str(board.pk): {"tags": [], "exclude_tags": ["urgent"], "due": "", "hidden_columns": []}}
    session.save()
    response = client.post(reverse("boards:board-filter-add-tag"), {"tag": "urgent", "board_id": board.pk})
    assert response.status_code == 200
    board_filter = client.session["board_filter"][str(board.pk)]
    assert board_filter["tags"] == ["urgent"]
    assert board_filter["exclude_tags"] == []


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
    assert f'hx-get="{reverse("boards:task-panel-create")}?team="' in content


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
    first_column = Board.objects.get(user=user).columns.first()
    response = client.get(reverse("boards:task-panel-create"))
    content = response.content.decode()
    assert response.status_code == 200
    assert response.context["selected_column_id"] == first_column.pk
    assert response.context["selected_status"] == first_column.default_status(user)
    assert 'id="task-comment-form"' not in content
    assert "Create task" in content


@pytest.mark.django_db
def test_task_panel_create_uses_default_status_when_user_has_one(logged_in_client):
    client, user = logged_in_client
    default_status = user.task_statuses.get(slug="in_progress")
    user.default_status = default_status
    user.save(update_fields=["default_status"])
    expected_column = Board.objects.get(user=user).columns.get(label="In Progress")

    response = client.get(reverse("boards:task-panel-create"))
    assert response.status_code == 200
    assert response.context["selected_column_id"] == expected_column.pk
    assert response.context["selected_status"] == "in_progress"


@pytest.mark.django_db
def test_task_panel_create_explicit_column_overrides_default_status(logged_in_client):
    client, user = logged_in_client
    user.default_status = user.task_statuses.get(slug="done")
    user.save(update_fields=["default_status"])
    explicit_column = Board.objects.get(user=user).columns.get(label="To Do")

    response = client.get(f'{reverse("boards:task-panel-create")}?column={explicit_column.pk}')
    assert response.status_code == 200
    assert response.context["selected_column_id"] == explicit_column.pk
    assert response.context["selected_status"] == "todo"


@pytest.mark.django_db
def test_task_panel_create_creates_task_and_refreshes_board(logged_in_client):
    client, user = logged_in_client
    default_status = user.task_statuses.get(slug="in_progress")
    user.default_status = default_status
    user.save(update_fields=["default_status"])

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


@pytest.mark.django_db
def test_task_detail_for_incomplete_task_shows_complete_edit_and_delete(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="My task", status="todo")
    response = client.get(reverse("boards:task-detail", kwargs={"pk": task.pk}))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'title="Mark complete"' in content
    assert 'title="Edit task"' in content
    assert 'title="Delete task"' in content
    assert f'hx-get="{reverse("boards:task-panel-edit", kwargs={"pk": task.pk})}"' in content
    assert 'hx-target="#task-panel-content"' in content
    assert 'hx-on::after-request="openTaskPanel()"' in content
    assert content.index('title="Mark complete"') < content.index('title="Edit task"')
    assert content.index('title="Edit task"') < content.index('title="Delete task"')


@pytest.mark.django_db
def test_task_detail_for_completed_task_hides_edit_and_delete(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Done task", status="done", completed_at=timezone.now())
    response = client.get(reverse("boards:task-detail", kwargs={"pk": task.pk}))
    content = response.content.decode()

    assert response.status_code == 200
    assert 'title="Move back to active"' in content
    assert 'title="Edit task"' not in content
    assert 'title="Delete task"' not in content


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


# ---------------------------------------------------------------------------
# Teams regression — non-teammates still can't reach each other's tasks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_detail_404s_for_non_teammates_task(logged_in_client):
    """A user with no team memberships still can't reach another user's personal task."""
    client, _ = logged_in_client
    other = User.objects.create_user()
    task = Task.objects.create(user=other, title="Not yours", status="todo")
    response = client.get(reverse("boards:task-detail", kwargs={"pk": task.pk}))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# TaskAssignView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_assign_claims_unassigned_team_task(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    _create_team_board(team)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")

    response = client.post(
        reverse("boards:task-assign", kwargs={"pk": task.pk}),
        {"assignee_id": user.pk},
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.assignee_id == user.pk
    assert task.activity.count() == 1


@pytest.mark.django_db
def test_task_assign_rejects_non_member(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    outsider = User.objects.create_user()
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")

    response = client.post(
        reverse("boards:task-assign", kwargs={"pk": task.pk}),
        {"assignee_id": outsider.pk},
    )

    assert response.status_code == 422
    task.refresh_from_db()
    assert task.assignee_id is None


@pytest.mark.django_db
def test_task_assign_rejects_personal_task(logged_in_client):
    client, user = logged_in_client
    task = Task.objects.create(user=user, title="Personal task", status="todo")

    response = client.post(
        reverse("boards:task-assign", kwargs={"pk": task.pk}),
        {"assignee_id": user.pk},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Board & Column team-scoping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_team_board_shows_teammates_tasks(logged_in_client):
    """A team's shared board shows every member's tasks on that team, not just the
    viewer's own."""
    client, user = logged_in_client
    other = User.objects.create_user()
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=team, user=other)
    _create_team_board(team)
    team_task = Task.objects.create(user=other, team=team, title="Team task", status="todo")

    response = client.get(reverse("boards:board-team", args=[team.pk]))
    all_tasks = [t for _, tasks, _ in response.context["columns_with_tasks"] for t in tasks]

    assert team_task in all_tasks


@pytest.mark.django_db
def test_team_board_excludes_other_teams_tasks(logged_in_client):
    """Board isolation: a team's board never shows another team's tasks, even for a
    user who belongs to both teams."""
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    other_team = Team.objects.create(name="Other")
    outsider = User.objects.create_user()
    TeamMembership.objects.create(team=team, user=user)
    TeamMembership.objects.create(team=other_team, user=outsider)
    _create_team_board(team)
    _create_team_board(other_team)
    other_team_task = Task.objects.create(user=outsider, team=other_team, title="Other team task", status="todo")

    response = client.get(reverse("boards:board-team", args=[team.pk]))
    all_tasks = [t for _, tasks, _ in response.context["columns_with_tasks"] for t in tasks]
    assert other_team_task not in all_tasks


@pytest.mark.django_db
def test_team_board_404s_for_non_member(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    _create_team_board(team)

    response = client.get(reverse("boards:board-team", args=[team.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_task_create_with_team_succeeds_for_member(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    _create_team_board(team)

    response = client.post(reverse("boards:task-create"), {"title": "Team task", "team": team.pk})

    assert response.status_code == 200
    task = Task.objects.get(title="Team task")
    assert task.team_id == team.pk


@pytest.mark.django_db
def test_task_create_with_team_rejects_non_member(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")

    response = client.post(reverse("boards:task-create"), {"title": "Team task", "team": team.pk})

    assert response.status_code == 422
    assert not Task.objects.filter(title="Team task").exists()


@pytest.mark.django_db
def test_task_panel_renders_assignee_select_and_activity_for_team_task(logged_in_client):
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    _create_team_board(team)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")
    client.post(reverse("boards:task-assign", kwargs={"pk": task.pk}), {"assignee_id": user.pk})

    response = client.get(reverse("boards:task-panel", kwargs={"pk": task.pk}))

    assert response.status_code == 200
    assert b"Assignee" in response.content
    assert b"Activity" in response.content


@pytest.mark.django_db
def test_task_panel_create_has_no_team_select(logged_in_client):
    """The team is implied by which board the create panel was opened from now
    (via the hidden 'team' field), not a user-facing dropdown."""
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    _create_team_board(team)

    response = client.get(reverse("boards:task-panel-create"), {"team": team.pk})

    assert response.status_code == 200
    assert b'id="task-panel-create-team"' not in response.content
    assert response.context["selected_team_id"] == team.pk


@pytest.mark.django_db
def test_task_panel_create_preselects_team_from_board(logged_in_client):
    """Opening the create panel from a team board's "Add task" link (which now
    carries ?team=<board's team id>) preselects that team instead of falling back
    to personal."""
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    team_board = _create_team_board(team)
    column = team_board.columns.first()

    response = client.get(
        reverse("boards:task-panel-create"), {"column": column.pk, "team": team.pk}
    )
    assert response.context["selected_team_id"] == team.pk


@pytest.mark.django_db
def test_team_board_mark_complete_uses_the_teams_own_done_slug(logged_in_client):
    """A team whose "done" status has a different slug than the personal board's
    "done" status must not have its quick-complete button wired to the wrong slug —
    that would 422 against the task's own team and silently no-op in the UI."""
    client, user = logged_in_client
    team = Team.objects.create(name="Rocketry")
    TeamMembership.objects.create(team=team, user=user)
    TaskStatus.objects.create(team=team, name="Todo", slug="todo", is_done=False, order=0)
    TaskStatus.objects.create(team=team, name="Shipped", slug="shipped", is_done=True, order=1)
    _create_team_board(team)
    task = Task.objects.create(user=user, team=team, title="Team task", status="todo")

    response = client.get(reverse("boards:board-team", args=[team.pk]))

    assert response.status_code == 200
    all_tasks = [t for _, tasks, _ in response.context["columns_with_tasks"] for t in tasks]
    assert all_tasks[0].done_slug == "shipped"
