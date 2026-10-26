"""Keep Playwright's event loop from leaking into the rest of the suite.

Browser tests start that loop on this thread. If it is still running,
asyncio.run() raises, and the MCP OAuth tests fail whenever a browser test
has already run. tests/browser/conftest.py stops Playwright at the end of
each browser test. This hook fails the next test if that stop didn't happen.
"""
import asyncio
from pathlib import Path

import pytest

_BROWSER_DIR = Path(__file__).resolve().parent / "tests" / "browser"


def _is_browser_test(item):
    path = Path(str(item.path)).resolve()
    return path == _BROWSER_DIR or _BROWSER_DIR in path.parents


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if _is_browser_test(item):
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    pytest.fail(
        "Playwright's event loop is still running. Browser tests have to stop "
        "it before the next test so asyncio.run() keeps working.",
        pytrace=False,
    )
