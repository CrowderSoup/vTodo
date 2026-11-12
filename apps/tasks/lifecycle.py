"""The task lifecycle state machine.

A task is OPEN, DONE or ARCHIVED (Task.state):

            complete
    OPEN ─────────────▶ DONE
         ◀─────────────
             reopen

    archive: OPEN or DONE ──▶ ARCHIVED
    unarchive: ARCHIVED ──▶ whichever of OPEN / DONE it was

Completion follows the status column. A task is DONE exactly when its status
is a done status (TaskStatus.is_done), and `completed_at` records that. Moving
into a done status completes the task, moving out of one reopens it, and
moving between two of the same kind (Done -> Shipped, To Do -> Doing) changes
neither. Archiving is a flag laid over that: an archived task keeps its
completion, so unarchiving puts it back where it was.

Only this module writes `completed_at` and `previous_status`. Every path that
changes a task's status, or what its status means, comes through here:

- start():            a task was just created, possibly straight into Done.
- enter_status():     a task moves to another status (via move_task).
- status_redefined(): a status was flipped to or from is_done.
- restore():          an import sets a task's status from a file.
"""

import enum

from django.utils import timezone


class Transition(enum.Enum):
    COMPLETE = "complete"
    REOPEN = "reopen"
    STAY = "stay"


def transition_for(task, *, to_done):
    """What moving `task` into a status with is_done=`to_done` does."""
    was_done = task.completed_at is not None
    if to_done and not was_done:
        return Transition.COMPLETE
    if was_done and not to_done:
        return Transition.REOPEN
    return Transition.STAY


def _complete(task, *, came_from, now):
    task.completed_at = now
    task.previous_status = came_from
    _drop_claim(task)


def _drop_claim(task):
    # Finished work needs no one holding it.
    task.claimed_by = None
    task.claim_expires_at = None


def _reopen(task):
    task.completed_at = None
    task.previous_status = ""


# The fields enter_status() may change, for save(update_fields=...).
ENTER_STATUS_FIELDS = ["status", "completed_at", "previous_status", "claimed_by", "claim_expires_at"]


def enter_status(task, slug, *, to_done, now=None):
    """Put `task` in status `slug` and apply the transition that implies.
    Does not save. Returns the Transition."""
    transition = transition_for(task, to_done=to_done)
    came_from = task.status
    task.status = slug
    if transition is Transition.COMPLETE:
        _complete(task, came_from=came_from, now=now or timezone.now())
    elif transition is Transition.REOPEN:
        _reopen(task)
    elif to_done:
        _drop_claim(task)
    return transition


def start(task):
    """Bring a just-created task into the state its status implies. A task
    created straight into a done column is DONE from the start. It has no
    earlier column to go back to, so reopening uses the board's default."""
    from apps.tasks.models import TaskStatus

    to_done = TaskStatus.objects.filter(
        workspace_id=task.workspace_id, slug=task.status, is_done=True
    ).exists()
    if transition_for(task, to_done=to_done) is Transition.COMPLETE:
        _complete(task, came_from="", now=task.created_at or timezone.now())
        task.save(update_fields=ENTER_STATUS_FIELDS)
    return task


def restore(task, slug, *, to_done, completed_at=None):
    """An import (apps/tasks/ical_import.py) puts `task` in status `slug` as
    a file recorded it. Like status_redefined(), this restores a state rather
    than doing the work, so the caller spawns no recurrence. A done task takes
    the completion time from the file when it has one. Works on an unsaved
    task too, which has no earlier column to go back to. Does not save."""
    came_from = task.status if task.pk else ""
    transition = enter_status(task, slug, to_done=to_done)
    if transition is Transition.COMPLETE:
        task.previous_status = came_from
    if to_done and completed_at is not None:
        task.completed_at = completed_at
    return transition


def status_redefined(status):
    """`status` was flipped to or from is_done. Its tasks follow: they become
    DONE or OPEN with it. This changes what the column means, not anyone's
    work, so no recurrence is spawned and no history row is written."""
    from apps.tasks.models import Task

    tasks = Task.objects.filter(workspace_id=status.workspace_id, status=status.slug)
    if status.is_done:
        tasks.filter(completed_at__isnull=True).update(
            completed_at=timezone.now(), previous_status="", claimed_by=None, claim_expires_at=None
        )
    else:
        tasks.filter(completed_at__isnull=False).update(completed_at=None, previous_status="")
