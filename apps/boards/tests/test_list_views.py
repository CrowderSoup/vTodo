from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.boards.models import Board
from apps.tasks import lifecycle
from apps.tasks.models import Task
from apps.users.models import User
from apps.workspaces.access import SESSION_KEY
from apps.workspaces.models import Membership
from apps.workspaces.services import create_shared_workspace

LIST_URL = "http://testserver/list/"
FROM_LIST = {"HTTP_HX_REQUEST": "true", "HTTP_HX_CURRENT_URL": LIST_URL}


@pytest.fixture
def user(db):
    return User.objects.create_user()


@pytest.fixture
def board(user):
    return Board.objects.get(user=user)


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def _task(user, title, **fields):
    task = Task.objects.create(user=user, title=title, status=fields.pop("status", "todo"), **fields)
    lifecycle.start(task)
    return task


def _done(user, title, **fields):
    return _task(user, title, status="done", **fields)


def _rows(response):
    return [[task.title for task in group["tasks"]] for group in response.context["groups"]]


def _set_filter(client, board, config):
    session = client.session
    session["board_filter"] = {str(board.pk): config}
    session.save()


@pytest.mark.django_db
def test_list_shows_open_tasks_then_done_ones(logged_in, user):
    _done(user, "Finished", order=0)
    _task(user, "Second", order=2)
    _task(user, "First", order=1)

    response = logged_in.get(reverse("list:list"))

    assert response.status_code == 200
    assert _rows(response) == [["First", "Second", "Finished"]]
    html = response.content.decode()
    assert 'class="task-row task-row--done"' in html
    assert "Show done" in html
    assert 'href="/list/"' in html


@pytest.mark.django_db
def test_list_leaves_out_archived_tasks(logged_in, user):
    _task(user, "Kept")
    _task(user, "Archived", is_archived=True)
    assert _rows(logged_in.get(reverse("list:list"))) == [["Kept"]]


@pytest.mark.django_db
def test_hiding_done_tasks_from_the_list(logged_in, user, board):
    _task(user, "Open")
    _done(user, "Finished")

    # The checkbox is unticked: only the filter form's hidden "0" is sent.
    response = logged_in.post(
        reverse("boards:board-filter"), {"board_id": board.pk, "show_done": "0"}, **FROM_LIST,
    )

    assert response.status_code == 200
    assert _rows(response) == [["Open"]]
    assert logged_in.session["board_filter"][str(board.pk)]["show_done"] is False
    assert response.context["active_filter_count"] == 1
    html = response.content.decode()
    assert 'id="board-filter" class="nav-filter-slot" hx-swap-oob="true"' in html
    assert "1 of 2 hidden" in html

    response = logged_in.post(
        reverse("boards:board-filter"), {"board_id": board.pk, "show_done": ["0", "1"]}, **FROM_LIST,
    )
    assert _rows(response) == [["Open", "Finished"]]


@pytest.mark.django_db
def test_board_shows_done_tasks_even_when_the_list_hides_them(logged_in, user, board):
    _done(user, "Finished")
    _set_filter(logged_in, board, {"show_done": False})

    response = logged_in.get(reverse("boards:board"))

    assert response.context["visible_task_count"] == 1
    assert response.context["active_filter_count"] == 0


@pytest.mark.django_db
def test_changing_sort_and_group(logged_in, user, board):
    today = timezone.localdate()
    _task(user, "Later", due_date=today + timedelta(days=3), tags=["home"])
    _task(user, "Soon", due_date=today, tags=["home", "work"])
    _task(user, "Bare")

    response = logged_in.post(
        reverse("list:layout"), {"board_id": board.pk, "sort": "due", "group": "tag"}, **FROM_LIST,
    )

    assert response.status_code == 200
    assert [g["label"] for g in response.context["groups"]] == ["home", "work", "Untagged"]
    assert _rows(response) == [["Soon", "Later"], ["Soon"], ["Bare"]]
    stored = logged_in.session["board_filter"][str(board.pk)]
    assert (stored["sort"], stored["sort_dir"], stored["group"]) == ("due", "asc", "tag")

    response = logged_in.post(
        reverse("list:layout"), {"board_id": board.pk, "sort_dir": "desc"}, **FROM_LIST,
    )
    assert _rows(response) == [["Later", "Soon"], ["Soon"], ["Bare"]]
    assert 'value="asc"' in response.content.decode()  # the button now offers ascending


@pytest.mark.django_db
def test_layout_change_keeps_filters(logged_in, user, board):
    _task(user, "Home", tags=["home"])
    _task(user, "Work", tags=["work"])
    _set_filter(logged_in, board, {"tags": ["home"]})

    response = logged_in.post(
        reverse("list:layout"), {"board_id": board.pk, "group": "status"}, **FROM_LIST,
    )

    assert _rows(response) == [["Home"]]
    assert response.context["active_filter"]["tags"] == ["home"]


@pytest.mark.django_db
def test_collapsing_a_group(logged_in, user, board):
    _task(user, "Todo")
    _set_filter(logged_in, board, {"group": "status"})

    response = logged_in.post(
        reverse("list:group-toggle"), {"board_id": board.pk, "key": "status:todo"}, **FROM_LIST,
    )

    group = response.context["groups"][0]
    assert group["collapsed"] is True
    assert 'aria-expanded="false"' in response.content.decode()
    assert "task-row" not in response.content.decode()

    response = logged_in.post(
        reverse("list:group-toggle"), {"board_id": board.pk, "key": "status:todo"}, **FROM_LIST,
    )
    assert response.context["groups"][0]["collapsed"] is False


