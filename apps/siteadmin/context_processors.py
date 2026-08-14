from apps.users.selectors import is_admin


def admin_status(request):
    return {"is_site_admin": is_admin(request.user)}
