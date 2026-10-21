"""A board move redraws the lanes that changed and leaves the others in place."""
import pytest
from django.urls import reverse
from playwright.sync_api import expect

from apps.tasks.models import Task, TaskStatus


@pytest.fixture
def board_page(page, login, transactional_db):
    from apps.users.models import User

    user = User.objects.create_user()
    Task.objects.create(user=user, title="Release notes", status="todo")
    Task.objects.create(user=user, title="Stay put", status="in_progress")
    login(user)

    def open_board():
        page.goto(reverse("boards:board"))
        page.wait_for_function("window.htmx !== undefined")
        return page

    open_board.user = user
    return open_board


def test_mark_complete_leaves_an_unrelated_lane_in_place(board_page):
    user = board_page.user
    in_progress = TaskStatus.objects.get(user=user, slug="in_progress")
    done = TaskStatus.objects.get(user=user, slug="done")
    page = board_page()
    page.evaluate(
        "(id) => { window.untouchedLane = document.getElementById(id); }",
        f"lane-status-{in_progress.pk}",
    )

    card = page.locator("article.task-card", has_text="Release notes")
    with page.expect_response(lambda response: response.url.endswith("/move/") and response.ok):
        card.locator("[title='Mark complete']").click()

    todo = TaskStatus.objects.get(user=user, slug="todo")
    done_lane = page.locator(f"#lane-status-{done.pk}")
    expect(done_lane).to_contain_text("Release notes")
    expect(page.locator(f"#lane-status-{todo.pk}")).not_to_contain_text("Release notes")
    expect(page.get_by_role("button", name="Archive done cards (1)")).to_be_visible()
    same_node = page.evaluate(
        "(id) => window.untouchedLane === document.getElementById(id)",
        f"lane-status-{in_progress.pk}",
    )
    assert same_node
    expect(page.locator(f"#lane-status-{in_progress.pk}")).to_contain_text("Stay put")


def test_drag_to_another_lane_leaves_an_unrelated_lane_in_place(board_page):
    user = board_page.user
    backlog = TaskStatus.objects.get(user=user, slug="backlog")
    in_progress = TaskStatus.objects.get(user=user, slug="in_progress")
    page = board_page()
    page.evaluate(
        "(id) => { window.untouchedLane = document.getElementById(id); }",
        f"lane-status-{backlog.pk}",
    )

    card = page.locator("article.task-card", has_text="Release notes")
    target = page.locator(f'[id="col-tasks-status:{in_progress.pk}"]')
    with page.expect_response(lambda response: response.url.endswith("/move/") and response.ok):
        card.drag_to(target)

    expect(page.locator(f"#lane-status-{in_progress.pk}")).to_contain_text("Release notes")
    expect(page.locator(f"#lane-status-{in_progress.pk}")).to_contain_text("Stay put")
    same_node = page.evaluate(
        "(id) => window.untouchedLane === document.getElementById(id)",
        f"lane-status-{backlog.pk}",
    )
    assert same_node
