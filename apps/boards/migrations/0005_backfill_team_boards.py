from django.db import migrations

DEFAULT_COLUMNS = [
    ("Backlog", {"statuses": ["backlog"], "tags": [], "due": None}, 0),
    ("To Do", {"statuses": ["todo"], "tags": [], "due": None}, 1),
    ("In Progress", {"statuses": ["in_progress"], "tags": [], "due": None}, 2),
    ("Done", {"statuses": ["done"], "tags": [], "due": None}, 3),
]


def backfill_team_boards(apps, schema_editor):
    """Give every existing Team its own shared Board.

    Before this migration, "team columns" were duplicated per member: each user who
    created or joined a team got their own independently-editable Column (tagged
    filter_config.scope == "team:<id>") sitting on their personal Board. Now that
    team boards are shared, each Team needs exactly one Board.

    Column-selection rule (deterministic, but a real one-time data-loss point --
    acceptable here because per-member team column customization was a rarely-used
    side effect of the old scoped-column design, not a feature anyone relied on):
    prefer the earliest-created owner's team-scoped columns; fall back to the
    earliest-created member's; if nobody has any, seed the same default columns a
    new personal board gets. Every other member's now-orphaned copy is discarded --
    any per-member customization on a non-chosen copy (custom statuses/tags/assignee
    filter/label) does not survive the migration.
    """
    Team = apps.get_model("teams", "Team")
    TeamMembership = apps.get_model("teams", "TeamMembership")
    Board = apps.get_model("boards", "Board")
    Column = apps.get_model("boards", "Column")

    for team in Team.objects.all():
        team_board, created = Board.objects.get_or_create(team=team, defaults={"name": team.name})
        if not created:
            continue

        scope = f"team:{team.pk}"
        memberships = list(TeamMembership.objects.filter(team=team))
        owners = sorted((m for m in memberships if m.role == "owner"), key=lambda m: (m.joined_at, m.pk))
        others = sorted((m for m in memberships if m.role != "owner"), key=lambda m: (m.joined_at, m.pk))

        chosen_columns = []
        for membership in owners + others:
            candidates = list(
                Column.objects.filter(board__user_id=membership.user_id, filter_config__scope=scope).order_by("order")
            )
            if candidates:
                chosen_columns = candidates
                break

        if chosen_columns:
            for order, column in enumerate(chosen_columns):
                filter_config = dict(column.filter_config or {})
                filter_config.pop("scope", None)
                column.board_id = team_board.pk
                column.filter_config = filter_config
                column.order = order
                column.save(update_fields=["board", "filter_config", "order"])
        else:
            for label, filter_config, order in DEFAULT_COLUMNS:
                Column.objects.create(board=team_board, label=label, filter_config=filter_config, order=order)

        # Every other member's leftover team-scoped column(s) for this team are dead --
        # they can never be reached through the new per-team board UI.
        Column.objects.filter(
            board__user_id__in=[m.user_id for m in memberships], filter_config__scope=scope
        ).delete()

    # "all"-scoped columns showed personal and team tasks mixed in one lane; that union
    # view is now provided by switching between board tabs, so fold them back onto
    # whichever (personal) board they're on as ordinary, unscoped columns. This loop
    # also strips any stray "scope" key from every other column as a final normalization.
    for column in Column.objects.all():
        filter_config = column.filter_config or {}
        if "scope" in filter_config:
            filter_config = dict(filter_config)
            filter_config.pop("scope", None)
            column.filter_config = filter_config
            column.save(update_fields=["filter_config"])


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0004_board_team_and_nullable_user"),
        ("teams", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_team_boards, migrations.RunPython.noop),
    ]
