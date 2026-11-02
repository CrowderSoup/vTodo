from django.shortcuts import get_object_or_404

from apps.workspaces.access import workspace_for
from apps.workspaces.models import Membership

from .models import Board


def resolve_board(user):
    return get_object_or_404(Board, workspace=workspace_for(user))


def user_can_access_board(user, board):
    return Membership.objects.filter(user=user, workspace_id=board.workspace_id).exists()