@pytest.mark.django_db
def test_group_toggle_rejects_junk(logged_in, board):
    response = logged_in.post(reverse("list:group-toggle"), {"board_id": board.pk, "key": "nope"})
    assert response.status_code == 404


@pytest.mark.django_db
def test_completing_a_task_from_the_list_redraws_the_list(logged_in, user):
    task = _task(user, "Do it")
    _task(user, "Other")

    response = logged_in.post(reverse("boards:task-move", args=[task.pk]), {"new_status": "done"}, **FROM_LIST)

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.completed_at is not None
    assert _rows(response) == [["Other", "Do it"]]
    html = response.content.decode()
    assert 'id="task-list-content" class="task-list-view" hx-swap-oob="innerHTML"' in html
    assert "board-column" not in html

    response = logged_in.post(reverse("boards:task-move", args=[task.pk]), {"new_status": "todo"}, **FROM_LIST)
    task.refresh_from_db()
    assert task.completed_at is None


@pytest.mark.django_db
def test_completing_a_recurring_task_from_the_list_shows_the_next_one(logged_in, user):
    task = _task(user, "Water plants", recurrence_days=3, due_date=timezone.localdate())

    response = logged_in.post(reverse("boards:task-move", args=[task.pk]), {"new_status": "done"}, **FROM_LIST)

    assert _rows(response) == [["Water plants", "Water plants"]]
    first, second = response.context["groups"][0]["tasks"]
    assert first.completed_at is None and second.completed_at is not None


@pytest.mark.django_db
def test_panel_save_from_the_list(logged_in, user):
    task = _task(user, "Old title")

    response = logged_in.post(
        reverse("boards:task-panel-update", args=[task.pk]),
        {"title": "New title", "notes": "", "due_date": "", "tags": "home"},
        **FROM_LIST,
    )

    assert response.status_code == 200
    assert _rows(response) == [["New title"]]
    html = response.content.decode()
    assert 'hx-swap-oob="innerHTML"' in html
    assert "New title" in html


@pytest.mark.django_db
def test_status_change_from_the_panel_on_the_list(logged_in, user):
    task = _task(user, "Task")

    response = logged_in.post(
        reverse("boards:task-move", args=[task.pk]),
        {"new_status": "in_progress"},
        HTTP_HX_TARGET="task-panel-content",
        **FROM_LIST,
    )

    assert response.status_code == 200
    assert response.context["task"].status == "in_progress"
    assert _rows(response) == [["Task"]]


@pytest.mark.django_db
def test_deleting_from_the_list(logged_in, user):
    task = _task(user, "Gone")
    _task(user, "Stays")

    response = logged_in.post(reverse("boards:task-delete", args=[task.pk]), **FROM_LIST)

    assert response.status_code == 200
    assert not Task.objects.filter(pk=task.pk).exists()
    assert _rows(response) == [["Stays"]]


@pytest.mark.django_db
def test_creating_from_the_list(logged_in, user):
    response = logged_in.post(
        reverse("boards:task-panel-create"), {"title": "Brand new", "tags": ""}, **FROM_LIST,
    )

    assert response.status_code == 200
    assert _rows(response) == [["Brand new"]]
    assert 'hx-swap-oob="innerHTML"' in response.content.decode()


@pytest.mark.django_db
def test_list_filter_keeps_the_boards_collapsed_lanes(logged_in, user, board):
    _set_filter(logged_in, board, {"hidden_lanes": ["status:1"]})
    response = logged_in.get(reverse("list:list"))
    html = response.content.decode()
    assert '<input type="hidden" name="hidden_lanes" value="status:1">' in html
    # Collapsed lanes don't apply to the list, so they aren't an active filter here.
    assert response.context["active_filter_count"] == 0


@pytest.mark.django_db
def test_clear_filters_on_the_list_keeps_the_boards_collapsed_lanes(logged_in, user, board):
    _set_filter(logged_in, board, {"tags": ["home"], "hidden_lanes": ["status:1"]})
    html = logged_in.get(reverse("list:list")).content.decode()
    clear_form = html[:html.index("Clear filters")]
    clear_form = clear_form[clear_form.rindex("<form"):]
    assert 'name="hidden_lanes" value="status:1"' in clear_form

    response = logged_in.post(
        reverse("boards:board-filter"), {"board_id": board.pk, "hidden_lanes": ["status:1"]}, **FROM_LIST,
    )
    stored = logged_in.session["board_filter"][str(board.pk)]
    assert (stored["tags"], stored["hidden_lanes"]) == ([], ["status:1"])
    assert response.context["active_filter_count"] == 0


@pytest.mark.django_db
def test_empty_states(logged_in, user, board):
    response = logged_in.get(reverse("list:list"))
    assert "No tasks yet." in response.content.decode()

    _task(user, "Home", tags=["home"])
    _set_filter(logged_in, board, {"tags": ["work"]})
    response = logged_in.get(reverse("list:list"))
    assert "No tasks match your filters." in response.content.decode()


@pytest.mark.django_db
def test_viewers_see_the_list_without_controls(client):
    owner = User.objects.create_user()
    viewer = User.objects.create_user()
    shared = create_shared_workspace(user=owner, name="Family")
    Membership.objects.create(workspace=shared, user=viewer, role=Membership.ROLE_VIEWER)
    Task.objects.create(user=owner, workspace=shared, title="Shared task", status="todo")

    client.force_login(viewer)
    session = client.session
    session[SESSION_KEY] = shared.pk
    session.save()
    response = client.get(reverse("list:list"))

    html = response.content.decode()
    assert "Shared task" in html
    assert "Mark complete" not in html
    assert "New task" not in html


@pytest.mark.django_db
def test_list_requires_login(client):
    response = client.get(reverse("list:list"))
    assert response.status_code == 302
