from apps.users.selectors import gravatar_url


def avatar_status(request):
    return {"gravatar_url": gravatar_url(request.user)}
