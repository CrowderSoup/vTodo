"""Fixtures for browser tests: a headless Chromium driving Django's live_server.

Every test in this directory is marked `browser`. Where Chromium isn't
installed they skip, unless VTODO_REQUIRE_BROWSER=1 is set (for the offline
test sandbox, so a missing browser fails loudly instead of passing quietly).
Run only these with `pytest -m browser`, or leave them out with
`pytest -m "not browser"`.

The page loads htmx from unpkg, but tests must run with no network. The
browser context serves htmx from a copy in vendor/ and aborts every other
request that isn't to the live server (stylesheets, EasyMDE). Static files
come straight from the source tree, so a stale `collectstatic` output in
staticfiles/ can't shadow them.

Playwright's sync API runs an event loop on this thread for as long as it is
started. pytest-playwright keeps that going until the end of the session, and
asyncio.run() then fails, which breaks the MCP OAuth tests when a browser
test has already run. The page fixture below starts and stops Playwright
itself so the loop does not outlive the test."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import Client

# Playwright's sync API runs an event loop in this thread, which makes Django
# refuse ORM calls from the test body. The tests and the live server don't
# share connections, so this is safe here.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

HTMX_URL = "https://unpkg.com/htmx.org@2.0.4"
HTMX_PATH = Path(__file__).parent / "vendor" / "htmx-2.0.4.min.js"


def _chromium_installed():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        return Path(p.chromium.executable_path).exists()


def pytest_collection_modifyitems(config, items):
    browser_dir = Path(__file__).parent
    browser_items = [item for item in items if browser_dir in Path(item.fspath).parents]
    for item in browser_items:
        item.add_marker(pytest.mark.browser)
    if not browser_items or os.environ.get("VTODO_REQUIRE_BROWSER") == "1":
        return
    if not _chromium_installed():
        skip = pytest.mark.skip(reason="Chromium not installed (run `playwright install chromium`)")
        for item in browser_items:
            item.add_marker(skip)


def _launch_kwargs(config):
    """The pytest-playwright flags these tests still honor. The plugin fixture
    isn't used; see the page fixture."""
    kwargs = {}
    if config.getoption("--headed"):
        kwargs["headless"] = False
    slowmo = config.getoption("--slowmo")
    if slowmo:
        kwargs["slow_mo"] = slowmo
    channel = config.getoption("--browser-channel")
    if channel:
        kwargs["channel"] = channel
    return kwargs


def _route(route, live_server):
    url = route.request.url
    path = urlparse(url).path
    if url.startswith(live_server.url) and path.startswith(settings.STATIC_URL):
        found = finders.find(path.removeprefix(settings.STATIC_URL))
        if found:
            route.fulfill(path=found)
        else:
            route.fulfill(status=404)
    elif url.startswith(live_server.url):
        route.continue_()
    elif url.startswith(HTMX_URL):
        route.fulfill(path=HTMX_PATH, content_type="application/javascript")
    else:
        route.abort()


@pytest.fixture
def page(live_server, browser_name, request):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        browser = browser_type.launch(**_launch_kwargs(request.config))
        context = browser.new_context(base_url=live_server.url)
        try:
            page = context.new_page()
            page.context.route("**/*", lambda route: _route(route, live_server))
            yield page
        finally:
            context.close()
            browser.close()


@pytest.fixture
def login(page, live_server):
    """Log `user` in by handing the browser a session cookie made by the test client."""
    def login(user):
        client = Client()
        client.force_login(user)
        page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": live_server.url,
        }])
    return login
