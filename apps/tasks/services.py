def provision_statuses(*, user, copy_from_user=None):
    """Seed TaskStatus rows for a new personal board.

    Copies copy_from_user's statuses (name/slug/order/color/is_done) if given,
    else seeds from DEFAULT_STATUS_DEFS.
    """
    from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus

    if copy_from_user is not None:
        source_statuses = TaskStatus.objects.filter(user=copy_from_user)
        rows = [
            (status.name, status.slug, status.order, status.is_done, status.color)
            for status in source_statuses
        ]
    else:
        rows = [(name, slug, order, is_done, "") for name, slug, order, is_done in DEFAULT_STATUS_DEFS]

    for name, slug, order, is_done, color in rows:
        TaskStatus.objects.create(
            user=user,
            name=name,
            slug=slug,
            order=order,
            is_done=is_done,
            color=color,
        )
