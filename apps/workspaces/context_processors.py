from apps.workspaces.access import bind_request_workspace
from apps.workspaces.models import Membership, Workspace


def workspace_nav(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {}
    bind_request_workspace(request)
    workspace = getattr(request, "active_workspace", None)
    membership = getattr(request, "workspace_membership", None)
    if workspace is None or membership is None:
        return {}
    return {
        "active_workspace": workspace,
        "workspace_membership": membership,
        "workspaces": Workspace.objects.filter(memberships__user=user).order_by("kind", "name"),
        "can_write_workspace": membership.can_write(),
        "can_admin_workspace": membership.can_admin(),
        "workspace_role_choices": Membership.ROLE_CHOICES,
    }
