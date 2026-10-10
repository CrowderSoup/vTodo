"""Board search box behavior that only shows up in a real browser: htmx
re-renders the filter bar around the box while the user is typing in it."""
import pytest
from django.urls import reverse
from playwright.sync_api import expect

from apps.boards.models import Board
from apps.tasks.models import Task
from apps.users.models import User


@pytest.fixture
def board_page(page, login, transactional_db):
    user = User.objects.create_user()
    Task.objects.create(user=user, title="Release notes", status="todo")
    Task.objects.create(user=user, title="Groceries", status="todo")
    login(user)

    def open_board():
        page.goto(reverse("boards:board"))
        page.wait_for_function("window.htmx !== undefined")
        return page

    open_board.user = user
    return open_board


def cards(page):
    return page.locator("article.task-card .task-title-btn")


def search_selection(page):
    return page.evaluate("""() => {
        const input = document.getElementById("board-filter-q");
        return {
            focused: document.activeElement === input,
            value: input.value,
            start: input.selectionStart,
            end: input.selectionEnd,
        };
    }""")


def filter_response(page):
    return page.expect_response(lambda r: r.url.endswith(reverse("boards:board-filter")))


def test_search_keeps_typing_focus_and_cursor_through_refresh(board_page):
    page = board_page()
    search = page.locator("#board-filter-q")
    # Note the box's state when the first refresh has swapped in, before any
    # later request can run.
    page.evaluate("""() => document.addEventListener("htmx:afterSettle", () => {
        if (!window.searchAfterFirstSwap) {
            const input = document.getElementById("board-filter-q");
            window.searchAfterFirstSwap = {
                focused: document.activeElement === input,
                value: input.value,
                start: input.selectionStart,
                end: input.selectionEnd,
            };
        }
    })""")
    held = []

    def hold_first(route):
        if held:
            route.fallback()
        else:
            held.append(route)

    page.route(f"**{reverse('boards:board-filter')}", hold_first)

    search.click()
    search.press_sequentially("rel", delay=30)
    while not held:
        page.wait_for_timeout(20)

    # Keep typing while that request is in flight, then let its response
    # land well inside the 300ms debounce, so it isn't replaced by the next.
    page.keyboard.type("ese")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    held[0].continue_()

    page.wait_for_function("window.searchAfterFirstSwap")
    assert page.evaluate("window.searchAfterFirstSwap") == {
        "focused": True, "value": "relese", "start": 4, "end": 4,
    }

    # The debounced request for "relese" matches nothing. Typing on without
    # clicking only lands in the box if it still has focus.
    expect(cards(page)).to_have_count(0)
    with filter_response(page):
        page.keyboard.type("a")
    expect(cards(page)).to_have_text(["Release notes"])
    assert search_selection(page) == {"focused": True, "value": "release", "start": 5, "end": 5}


def test_clear_filters_empties_search(board_page):
    page = board_page()
    search = page.locator("#board-filter-q")
    with filter_response(page):
        search.fill("release")
    expect(cards(page)).to_have_text(["Release notes"])

    page.locator(".filter-bar-trigger").click()
    page.get_by_role("button", name="Clear filters").click()

    expect(search).to_have_value("")
    expect(cards(page)).to_have_count(2)


def test_loading_saved_view_fills_search(board_page):
    open_board = board_page
    board = Board.objects.get(user=open_board.user)
    board.saved_filters.create(name="Release work", filter_config={"q": "release"})
    page = open_board()
    search = page.locator("#board-filter-q")
    expect(search).to_have_value("")

    page.locator(".filter-bar-trigger").click()
    page.locator("#saved-filter-select").select_option(label="Release work")

    expect(search).to_have_value("release")
    expect(cards(page)).to_have_text(["Release notes"])
