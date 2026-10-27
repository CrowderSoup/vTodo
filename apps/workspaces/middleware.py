from apps.workspaces.access import bind_request, reset_request


class ActiveWorkspaceMiddleware:
    """Keep the current request available so task queries can see its workspace.

    Session login is authenticated before the view runs. API token login is
    not, so those views bind the workspace themselves once they know the user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = bind_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_request(token)
