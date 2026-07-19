from django.shortcuts import get_object_or_404

from .models import Board


def resolve_board(user, team_id=None):
    """The personal board (team_id is None) or a team board the user belongs to.
    404s if team_id names a team the user isn't a member of."""
    from apps.tasks.selectors import user_teams_qs

    if team_id is None:
        return get_object_or_404(Board, user=user)
    team = get_object_or_404(user_teams_qs(user), pk=team_id)
    return get_object_or_404(Board, team=team)


def user_can_access_board(user, board):
    from apps.tasks.selectors import user_teams_qs

    if board.user_id == user.id:
        return True
    return bool(board.team_id and user_teams_qs(user).filter(pk=board.team_id).exists())
