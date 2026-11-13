from datetime import date

import pytest

from apps.attachments import services
from apps.attachments.models import Attachment, PendingDeletion
from apps.attachments.services import AttachmentError
from apps.attachments.tasks import purge_vupload_deletions
from apps.tasks.models import Task, TaskActivity, TaskComment
from apps.users.models import User
from apps.workspaces.models import Membership
from apps.workspaces.services import create_shared_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40


@pytest.fixture
def user(db):
    return User.objects.create_user()


@pytest.fixture
def task(user):
    return Task.objects.create(user=user, title="Receipts")


def attach(fake, task, user, data=PNG, name="cat.png", ctype="image/png", comment=None):
    up = services.start_upload(task=task, filename=name, content_type=ctype, size=len(data))
    fake.put(up["file_id"], data)
    return services.finish_upload(
        task=task, file_id=up["file_id"], actor=user, source="web", comment=comment
    )


def test_attach_records_vuploads_metadata_and_activity(fake_vupload, task, user):
    up = services.start_upload(task=task, filename="cat.png", content_type="image/png", size=len(PNG))
    assert up["upload_method"] == "PUT" and up["upload_headers"] == {"Content-Type": "image/png"}
    assert fake_vupload.files[up["file_id"]]["owner"] == f"workspace:{task.workspace_id}"

    fake_vupload.put(up["file_id"], PNG)
    a = services.finish_upload(task=task, file_id=up["file_id"], actor=user, source="web")

    assert (a.task, a.workspace_id, a.uploaded_by) == (task, task.workspace_id, user)
    assert (a.original_name, a.content_type, a.size) == ("cat.png", "image/png", len(PNG))
    assert a.is_image
    row = TaskActivity.objects.get(task_pk=task.pk, action=TaskActivity.ATTACHED)
    assert row.new_value == "cat.png" and row.actor == user


def test_finish_twice_returns_the_same_attachment(fake_vupload, task, user):
    a = attach(fake_vupload, task, user)
    again = services.finish_upload(task=task, file_id=a.file_id, actor=user, source="web")
    assert again.pk == a.pk
    assert Attachment.objects.count() == 1
    assert TaskActivity.objects.filter(action=TaskActivity.ATTACHED).count() == 1


def test_another_workspaces_upload_cant_be_claimed(fake_vupload, task, user):
    other_user = User.objects.create_user()
    other_task = Task.objects.create(user=other_user, title="Theirs")
    up = services.start_upload(task=other_task, filename="a.png", content_type="image/png", size=len(PNG))
    fake_vupload.put(up["file_id"], PNG)

    with pytest.raises(AttachmentError) as exc:
        services.finish_upload(task=task, file_id=up["file_id"], actor=user, source="web")
    assert exc.value.status == 404
    assert not Attachment.objects.exists()
    # And an attachment already on another task can't be re-finished onto this one.
    a = attach(fake_vupload, other_task, other_user)
    with pytest.raises(AttachmentError):
        services.finish_upload(task=task, file_id=a.file_id, actor=user, source="web")


def test_comment_must_be_on_the_task(fake_vupload, task, user):
    other = Task.objects.create(user=user, title="Other")
    comment = TaskComment.objects.create(task=other, author=user, body="hi")
    with pytest.raises(AttachmentError):
        attach(fake_vupload, task, user, comment=comment)
    ok = TaskComment.objects.create(task=task, author=user, body="hi")
    a = attach(fake_vupload, task, user, comment=ok)
    assert a.comment == ok and a.task == task


@pytest.mark.parametrize(
    "setup,status",
    [
        (lambda fake, fid: None, 409),  # never uploaded
        (lambda fake, fid: fake.put(fid, b"MZ\x90" + b"x" * 43), 422),  # bytes aren't a PNG
        (lambda fake, fid: fake.put(fid, PNG + b"extra"), 422),  # wrong size
    ],
)
def test_finish_errors_leave_no_attachment(fake_vupload, task, user, setup, status):
    up = services.start_upload(task=task, filename="cat.png", content_type="image/png", size=len(PNG))
    setup(fake_vupload, up["file_id"])
    with pytest.raises(AttachmentError) as exc:
        services.finish_upload(task=task, file_id=up["file_id"], actor=user, source="web")
    assert exc.value.status == status
    assert not Attachment.objects.exists()


def test_declared_checks_and_type_guessing(fake_vupload, task):
    with pytest.raises(AttachmentError) as exc:
        services.start_upload(task=task, filename="a.zip", content_type="application/zip", size=10)
    assert exc.value.status == 415
    with pytest.raises(AttachmentError) as exc:
        services.start_upload(task=task, filename="a.svg", content_type="image/svg+xml", size=10)
    assert exc.value.status == 415
    with pytest.raises(AttachmentError) as exc:
        services.start_upload(task=task, filename="a.png", content_type="image/png", size=25 * 1024 * 1024 + 1)
    assert exc.value.status == 413
    # Browsers send octet-stream for .md and .heic; the extension decides.
    up = services.start_upload(task=task, filename="Notes.MD", content_type="application/octet-stream", size=3)
    assert up["upload_headers"]["Content-Type"] == "text/markdown"
    assert services.guess_type("x.docm", "") == ""


def test_quota_message(fake_vupload, task):
    fake_vupload.owner_limit = 10
    with pytest.raises(AttachmentError) as exc:
        services.start_upload(task=task, filename="a.png", content_type="image/png", size=11)
    assert exc.value.status == 409 and "storage" in exc.value.message


