from django.shortcuts import get_object_or_404

from .models import Board


def resolve_board(user):
    return get_object_or_404(Board, user=user)


def user_can_access_board(user, board):
    return board.user_id == user.id
