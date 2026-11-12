"""The list view in a real browser: its controls post with htmx and redraw the
list, and "Show done" posts through the filter bar's form from outside it."""
import pytest
from django.urls import reverse
from playwright.sync_api import expect

from apps.tasks import lifecycle
from apps.tasks.models import Task
from apps.users.models import User


@pytest.fixture
def list_page(page, login, transactional_db):
    user = User.objects.create_user()
    for title, tags, status in [
        ("Buy milk", ["home", "errand"], "todo"),
        ("Fix bike", ["home"], "todo"),
        ("Ship release", ["work"], "todo"),
        ("Old chore", ["home"], "done"),
    ]:
        task = Task.objects.create(user=user, title=title, tags=tags, status=status)
        lifecycle.start(task)
    login(user)
    page.goto(reverse("boards:list"))
    page.wait_for_function("window.htmx !== undefined")
    return page


def group_labels(page):
    return page.locator(".list-group-label")


def rows(page):
    return page.locator(".task-row-title")


def test_grouping_by_tag(list_page):
    page = list_page
    expect(group_labels(page)).to_have_count(0)
    expect(rows(page)).to_have_text(["Buy milk", "Fix bike", "Ship release", "Old chore"])

    page.get_by_label("Group by").select_option("tag")

    expect(group_labels(page)).to_have_text(["errand", "home", "work"])
    expect(page.locator(".list-group").nth(1).locator(".task-row-title")).to_have_text(
        ["Buy milk", "Fix bike", "Old chore"]
    )
    # The page remembers it.
    page.reload()
    expect(page.get_by_label("Group by")).to_have_value("tag")

    page.locator(".list-group-toggle", has_text="home").click()
    expect(page.locator(".list-group").nth(1)).to_have_class("list-group is-collapsed")
    expect(rows(page)).to_have_text(["Buy milk", "Ship release"])


def test_sorting_and_direction(list_page):
    page = list_page
    page.get_by_label("Sort by").select_option("title")
    expect(rows(page)).to_have_text(["Buy milk", "Fix bike", "Ship release", "Old chore"])

    page.get_by_label("Sorted ascending").click()
    expect(rows(page)).to_have_text(["Ship release", "Fix bike", "Buy milk", "Old chore"])
    expect(page.get_by_label("Sorted descending")).to_be_visible()


def test_completing_moves_the_task_to_the_bottom(list_page):
    page = list_page
    page.get_by_label("Mark “Buy milk” complete").click()

    expect(rows(page)).to_have_text(["Fix bike", "Ship release", "Buy milk", "Old chore"])
    expect(page.locator(".task-row--done .task-row-title")).to_have_text(["Buy milk", "Old chore"])


def test_show_done_toggle(list_page):
    page = list_page
    show_done = page.get_by_label("Show done")
    expect(show_done).to_be_checked()

    show_done.uncheck()
    expect(rows(page)).to_have_text(["Buy milk", "Fix bike", "Ship release"])
    expect(page.locator(".filter-count-badge")).to_have_text("1")

    page.get_by_label("Show done").check()
    expect(rows(page)).to_have_count(4)
