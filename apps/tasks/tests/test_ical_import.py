import datetime
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.tasks import ical, ical_import, lifecycle
from apps.tasks.models import Task, TaskActivity, TaskStatus
from apps.tasks.selectors import move_task
from apps.users.models import User
from apps.workspaces.models import Membership
from apps.workspaces.services import create_shared_workspace, ensure_personal_workspace


def _cal(*todos):
    body = "".join(f"BEGIN:VTODO\r\n{t.strip()}\r\nEND:VTODO\r\n" for t in todos)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n{body}END:VCALENDAR\r\n"


def _import(user, text, *, dry_run=False, **kwargs):
    return ical_import.import_ics(
        text, workspace=ensure_personal_workspace(user), user=user, dry_run=dry_run, **kwargs
    )


def _only_task(user):
    (task,) = Task.objects.filter(workspace=ensure_personal_workspace(user))
    return task


def _without_dtstamp(text):
    return [line for line in text.replace("\r\n ", "").split("\r\n") if not line.startswith("DTSTAMP:")]


# ── Reading the file ──────────────────────────────────────────────────────────


def test_unfold_accepts_crlf_lf_and_tab_continuations():
    assert ical_import.unfold("A:1\r\n 2\nB:x\n\ty\n\n") == ["A:12", "B:xy"]


def test_parse_line_with_quoted_params():
    prop = ical_import.parse_line('DUE;TZID="America/New_York";X-A=b:20261120T090000')
    assert prop.name == "DUE"
    assert prop.params == {"TZID": "America/New_York", "X-A": "b"}
    assert prop.value == "20261120T090000"


def test_unescape_reverses_escape():
    original = "a;b,c\\d\ne"
    assert ical_import.unescape_text(ical.escape_text(original)) == original


def test_split_text_list_keeps_escaped_commas():
    assert ical_import.split_text_list("home,a\\,b, work ") == ["home", "a,b", "work"]


def test_not_a_calendar():
    with pytest.raises(ical_import.IcsImportError):
        ical_import.vtodos("hello")


def test_events_and_alarms_are_ignored():
    text = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Meeting\r\nEND:VEVENT\r\n"
        "BEGIN:VTODO\r\nSUMMARY:Task\r\nBEGIN:VALARM\r\nSUMMARY:Alarm\r\nEND:VALARM\r\nEND:VTODO\r\n"
        "END:VCALENDAR\r\n"
    )
    (todo,) = ical_import.vtodos(text)
    assert [(p.name, p.value) for p in todo] == [("SUMMARY", "Task")]


@pytest.mark.parametrize(
    "rule,days,problem",
    [
        ("FREQ=DAILY", 1, False),
        ("FREQ=DAILY;INTERVAL=3", 3, False),
        ("FREQ=WEEKLY;INTERVAL=2", 14, False),
        ("FREQ=WEEKLY;BYDAY=MO;WKST=MO", 7, False),
        ("FREQ=DAILY;COUNT=5", 1, True),
        ("FREQ=WEEKLY;BYDAY=MO,WE", None, True),
        ("FREQ=MONTHLY", None, True),
        ("FREQ=DAILY;INTERVAL=0", None, True),
        ("FREQ=DAILY;INTERVAL=x", None, True),
    ],
)
def test_parse_rrule(rule, days, problem):
    got_days, got_problem = ical_import.parse_rrule(rule)
    assert got_days == days
    assert bool(got_problem) == problem


@pytest.mark.parametrize("value,minutes", [("PT1H30M", 90), ("PT45M", 45), ("P1D", 1440), ("nope", None)])
def test_parse_duration(value, minutes):
    assert ical_import.parse_duration_minutes(value) == minutes


