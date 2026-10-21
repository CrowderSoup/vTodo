from oauth2_provider.models import get_access_token_model
from rest_framework.permissions import BasePermission

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
