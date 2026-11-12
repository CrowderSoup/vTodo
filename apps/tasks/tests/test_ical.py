import datetime

import pytest
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks import ical
from apps.tasks.models import Task
from apps.users.models import User
from apps.workspaces.access import SESSION_KEY
from apps.workspaces.models import Membership
from apps.workspaces.services import create_shared_workspace


def _unfold(text):
    assert text.endswith("\r\n")
    return text.replace("\r\n ", "").split("\r\n")[:-1]


def _vtodos(text):
    """Each VTODO in an export as a {property line prefix: value} dict, keyed
    by everything before the first ':' (so parameters stay in the key)."""
    todos, current = [], None
    for line in _unfold(text):
        if line == "BEGIN:VTODO":
            current = {}
        elif line == "END:VTODO":
            todos.append(current)
            current = None
        elif current is not None:
            key, _, value = line.partition(":")
            current[key] = value
    return todos


def _only(text):
    (todo,) = _vtodos(text)
    return todo


# ── Formatting ────────────────────────────────────────────────────────────────


def test_escape_text():
    assert ical.escape_text("a;b,c\\d\r\ne\nf") == "a\\;b\\,c\\\\d\\ne\\nf"


def test_fold_keeps_lines_within_75_octets_and_utf8_whole():
    line = "DESCRIPTION:" + "é" * 100
    folded = ical.fold(line)
    parts = folded.split("\r\n")
    assert all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert folded.replace("\r\n ", "") == line


def test_short_line_is_not_folded():
    assert ical.fold("SUMMARY:Hi") == "SUMMARY:Hi"


# ── Task → VTODO ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_calendar_wrapper():
    text = ical.export_tasks([])
    assert _unfold(text) == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{ical.PRODID}",
        "CALSCALE:GREGORIAN",
        "END:VCALENDAR",
    ]


@pytest.mark.django_db
def test_plain_task():
    user = User.objects.create_user()
    task = Task.objects.create(
        user=user,
        title="Buy milk, eggs; bread",
        notes="Line one\nLine two",
        tags=["home", "errands"],
        status="todo",
        due_date=datetime.date(2026, 11, 20),
    )

    todo = _only(ical.export_tasks([task]))

    assert todo["UID"] == task.ical_uid
    assert todo["SUMMARY"] == "Buy milk\\, eggs\\; bread"
    assert todo["DESCRIPTION"] == "Line one\\nLine two"
    assert todo["CATEGORIES"] == "home,errands"
    assert todo["DUE;VALUE=DATE"] == "20261120"
    assert todo["STATUS"] == "NEEDS-ACTION"
    assert "DTSTAMP" in todo
    for absent in ("DTSTART", "DTSTART;VALUE=DATE", "RRULE", "COMPLETED",
                   ical.RECUR_FROM_PROPERTY, ical.DURATION_PROPERTY, ical.ARCHIVED_PROPERTY):
        assert absent not in todo


@pytest.mark.django_db
def test_bare_task_has_no_optional_properties():
    task = Task.objects.create(user=User.objects.create_user(), title="Bare", status="todo")
    todo = _only(ical.export_tasks([task]))
    assert set(todo) == {"UID", "DTSTAMP", "CREATED", "SUMMARY", "STATUS"}


@pytest.mark.django_db
def test_due_time_is_utc_datetime_and_duration_is_kept():
    task = Task.objects.create(
        user=User.objects.create_user(),
        title="Call",
        status="todo",
        due_date=datetime.date(2026, 11, 20),
        due_time=datetime.time(14, 30),
        duration_minutes=90,
    )
    todo = _only(ical.export_tasks([task]))
    assert todo["DUE"] == "20261120T143000Z"
    assert todo[ical.DURATION_PROPERTY] == "PT1H30M"


@pytest.mark.parametrize("minutes,expected", [(30, "PT30M"), (60, "PT1H"), (125, "PT2H5M")])
def test_duration_format(minutes, expected):
    assert ical._duration(minutes) == expected