# ── Importing ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_imports_a_task_from_another_app():
    user = User.objects.create_user()
    text = _cal(
        "UID:abc@other\r\nSUMMARY:Buy milk\\, eggs\r\nDESCRIPTION:One\\nTwo\r\n"
        "CATEGORIES:home,errands\r\nCATEGORIES:shop\r\nDUE;VALUE=DATE:20261120\r\nSTATUS:NEEDS-ACTION"
    )

    result = _import(user, text)

    assert (result.created, result.updated, result.skipped) == (1, 0, 0)
    task = _only_task(user)
    assert task.ical_uid == "abc@other"
    assert task.title == "Buy milk, eggs"
    assert task.notes == "One\nTwo"
    assert task.tags == ["home", "errands", "shop"]
    assert task.due_date == datetime.date(2026, 11, 20)
    assert task.due_time is None
    assert task.status == "backlog"  # the first status, as for any new task
    assert task.completed_at is None
    assert TaskActivity.objects.filter(task=task, action=TaskActivity.CREATED).count() == 1


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    user = User.objects.create_user()
    result = _import(user, _cal("UID:a\r\nSUMMARY:A"), dry_run=True)
    assert result.dry_run and result.created == 1
    assert result.summary == "1 new, 0 updated, 0 skipped"
    assert not Task.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_importing_twice_adds_nothing():
    user = User.objects.create_user()
    text = _cal("UID:a\r\nSUMMARY:A\r\nDUE:20261120T143000Z", "UID:b\r\nSUMMARY:B")
    _import(user, text)
    again = _import(user, text)
    assert (again.created, again.updated, again.skipped) == (0, 0, 2)
    assert Task.objects.filter(user=user).count() == 2


@pytest.mark.django_db
def test_a_matched_task_is_updated_and_its_history_recorded():
    user = User.objects.create_user()
    _import(user, _cal("UID:a\r\nSUMMARY:Old\r\nCATEGORIES:x"))

    result = _import(user, _cal("UID:a\r\nSUMMARY:New\r\nCATEGORIES:x,y"), dry_run=True)
    assert result.updated == 1
    assert result.tasks[0].changes == ["title", "tags"]
    assert _only_task(user).title == "Old"

    _import(user, _cal("UID:a\r\nSUMMARY:New\r\nCATEGORIES:x,y"))
    task = _only_task(user)
    assert (task.title, task.tags) == ("New", ["x", "y"])
    fields = set(TaskActivity.objects.filter(task=task, action=TaskActivity.UPDATED).values_list("field", flat=True))
    assert fields == {"title", "tags"}


@pytest.mark.django_db
def test_uids_are_matched_only_within_the_workspace():
    owner = User.objects.create_user()
    other = User.objects.create_user()
    _import(owner, _cal("UID:same\r\nSUMMARY:Mine"))
    assert _import(other, _cal("UID:same\r\nSUMMARY:Theirs")).created == 1
    assert _only_task(owner).title == "Mine"


@pytest.mark.django_db
def test_due_times_are_stored_in_utc():
    user = User.objects.create_user()
    _import(user, _cal('UID:a\r\nSUMMARY:A\r\nDUE;TZID="America/New_York":20261120T090000'))
    task = _only_task(user)
    assert (task.due_date, task.due_time) == (datetime.date(2026, 11, 20), datetime.time(14, 0))


@pytest.mark.django_db
def test_floating_time_is_read_in_the_given_zone():
    user = User.objects.create_user()
    _import(user, _cal("UID:a\r\nSUMMARY:A\r\nDUE:20261120T230000"), floating_tz=ZoneInfo("America/Denver"))
    task = _only_task(user)
    assert (task.due_date, task.due_time) == (datetime.date(2026, 11, 21), datetime.time(6, 0))


@pytest.mark.django_db
def test_unknown_tzid_is_read_as_utc_with_a_warning():
    user = User.objects.create_user()
    result = _import(user, _cal("UID:a\r\nSUMMARY:A\r\nDUE;TZID=Nowhere/Land:20261120T090000"))
    assert _only_task(user).due_time == datetime.time(9, 0)
    assert any("Nowhere/Land" in w for w in result.warnings)


@pytest.mark.django_db
def test_recurrence_from_due_date_and_from_completion():
    user = User.objects.create_user()
    _import(
        user,
        _cal(
            "UID:a\r\nSUMMARY:A\r\nDTSTART;VALUE=DATE:20261120\r\nDUE;VALUE=DATE:20261120\r\nRRULE:FREQ=WEEKLY",
            "UID:b\r\nSUMMARY:B\r\nRRULE:FREQ=DAILY;INTERVAL=2\r\nX-VTODO-RECUR-FROM:COMPLETION",
        ),
    )
    a = Task.objects.get(ical_uid="a")
    b = Task.objects.get(ical_uid="b")
    assert (a.recurrence_days, a.recurrence_from) == (7, Task.RECURRENCE_FROM_DUE_DATE)
    assert (b.recurrence_days, b.recurrence_from) == (2, Task.RECURRENCE_FROM_COMPLETION)


