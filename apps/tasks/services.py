def provision_statuses(*, user=None, team=None, copy_from_user=None):
    """Seed TaskStatus rows for a new personal board or team.

    Copies copy_from_user's personal statuses (name/slug/order/color/is_done)
    if given, else seeds from DEFAULT_STATUS_DEFS. Exactly one of user/team
    must be given, matching TaskStatus's ownership constraint.
    """
    from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus

    if copy_from_user is not None:
        source_statuses = TaskStatus.objects.filter(user=copy_from_user, team__isnull=True)
        rows = [
            (status.name, status.slug, status.order, status.is_done, status.color)
            for status in source_statuses
        ]
    else:
        rows = [(name, slug, order, is_done, "") for name, slug, order, is_done in DEFAULT_STATUS_DEFS]

    for name, slug, order, is_done, color in rows:
        TaskStatus.objects.create(
            user=user,
            team=team,
            name=name,
            slug=slug,
            order=order,
            is_done=is_done,
            color=color,
        )
