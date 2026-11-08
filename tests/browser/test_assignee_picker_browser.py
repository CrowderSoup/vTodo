"""The assignee picker in the task panel: search, keyboard, clear, save."""
import pytest
from django.urls import reverse
from playwright.sync_api import expect

from apps.tasks.models import Task
from apps.users.agents import create_agent
from apps.users.models import User


@pytest.fixture
def panel(page, login, transactional_db):
    user = User.objects.create_user(display_name="Aaron")
    agent, _raw = create_agent(parent=user, name="Coder")
    create_agent(parent=user, name="Reviewer")
    task = Task.objects.create(user=user, title="Ship it", status="todo")
    login(user)
    page.goto(reverse("boards:board"))
    page.wait_for_function("window.htmx !== undefined")
    page.locator("article.task-card .task-title-btn", has_text="Ship it").click()
    page.get_by_role("button", name="Edit task").click()
    picker = page.locator("#task-panel-assignee-field")
    expect(picker).to_be_visible()
    return {"page": page, "task": task, "agent": agent, "picker": picker}


def save(page):
    with page.expect_response(lambda r: "/panel/update/" in r.url):
        page.get_by_role("button", name="Save changes").click()


def test_search_and_pick_with_the_keyboard(panel):
    page, picker, task = panel["page"], panel["picker"], panel["task"]

    picker.click()
    options = page.locator("#task-panel-assignee-listbox [role=option]")
    expect(options).to_have_count(3)
    expect(options.first).to_contain_text("Aaron (you)")

    picker.fill("cod")
    expect(options).to_have_count(1)
    expect(options.first).to_contain_text("Coder")
    expect(options.first).to_contain_text("agent")
    picker.press("Enter")

    chip = page.locator("[data-assignee-picker] .tag-chip")
    expect(chip).to_contain_text("Coder")
    expect(page.locator("#task-panel-assignee")).to_have_value(str(panel["agent"].pk))
    # Enter picked the option. It didn't submit the form.
    task.refresh_from_db()
    assert task.assignee is None

    save(page)
    task.refresh_from_db()
    assert task.assignee == panel["agent"]


def test_no_match_message_and_clearing(panel):
    page, picker, task = panel["page"], panel["picker"], panel["task"]
    task.assignee = panel["agent"]
    task.save()
    page.get_by_role("button", name="Cancel").click()
    page.get_by_role("button", name="Edit task").click()
    expect(page.locator("[data-assignee-picker] .tag-chip")).to_contain_text("Coder")

    picker.fill("zzz")
    expect(page.locator("#task-panel-assignee-listbox")).to_contain_text("No one matches")

    page.get_by_role("button", name="Unassign Coder").click()
    expect(page.locator("#task-panel-assignee")).to_have_value("")
    save(page)
    task.refresh_from_db()
    assert task.assignee is None