@pytest.mark.django_db
def test_unsupported_rrule_imports_a_one_off_with_a_warning():
    user = User.objects.create_user()
    text = _cal("UID:a\r\nSUMMARY:Gym\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE", "UID:b\r\nSUMMARY:Fine")
    result = _import(user, text)
    assert result.created == 2
    assert Task.objects.get(ical_uid="a").recurrence_days is None
    assert len(result.warnings) == 1 and '"Gym"' in result.warnings[0]


@pytest.mark.django_db
def test_unsupported_rrule_leaves_a_matched_tasks_recurrence_alone():
    user = User.objects.create_user()
    _import(user, _cal("UID:a\r\nSUMMARY:Gym\r\nRRULE:FREQ=DAILY;INTERVAL=3"))
    result = _import(user, _cal("UID:a\r\nSUMMARY:Gym\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE"))
    assert result.skipped == 1
    assert _only_task(user).recurrence_days == 3


@pytest.mark.django_db
def test_completed_task_goes_to_done_with_its_time_and_spawns_nothing():
    user = User.objects.create_user()
    _import(
        user,
        _cal("UID:a\r\nSUMMARY:A\r\nSTATUS:COMPLETED\r\nCOMPLETED:20261110T081500Z\r\nRRULE:FREQ=DAILY"),
    )
    task = _only_task(user)  # no spawned next occurrence
    assert task.status == "done"
    assert task.completed_at == datetime.datetime(2026, 11, 10, 8, 15, tzinfo=datetime.UTC)
    assert task.previous_status == ""


@pytest.mark.django_db
def test_import_completes_and_reopens_matched_tasks():
    user = User.objects.create_user()
    _import(user, _cal("UID:a\r\nSUMMARY:A"))
    task = _only_task(user)
    move_task(user, task, "in_progress")

    result = _import(user, _cal("UID:a\r\nSUMMARY:A\r\nSTATUS:COMPLETED"))
    assert result.tasks[0].changes == ["done"]
    task.refresh_from_db()
    assert task.status == "done" and task.completed_at is not None

    _import(user, _cal("UID:a\r\nSUMMARY:A\r\nSTATUS:NEEDS-ACTION"))
    task.refresh_from_db()
    assert task.status == "in_progress" and task.completed_at is None
    moves = TaskActivity.objects.filter(task=task, action=TaskActivity.MOVED).values_list("new_value", flat=True)
    assert list(moves) == ["in_progress", "done", "in_progress"]


@pytest.mark.django_db
def test_no_done_status_imports_completed_tasks_as_open():
    user = User.objects.create_user()
    TaskStatus.objects.filter(workspace=ensure_personal_workspace(user), is_done=True).update(is_done=False)
    result = _import(user, _cal("UID:a\r\nSUMMARY:A\r\nSTATUS:COMPLETED"))
    assert _only_task(user).completed_at is None
    assert any("no done status" in w for w in result.warnings)


@pytest.mark.django_db
def test_missing_uid_duplicates_and_overrides():
    user = User.objects.create_user()
    text = _cal(
        "SUMMARY:No uid",
        "UID:a\r\nSUMMARY:First",
        "UID:a\r\nSUMMARY:Again",
        "UID:a\r\nRECURRENCE-ID:20261120T090000Z\r\nSUMMARY:One occurrence",
    )
    result = _import(user, text)
    assert [t.action for t in result.tasks] == ["create", "create", "skip", "skip"]
    assert len(result.warnings) == 3
    assert sorted(Task.objects.filter(user=user).values_list("title", flat=True)) == ["First", "No uid"]


@pytest.mark.django_db
def test_untitled_and_overlong_titles():
    user = User.objects.create_user()
    result = _import(user, _cal("UID:a", f"UID:b\r\nSUMMARY:{'x' * 600}"))
    assert Task.objects.get(ical_uid="a").title == "Untitled task"
    assert len(Task.objects.get(ical_uid="b").title) == 500
    assert len(result.warnings) == 2


