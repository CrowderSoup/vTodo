def provision_statuses(*, user, workspace=None, copy_from_user=None):
    """Seed TaskStatus rows for a workspace.

    Copies the personal statuses of copy_from_user (name/slug/order/color/is_done)
    if given, else seeds from DEFAULT_STATUS_DEFS. `workspace` defaults to the
    user's personal workspace.
    """
    from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus
    from apps.workspaces.models import Workspace
    from apps.workspaces.services import ensure_personal_workspace

    if workspace is None:
        workspace = ensure_personal_workspace(user)

    if copy_from_user is not None:
        source_statuses = TaskStatus.objects.filter(
            user=copy_from_user,
            workspace__owner=copy_from_user,
            workspace__kind=Workspace.KIND_PERSONAL,
        )
        rows = [
            (status.name, status.slug, status.order, status.is_done, status.color)
            for status in source_statuses
        ]
    else:
        rows = [(name, slug, order, is_done, "") for name, slug, order, is_done in DEFAULT_STATUS_DEFS]

    for name, slug, order, is_done, color in rows:
        TaskStatus.objects.create(
            user=user,
            workspace=workspace,
            name=name,
            slug=slug,
            order=order,
            is_done=is_done,
            color=color,
        )
