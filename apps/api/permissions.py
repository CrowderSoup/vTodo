from oauth2_provider.models import get_access_token_model
from rest_framework.permissions import SAFE_METHODS, BasePermission

AccessToken = get_access_token_model()

TASKS_SCOPE = "tasks"


class OAuthTokenHasTasksScope(BasePermission):
    """Requests authenticated by an OAuth access token need the `tasks` scope.

    DRF-token and session requests pass through here; IsAuthenticated still
    covers them. OAuth tokens reach the API when mcp_server forwards a remote
    MCP client's token (see validate_api_resource_token in views.py).
    """

    def has_permission(self, request, view):
        if isinstance(request.auth, AccessToken):
            return request.auth.is_valid([TASKS_SCOPE])
        return True


class WorkspaceRolePermission(BasePermission):
    """Viewers can read a workspace. Members can change its tasks. Owners can
    change its statuses. The workspace is the session one, or X-Workspace-Id."""

    message = "You can't change this workspace."

    def has_permission(self, request, view):
        from apps.workspaces.access import bind_request_workspace

        bind_request_workspace(request)
        if request.method in SAFE_METHODS:
            return True
        membership = getattr(request, "workspace_membership", None)
        if membership is None:
            return False
        if getattr(view, "workspace_admin", False):
            return membership.can_admin()
        return membership.can_write()
