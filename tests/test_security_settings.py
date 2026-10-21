"""Production security settings are on whenever DEBUG is off.

DEBUG is read at import time, so each case loads config.settings in a fresh
interpreter rather than reloading the module the test run already uses."""

import json
import os
import subprocess
import sys
from pathlib import Path

NAMES = [
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SESSION_COOKIE_HTTPONLY",
    "CSRF_COOKIE_HTTPONLY",
    "SECURE_CONTENT_TYPE_NOSNIFF",
]


def load_settings(debug):
    script = (
        "import json, config.settings as s; "
        f"print(json.dumps({{n: getattr(s, n, None) for n in {NAMES!r}}}))"
    )
    env = {**os.environ, "DEBUG": debug, "INTEGRATIONS_ENCRYPTION_KEY": "test"}
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def test_production_sends_hsts_and_secure_cookies():
    s = load_settings("False")
    assert s["SECURE_HSTS_SECONDS"] == 60 * 60 * 24 * 365
    assert s["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is True
    assert s["SESSION_COOKIE_SECURE"] is True
    assert s["CSRF_COOKIE_SECURE"] is True
    assert s["SESSION_COOKIE_HTTPONLY"] is True
    assert s["SECURE_CONTENT_TYPE_NOSNIFF"] is True
    # static/app.js reads document.cookie for the htmx X-CSRFToken header.
    assert not s["CSRF_COOKIE_HTTPONLY"]


def test_debug_leaves_cookies_usable_over_http():
    s = load_settings("True")
    assert not s["SESSION_COOKIE_SECURE"]
    assert not s["SECURE_HSTS_SECONDS"]