@pytest.mark.django_db
def test_recurring_from_due_date():
    task = Task.objects.create(
        user=User.objects.create_user(),
        title="Water plants",
        status="todo",
        due_date=datetime.date(2026, 11, 20),
        recurrence_days=3,
        recurrence_from=Task.RECURRENCE_FROM_DUE_DATE,
    )
    todo = _only(ical.export_tasks([task]))
    assert todo["DTSTART;VALUE=DATE"] == "20261120"
    assert todo["DUE;VALUE=DATE"] == "20261120"
    assert todo["RRULE"] == "FREQ=DAILY;INTERVAL=3"
    assert ical.RECUR_FROM_PROPERTY not in todo


@pytest.mark.django_db
def test_recurring_from_completion_with_time():
    task = Task.objects.create(
        user=User.objects.create_user(),
        title="Haircut",
        status="todo",
        due_date=datetime.date(2026, 11, 20),
        due_time=datetime.time(9, 0),
        recurrence_days=28,
        recurrence_from=Task.RECURRENCE_FROM_COMPLETION,
    )
    todo = _only(ical.export_tasks([task]))
    # DTSTART and DUE must share a value type (RFC 5545 3.8.2.3).
    assert todo["DTSTART"] == "20261120T090000Z"
    assert todo["DUE"] == "20261120T090000Z"
    assert todo["RRULE"] == "FREQ=DAILY;INTERVAL=28"
    assert todo[ical.RECUR_FROM_PROPERTY] == "COMPLETION"


@pytest.mark.django_db
def test_recurring_without_due_date_starts_on_its_creation_day():
    task = Task.objects.create(
        user=User.objects.create_user(), title="Stretch", status="todo", recurrence_days=1
    )
    Task.objects.filter(pk=task.pk).update(
        created_at=datetime.datetime(2026, 11, 1, 23, 0, tzinfo=datetime.UTC)
    )
    task.refresh_from_db()

    todo = _only(ical.export_tasks([task]))
    assert todo["DTSTART;VALUE=DATE"] == "20261101"
    assert "DUE;VALUE=DATE" not in todo and "DUE" not in todo
    assert todo["RRULE"] == "FREQ=DAILY;INTERVAL=1"
    assert todo[ical.RECUR_FROM_PROPERTY] == "COMPLETION"


@pytest.mark.django_db
def test_completed_task_drops_its_rrule():
    done_at = datetime.datetime(2026, 11, 10, 8, 15, tzinfo=datetime.UTC)
    task = Task.objects.create(
        user=User.objects.create_user(),
        title="Old copy",
        status="done",
        due_date=datetime.date(2026, 11, 9),
        recurrence_days=7,
    )
    Task.objects.filter(pk=task.pk).update(completed_at=done_at)
    task.refresh_from_db()

    todo = _only(ical.export_tasks([task]))
    assert todo["STATUS"] == "COMPLETED"
    assert todo["COMPLETED"] == "20261110T081500Z"
    assert todo["DUE;VALUE=DATE"] == "20261109"
    assert "RRULE" not in todo
    assert "DTSTART;VALUE=DATE" not in todo


@pytest.mark.django_db
def test_archived_task_is_flagged():
    task = Task.objects.create(
        user=User.objects.create_user(), title="Shelved", status="todo", is_archived=True
    )
    assert _only(ical.export_tasks([task]))[ical.ARCHIVED_PROPERTY] == "TRUE"


# ── UIDs ──────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_uid_is_stable_and_unique():
    user = User.objects.create_user()
    a = Task.objects.create(user=user, title="A", status="todo")
    b = Task.objects.create(user=user, title="B", status="todo")
    assert a.ical_uid and b.ical_uid and a.ical_uid != b.ical_uid
    uid = a.ical_uid
    a.title = "A2"
    a.save()
    a.refresh_from_db()
    assert a.ical_uid == uid