@pytest.mark.django_db
def test_new_tasks_go_after_existing_ones_in_file_order():
    user = User.objects.create_user()
    Task.objects.create(user=user, title="Existing", status="todo", order=0)
    _import(user, _cal("UID:a\r\nSUMMARY:A", "UID:b\r\nSUMMARY:B"))
    assert Task.objects.get(ical_uid="a").order == 1
    assert Task.objects.get(ical_uid="b").order == 2


@pytest.mark.django_db
def test_too_big():
    user = User.objects.create_user()
    with pytest.raises(ical_import.IcsImportError):
        _import(user, "x" * (ical_import.MAX_BYTES + 1))


# ── Round trip ────────────────────────────────────────────────────────────────


def _varied_tasks(user):
    def make(**fields):
        task = Task.objects.create(user=user, **fields)
        return lifecycle.start(task)

    make(title="Plain, with; escapes", notes="Line one\nLine two \\ done", status="todo",
         tags=["home", "a,b"], due_date=datetime.date(2026, 11, 20))
    make(title="Timed", status="in_progress", due_date=datetime.date(2026, 11, 21),
         due_time=datetime.time(14, 30), duration_minutes=90)
    make(title="Water plants", status="todo", due_date=datetime.date(2026, 11, 22),
         recurrence_days=3, recurrence_from=Task.RECURRENCE_FROM_DUE_DATE)
    make(title="Haircut", status="todo", due_date=datetime.date(2026, 11, 23),
         due_time=datetime.time(9, 0), recurrence_days=28,
         recurrence_from=Task.RECURRENCE_FROM_COMPLETION)
    make(title="Stretch", status="backlog", recurrence_days=1)
    make(title="Finished", status="done", due_date=datetime.date(2026, 11, 1))
    make(title="Finished copy of a series", status="done", recurrence_days=7)
    make(title="Shelved", status="todo", is_archived=True)
    make(title="Shelved and done", status="done", is_archived=True)
    make(title="Ünïcödé " + "é" * 60, status="todo")


@pytest.mark.django_db
def test_round_trip_export_import_export_matches():
    source = User.objects.create_user()
    _varied_tasks(source)
    first = ical.export_tasks(ical.workspace_tasks(ensure_personal_workspace(source)))

    target = User.objects.create_user()
    result = _import(target, first)
    assert (result.created, result.updated, result.skipped) == (10, 0, 0)
    assert result.warnings == []

    second = ical.export_tasks(ical.workspace_tasks(ensure_personal_workspace(target)))
    assert _without_dtstamp(second) == _without_dtstamp(first)
    assert "RRULE:FREQ=DAILY;INTERVAL=3" in second
    assert "X-VTODO-RECUR-FROM:COMPLETION" in second


@pytest.mark.django_db
def test_reimporting_a_workspaces_own_export_changes_nothing():
    user = User.objects.create_user()
    _varied_tasks(user)
    workspace = ensure_personal_workspace(user)
    text = ical.export_tasks(ical.workspace_tasks(workspace))
    before = list(Task.objects.filter(workspace=workspace).values())

    result = _import(user, text)

    assert (result.created, result.updated, result.skipped) == (0, 0, 10)
    assert list(Task.objects.filter(workspace=workspace).values()) == before


# ── API ───────────────────────────────────────────────────────────────────────


def _api(user, workspace=None):
    token, _ = Token.objects.get_or_create(user=user)
    headers = {"HTTP_AUTHORIZATION": f"Token {token.key}"}
    if workspace is not None:
        headers["HTTP_X_WORKSPACE_ID"] = str(workspace.pk)
    client = APIClient()
    client.credentials(**headers)
    return client