def test_download_url_is_inline_only_for_images(fake_vupload, task, user):
    img = attach(fake_vupload, task, user)
    pdf = attach(fake_vupload, task, user, data=b"%PDF-1.7", name="a.pdf", ctype="application/pdf")
    assert "disposition=inline" in services.download_url(img, inline=True)
    assert "disposition=attachment" in services.download_url(img)
    assert "disposition=attachment" in services.download_url(pdf, inline=True)


def test_upload_bytes_puts_then_finishes(fake_vupload, task, user, monkeypatch):
    calls = []

    class Resp:
        status_code = 200

    def fake_put(url, data, headers, timeout):
        calls.append((url, headers))
        fake_vupload.put(url.split("/vtodo/")[1].split("?")[0], data, headers["Content-Type"])
        return Resp()

    monkeypatch.setattr(services.requests, "put", fake_put)
    a = services.upload_bytes(
        task=task, filename="n.txt", content_type="text/plain", data=b"hello", actor=user, source="mcp"
    )
    assert a.size == 5 and a.content_type == "text/plain"
    assert calls[0][1] == {"Content-Type": "text/plain"}


def test_delete_attachment_removes_the_file_in_vupload(
    fake_vupload, task, user, django_capture_on_commit_callbacks
):
    a = attach(fake_vupload, task, user)
    with django_capture_on_commit_callbacks(execute=True):
        services.delete_attachment(a, actor=user, source="web")
    assert not Attachment.objects.exists()
    assert str(a.file_id) not in fake_vupload.files
    assert not PendingDeletion.objects.exists()
    row = TaskActivity.objects.get(action=TaskActivity.ATTACHMENT_DELETED)
    assert row.old_value == "cat.png"


def test_deleting_a_task_deletes_its_files(fake_vupload, task, user, django_capture_on_commit_callbacks):
    a = attach(fake_vupload, task, user)
    comment = TaskComment.objects.create(task=task, author=user, body="see file")
    b = attach(fake_vupload, task, user, comment=comment)
    with django_capture_on_commit_callbacks(execute=True):
        task.delete()
    assert str(a.file_id) not in fake_vupload.files
    assert str(b.file_id) not in fake_vupload.files


def test_vupload_down_queues_the_delete_until_it_returns(
    fake_vupload, task, user, django_capture_on_commit_callbacks
):
    a = attach(fake_vupload, task, user)
    fake_vupload.down = True
    with django_capture_on_commit_callbacks(execute=True):
        services.delete_attachment(a, actor=user, source="web")
    pending = PendingDeletion.objects.get()
    assert pending.attempts == 1 and "unreachable" in pending.last_error

    fake_vupload.down = False
    assert purge_vupload_deletions() == 1
    assert not PendingDeletion.objects.exists()
    assert str(a.file_id) not in fake_vupload.files


def test_deleting_a_workspace_deletes_its_owner_once(
    fake_vupload, user, django_capture_on_commit_callbacks
):
    workspace = create_shared_workspace(user=user, name="Home")
    task = Task.objects.create(user=user, workspace=workspace, title="Shared")
    a = attach(fake_vupload, task, user)
    owner = f"workspace:{workspace.pk}"
    with django_capture_on_commit_callbacks(execute=True):
        workspace.delete()
    assert fake_vupload.deleted_owners == [owner]
    assert str(a.file_id) not in fake_vupload.files
    assert not PendingDeletion.objects.exists()


def test_deleting_an_account_deletes_its_personal_workspaces_files(
    fake_vupload, task, user, django_capture_on_commit_callbacks
):
    attach(fake_vupload, task, user)
    owner = f"workspace:{task.workspace_id}"
    with django_capture_on_commit_callbacks(execute=True):
        user.delete()
    assert owner in fake_vupload.deleted_owners
    assert not fake_vupload.files


def test_a_member_leaving_keeps_shared_files(fake_vupload, user, django_capture_on_commit_callbacks):
    workspace = create_shared_workspace(user=user, name="Home")
    member = User.objects.create_user()
    Membership.objects.create(workspace=workspace, user=member, role=Membership.ROLE_MEMBER)
    task = Task.objects.create(user=user, workspace=workspace, title="Shared")
    a = attach(fake_vupload, task, member)
    with django_capture_on_commit_callbacks(execute=True):
        member.delete()
    a.refresh_from_db()
    assert a.uploaded_by is None
    assert str(a.file_id) in fake_vupload.files


def test_can_delete_rules(fake_vupload, user):
    workspace = create_shared_workspace(user=user, name="Home")
    member = User.objects.create_user()
    viewer = User.objects.create_user()
    m_member = Membership.objects.create(workspace=workspace, user=member, role=Membership.ROLE_MEMBER)
    m_viewer = Membership.objects.create(workspace=workspace, user=viewer, role=Membership.ROLE_VIEWER)
    m_owner = Membership.objects.get(workspace=workspace, user=user)
    task = Task.objects.create(user=user, workspace=workspace, title="Shared")
    mine = attach(fake_vupload, task, member)
    theirs = attach(fake_vupload, task, user)
    assert services.can_delete(m_member, mine, member)
    assert not services.can_delete(m_member, theirs, member)
    assert services.can_delete(m_owner, mine, user)
    assert not services.can_delete(m_viewer, mine, viewer)


def test_recurring_copies_dont_carry_attachments(fake_vupload, user):
    task = Task.objects.create(user=user, title="Water plants", recurrence_days=7)
    attach(fake_vupload, task, user)
    nxt = task.spawn_recurrence(date(2026, 11, 13))
    assert nxt.attachments.count() == 0


def test_disabled_without_settings(db, settings):
    settings.VUPLOAD_URL = ""
    assert not services.enabled()
    with pytest.raises(AttachmentError) as exc:
        services.start_upload(task=None, filename="a.png", content_type="image/png", size=1)
    assert exc.value.status == 503
