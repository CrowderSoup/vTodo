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
staticfiles/ can't shadow them."""
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


@pytest.fixture
def browser_context_args(browser_context_args, live_server):
    return {**browser_context_args, "base_url": live_server.url}


@pytest.fixture
def page(page, live_server):
    def handle(route):
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

    page.context.route("**/*", handle)
    return page


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