@pytest.mark.django_db
def test_next_recurrence_gets_its_own_uid():
    task = Task.objects.create(
        user=User.objects.create_user(), title="Daily", status="todo", recurrence_days=1
    )
    spawned = task.spawn_recurrence(timezone.now().date())
    assert spawned.ical_uid != task.ical_uid


@pytest.mark.django_db
def test_uid_is_unique_within_a_workspace():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="A", status="todo")
    with pytest.raises(IntegrityError):
        Task.objects.create(user=user, title="B", status="todo", ical_uid=task.ical_uid)


# ── Whole-workspace export ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_workspace_export_includes_done_and_archived_in_creation_order():
    user = User.objects.create_user()
    first = Task.objects.create(user=user, title="First", status="done")
    second = Task.objects.create(user=user, title="Second", status="todo", is_archived=True)
    Task.objects.create(user=User.objects.create_user(), title="Someone else's", status="todo")
    workspace = first.workspace

    todos = _vtodos(ical.export_tasks(ical.workspace_tasks(workspace)))

    assert [t["UID"] for t in todos] == [first.ical_uid, second.ical_uid]


def _api(user, workspace=None):
    token, _ = Token.objects.get_or_create(user=user)
    headers = {"HTTP_AUTHORIZATION": f"Token {token.key}"}
    if workspace is not None:
        headers["HTTP_X_WORKSPACE_ID"] = str(workspace.pk)
    client = APIClient()
    client.credentials(**headers)
    return client


@pytest.mark.django_db
def test_api_export():
    user = User.objects.create_user()
    task = Task.objects.create(user=user, title="Mine", status="todo")
    Task.objects.create(user=User.objects.create_user(), title="Theirs", status="todo")

    response = _api(user).get(reverse("task-export"))

    assert response.status_code == 200
    assert response["Content-Type"] == ical.CONTENT_TYPE
    assert response["Content-Disposition"].startswith('attachment; filename="vtodo-')
    assert [t["SUMMARY"] for t in _vtodos(response.content.decode())] == [task.title]


@pytest.mark.django_db
def test_api_export_follows_the_workspace_header_and_allows_viewers():
    owner = User.objects.create_user()
    workspace = create_shared_workspace(user=owner, name="Aaron & Azure")
    viewer = User.objects.create_user()
    Membership.objects.create(workspace=workspace, user=viewer, role=Membership.ROLE_VIEWER)
    Task.objects.create(user=owner, workspace=workspace, title="Shared", status="todo")
    Task.objects.create(user=viewer, title="Viewer's own", status="todo")

    response = _api(viewer, workspace).get(reverse("task-export"))

    assert response.status_code == 200
    assert 'filename="vtodo-aaron-azure-' in response["Content-Disposition"]
    assert [t["SUMMARY"] for t in _vtodos(response.content.decode())] == ["Shared"]


@pytest.mark.django_db
def test_api_export_needs_auth():
    assert APIClient().get(reverse("task-export")).status_code in (401, 403)


@pytest.mark.django_db
def test_web_export_uses_the_active_workspace(client):
    owner = User.objects.create_user()
    workspace = create_shared_workspace(user=owner, name="Shared one")
    Task.objects.create(user=owner, workspace=workspace, title="In shared", status="todo")
    Task.objects.create(user=owner, title="In personal", status="todo")
    client.force_login(owner)

    personal = client.get(reverse("users:task-export"))
    assert personal.status_code == 200
    assert [t["SUMMARY"] for t in _vtodos(personal.content.decode())] == ["In personal"]

    session = client.session
    session[SESSION_KEY] = workspace.pk
    session.save()
    shared = client.get(reverse("users:task-export"))
    assert [t["SUMMARY"] for t in _vtodos(shared.content.decode())] == ["In shared"]


@pytest.mark.django_db
def test_web_export_needs_login(client):
    response = client.get(reverse("users:task-export"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_settings_page_links_to_the_export(client):
    client.force_login(User.objects.create_user())
    response = client.get(reverse("users:settings"))
    assert reverse("users:task-export").encode() in response.content
