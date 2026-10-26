"""The suite fails a later test if Playwright's loop is still running.

Browser tests are skipped without Chromium, including in the offline sandbox,
so this runs a tiny suite instead of launching a browser. It does not need
the browser binary: sync_playwright() starts the loop on its own.
"""
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]


def test_a_leaked_playwright_loop_fails_the_next_test(pytester):
    pytester.makeconftest((_ROOT / "conftest.py").read_text())
    pytester.makepyfile(
        """
        import asyncio

        import pytest
        from playwright.sync_api import sync_playwright

        @pytest.fixture(scope="session", autouse=True)
        def leaked_playwright():
            playwright = sync_playwright().start()
            yield
            playwright.stop()

        def test_playwright_is_running():
            assert asyncio.get_running_loop().is_running()

        def test_asyncio_run_after_that():
            async def ok():
                return "ok"

            assert asyncio.run(ok()) == "ok"
        """
    )
    # The parent suite exports DJANGO_SETTINGS_MODULE. This run has no project
    # on its path, so leave pytest-django out.
    result = pytester.runpytest_subprocess("-p", "no:django")
    result.stdout.fnmatch_lines(["*Playwright's event loop is still running*"])
    assert result.ret != 0
