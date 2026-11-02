"""Which workspace a request is acting in, and what that person's role allows.

The active workspace lives in the session for the browser. API clients send
`X-Workspace-Id` instead. Anything else uses the caller's personal workspace.
"""

from contextvars import ContextVar

from django.core.exceptions import PermissionDenied
from django.http import Http404

from apps.workspaces.models import Membership
from apps.workspaces.services import ensure_personal_workspace

SESSION_KEY = "active_workspace_id"
_request = ContextVar("vtodo_request", default=None)


def bind_request(request):
    """Remember this request so task queries can follow its workspace."""
    return _request.set(request)


def reset_request(token):
    _request.reset(token)


def bind_request_workspace(request):
    """Set request.active_workspace once the user is authenticated.

    Called again after API token auth, which runs inside the view, later than
    the session middleware. Anonymous calls do nothing and stay unbound.
    """
    if getattr(request, "_workspace_bound", False):
        return
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return
    workspace, membership = resolve_request_workspace(request)
    request.active_workspace = workspace
    request.workspace_membership = membership
    request._workspace_bound = True


def resolve_request_workspace(request):
    user = request.user
    explicit = request.headers.get("X-Workspace-Id", "").strip()
    if explicit:
        if not explicit.isdigit():
            raise Http404("No such workspace.")
        membership = (
            Membership.objects.filter(workspace_id=int(explicit), user=user)
            .select_related("workspace")
            .first()
        )
        if membership is None:
            raise Http404("No such workspace.")
        return membership.workspace, membership

    stored = request.session.get(SESSION_KEY)
    if stored:
        membership = (
            Membership.objects.filter(workspace_id=stored, user=user)
            .select_related("workspace")
            .first()
        )
        if membership is not None:
            return membership.workspace, membership

    workspace = ensure_personal_workspace(user)
    membership = Membership.objects.get(workspace=workspace, user=user)
    if request.session.session_key:
        request.session[SESSION_KEY] = workspace.pk
    return workspace, membership


def workspace_for(user):
    """The workspace `user` is acting in.

    During a request this is the active workspace when `user` is the caller.
    Everywhere else (tests, signals, the migration) it is their personal one.
    """
    request = _request.get()
    if (
        request is not None
        and getattr(user, "pk", None) is not None
        and getattr(request.user, "pk", None) == user.pk
    ):
        bind_request_workspace(request)
        workspace = getattr(request, "active_workspace", None)
        if workspace is not None:
            return workspace
    return ensure_personal_workspace(user)


def active_workspace(request):
    bind_request_workspace(request)
    return request.active_workspace


def ensure_can_write(request):
    bind_request_workspace(request)
    membership = getattr(request, "workspace_membership", None)
    if membership is None or not membership.can_write():
        raise PermissionDenied


def ensure_can_admin(request):
    bind_request_workspace(request)
    membership = getattr(request, "workspace_membership", None)
    if membership is None or not membership.can_admin():
        raise PermissionDenied


def can_delete_comment(request, comment):
    """Its author can delete a comment while they can still write. An owner
    can delete any comment in the workspace."""
    bind_request_workspace(request)
    membership = getattr(request, "workspace_membership", None)
    if membership is None or not membership.can_write():
        return False
    return membership.can_admin() or comment.author_id == request.user.pk


def _membership_on(user, workspace_id):
    return Membership.objects.filter(user=user, workspace_id=workspace_id).first()


def require_write_on(user, workspace_id):
    membership = _membership_on(user, workspace_id)
    if membership is None or not membership.can_write():
        raise PermissionDenied


def require_admin_on(user, workspace_id):
    membership = _membership_on(user, workspace_id)
    if membership is None or not membership.can_admin():
        raise PermissionDenied