@pytest.mark.django_db
def test_api_import_dry_run_then_import():
    user = User.objects.create_user()
    url = reverse("task-import")
    text = _cal("UID:a\r\nSUMMARY:A")

    preview = _api(user).post(url, {"ics": text, "dry_run": True}, format="json")
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["created"] == 1
    assert not Task.objects.filter(user=user).exists()

    done = _api(user).post(url, {"ics": text}, format="json")
    assert done.status_code == 200
    assert done.json()["summary"] == "1 new, 0 updated, 0 skipped"
    assert done.json()["tasks"][0]["action"] == "create"
    assert TaskActivity.objects.get(task=_only_task(user)).source == TaskActivity.SOURCE_API


@pytest.mark.django_db
def test_api_import_accepts_a_file_upload():
    from django.core.files.uploadedfile import SimpleUploadedFile

    user = User.objects.create_user()
    upload = SimpleUploadedFile("tasks.ics", _cal("UID:a\r\nSUMMARY:A").encode(), "text/calendar")
    response = _api(user).post(reverse("task-import"), {"file": upload}, format="multipart")
    assert response.status_code == 200
    assert _only_task(user).title == "A"


@pytest.mark.django_db
def test_api_import_rejects_bad_input():
    user = User.objects.create_user()
    assert _api(user).post(reverse("task-import"), {}, format="json").status_code == 400
    response = _api(user).post(reverse("task-import"), {"ics": "nope"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_api_import_goes_to_the_header_workspace_and_viewers_cannot():
    owner = User.objects.create_user()
    workspace = create_shared_workspace(user=owner, name="Shared")
    viewer = User.objects.create_user()
    Membership.objects.create(workspace=workspace, user=viewer, role=Membership.ROLE_VIEWER)
    text = _cal("UID:a\r\nSUMMARY:A")

    assert _api(viewer, workspace).post(reverse("task-import"), {"ics": text}, format="json").status_code == 403
    assert _api(owner, workspace).post(reverse("task-import"), {"ics": text}, format="json").status_code == 200
    assert Task.objects.get(ical_uid="a").workspace == workspace


# ── Web ───────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_web_import_previews_then_imports(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    user = User.objects.create_user()
    client.force_login(user)
    text = _cal("UID:a\r\nSUMMARY:From a file", "UID:b\r\nSUMMARY:Gym\r\nRRULE:FREQ=MONTHLY")
    upload = SimpleUploadedFile("tasks.ics", text.encode(), "text/calendar")

    preview = client.post(reverse("users:task-import"), {"file": upload})
    assert preview.status_code == 200
    assert b"2 new, 0 updated, 0 skipped" in preview.content
    assert b"From a file" in preview.content
    assert b"repeats monthly" in preview.content
    assert not Task.objects.filter(user=user).exists()

    confirm = client.post(
        reverse("users:task-import"),
        {"confirm": "1", "ics": preview.context["ics"], "filename": "tasks.ics"},
        follow=True,
    )
    assert confirm.redirect_chain[-1][0] == reverse("users:settings")
    assert b"2 new, 0 updated, 0 skipped" in confirm.content
    assert Task.objects.filter(user=user).count() == 2


@pytest.mark.django_db
def test_web_import_reports_a_bad_file(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(User.objects.create_user())
    upload = SimpleUploadedFile("notes.txt", b"hello", "text/plain")
    response = client.post(reverse("users:task-import"), {"file": upload}, follow=True)
    assert b"isn&#x27;t an iCalendar" in response.content


@pytest.mark.django_db
def test_web_import_needs_write_access(client):
    from apps.workspaces.access import SESSION_KEY

    owner = User.objects.create_user()
    workspace = create_shared_workspace(user=owner, name="Shared")
    viewer = User.objects.create_user()
    Membership.objects.create(workspace=workspace, user=viewer, role=Membership.ROLE_VIEWER)
    client.force_login(viewer)
    session = client.session
    session[SESSION_KEY] = workspace.pk
    session.save()

    settings_page = client.get(reverse("users:settings"))
    assert reverse("users:task-import").encode() not in settings_page.content
    response = client.post(
        reverse("users:task-import"), {"confirm": "1", "ics": _cal("UID:a\r\nSUMMARY:A")}
    )
    assert response.status_code == 403
    assert not Task.objects.exists()


@pytest.mark.django_db
def test_settings_page_has_the_import_form(client):
    client.force_login(User.objects.create_user())
    response = client.get(reverse("users:settings"))
    assert reverse("users:task-import").encode() in response.content
