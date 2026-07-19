from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from .models import Team, TeamInvite, TeamMembership

INVITE_RATE_LIMIT = 5
INVITE_RATE_WINDOW = 3600  # seconds (1 hour)


def _owner_membership_or_404(user, team_pk):
    return get_object_or_404(
        TeamMembership, team_id=team_pk, user=user, role=TeamMembership.ROLE_OWNER
    )


def _invite_email_matches(user, invite):
    return user.email_identities.filter(email__iexact=invite.email, verified=True).exists()


def _provision_team_statuses(team):
    """Give a new team the same starter workflow personal boards get, so it isn't
    unusable until someone visits Settings and hand-builds a status list."""
    from apps.tasks.models import DEFAULT_STATUS_DEFS, TaskStatus

    for name, slug, order, is_done in DEFAULT_STATUS_DEFS:
        TaskStatus.objects.get_or_create(
            team=team, slug=slug,
            defaults={"name": name, "order": order, "is_done": is_done},
        )


def _provision_team_board(team):
    """Create the team's shared board, with the same starter columns a new personal
    board gets, so a fresh team isn't unusable until someone visits Settings and
    hand-builds a column list. Called once, at team creation -- joining an existing
    team doesn't provision anything, since the shared board already exists."""
    from apps.boards.models import Board, Column

    board = Board.objects.create(team=team, name=team.name)
    default_columns = [
        ("Backlog",     {"statuses": ["backlog"],     "tags": [], "due": None}, 0),
        ("To Do",       {"statuses": ["todo"],         "tags": [], "due": None}, 1),
        ("In Progress", {"statuses": ["in_progress"],  "tags": [], "due": None}, 2),
        ("Done",        {"statuses": ["done"],          "tags": [], "due": None}, 3),
    ]
    for label, filter_config, order in default_columns:
        Column.objects.create(board=board, label=label, filter_config=filter_config, order=order)
    return board


def _cleanup_after_membership_removal(actor, user, team):
    """When someone leaves or is removed from a team: unassign them from that
    team's tasks (an assignee who isn't a member is a stale/invalid state — see
    AssignmentError in apps.tasks.selectors.assign_task). The team's shared board
    is untouched -- other members still need it."""
    from apps.tasks.models import Task, TaskActivity

    for task in Task.objects.filter(team=team, assignee=user):
        old_display = user.display_name or user.username
        task.assignee = None
        task.save(update_fields=["assignee", "updated_at"])
        TaskActivity.objects.create(
            task=task, actor=actor, field="assignee", old_value=old_display, new_value="Unassigned",
        )


def _cleanup_before_team_delete(team):
    """Snapshot what CASCADE is about to wipe out (Task.team is SET_NULL, so those
    tasks survive the team's deletion) so post-delete cleanup still knows which tasks
    need remapping. team.pk is reset to None by Team.delete(), so it's captured too."""
    from apps.tasks.models import Task

    return {
        "team_id": team.pk,
        "orphaned_task_ids": list(Task.objects.filter(team=team).values_list("pk", flat=True)),
    }


def _cleanup_after_team_delete(snapshot):
    """Deleting a team already CASCADEs its TaskStatus rows, Board (and that board's
    Columns/SavedFilters), and SET_NULLs Task.team (see apps/tasks/models.py and
    apps/boards/models.py). What's left: newly-personal tasks may carry a status slug
    or assignee that no longer means anything without the team."""
    from apps.tasks.models import Task, TaskStatus

    personal_statuses_by_user = {}

    def _personal_statuses(user):
        if user.pk not in personal_statuses_by_user:
            personal_statuses_by_user[user.pk] = list(
                TaskStatus.objects.filter(user=user, team__isnull=True).order_by("order")
            )
        return personal_statuses_by_user[user.pk]

    orphaned_tasks = Task.objects.filter(pk__in=snapshot["orphaned_task_ids"]).select_related(
        "user", "user__default_status"
    )
    for task in orphaned_tasks:
        update_fields = ["assignee", "updated_at"]
        task.assignee = None

        statuses = _personal_statuses(task.user)
        valid_slugs = {status.slug for status in statuses}
        if task.status not in valid_slugs:
            default = task.user.default_status
            fallback = default if default and default.slug in valid_slugs else (statuses[0] if statuses else None)
            task.status = fallback.slug if fallback else "todo"
            if not (fallback and fallback.is_done):
                task.completed_at = None
            update_fields += ["status", "completed_at"]

        task.save(update_fields=update_fields)


class TeamCreateView(LoginRequiredMixin, View):
    def post(self, request):
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Give your team a name.")
            return redirect(reverse("users:settings-teams"))

        with transaction.atomic():
            team = Team.objects.create(name=name)
            TeamMembership.objects.create(team=team, user=request.user, role=TeamMembership.ROLE_OWNER)
            _provision_team_statuses(team)
            _provision_team_board(team)

        messages.success(request, f"Created team “{team.name}”.")
        return redirect(reverse("users:settings-teams"))


class TeamInviteCreateView(LoginRequiredMixin, View):
    def post(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        team = get_object_or_404(Team, pk=team_pk)

        email = request.POST.get("email", "").strip().lower()
        if not email:
            messages.error(request, "Enter an email address to invite.")
            return redirect(reverse("users:settings-teams"))

        rate_key = f"team_invite_rate:{team_pk}:{email}"
        count = cache.get(rate_key, 0)
        if count >= INVITE_RATE_LIMIT:
            messages.error(request, "Too many invites sent to that address. Try again later.")
            return redirect(reverse("users:settings-teams"))

        invite = TeamInvite.generate(team, email, request.user)
        accept_url = request.build_absolute_uri(reverse("teams:invite-accept", args=[invite.token]))

        try:
            send_mail(
                subject=f"You've been invited to join {team.name} on vtodo",
                message=(
                    f"{request.user.display_name or request.user.username} invited you to join "
                    f"the “{team.name}” team on vtodo.\n\n"
                    f"Accept the invite: {accept_url}\n\n"
                    "This link expires in 7 days."
                ),
                from_email=None,
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception:
            messages.error(request, "Failed to send invite email. Please try again later.")
            return redirect(reverse("users:settings-teams"))

        cache.set(rate_key, count + 1, INVITE_RATE_WINDOW)
        messages.success(request, f"Invited {email} to {team.name}.")
        return redirect(reverse("users:settings-teams"))


class TeamInviteAcceptView(LoginRequiredMixin, View):
    def get(self, request, token):
        invite = get_object_or_404(TeamInvite, token=token)
        already_member = TeamMembership.objects.filter(team=invite.team, user=request.user).exists()
        email_mismatch = not already_member and not _invite_email_matches(request.user, invite)
        return render(request, "teams/invite_accept.html", {
            "invite": invite,
            "already_member": already_member,
            "email_mismatch": email_mismatch,
        })

    def post(self, request, token):
        invite = get_object_or_404(TeamInvite, token=token)
        if not invite.is_valid:
            messages.error(request, "This invite has expired or was already used.")
            return redirect(reverse("boards:board"))

        if not _invite_email_matches(request.user, invite):
            messages.error(
                request,
                f"This invite was sent to {invite.email}. Log in with that email address to accept it.",
            )
            return redirect(reverse("boards:board"))

        TeamMembership.objects.get_or_create(
            team=invite.team, user=request.user, defaults={"role": TeamMembership.ROLE_MEMBER}
        )
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])

        messages.success(request, f"You've joined {invite.team.name}.")
        return redirect(reverse("users:settings-teams"))


class TeamMemberRemoveView(LoginRequiredMixin, View):
    def post(self, request, team_pk, user_pk):
        _owner_membership_or_404(request.user, team_pk)

        with transaction.atomic():
            # Lock the team's owner rows so a concurrent remove/leave can't also
            # pass the "at least one owner remains" check before either commits.
            owner_count = (
                TeamMembership.objects.select_for_update()
                .filter(team_id=team_pk, role=TeamMembership.ROLE_OWNER)
                .count()
            )
            target = get_object_or_404(TeamMembership, team_id=team_pk, user_id=user_pk)
            if target.role == TeamMembership.ROLE_OWNER and owner_count <= 1:
                messages.error(request, "A team must have at least one owner.")
                return redirect(reverse("users:settings-teams"))

            team, target_user = target.team, target.user
            target.delete()
            _cleanup_after_membership_removal(request.user, target_user, team)

        messages.success(request, "Removed from team.")
        return redirect(reverse("users:settings-teams"))


class TeamLeaveView(LoginRequiredMixin, View):
    def post(self, request, team_pk):
        with transaction.atomic():
            membership = get_object_or_404(TeamMembership, team_id=team_pk, user=request.user)
            if membership.role == TeamMembership.ROLE_OWNER:
                owner_count = (
                    TeamMembership.objects.select_for_update()
                    .filter(team_id=team_pk, role=TeamMembership.ROLE_OWNER)
                    .count()
                )
                if owner_count <= 1:
                    messages.error(request, "Promote another member to owner before leaving.")
                    return redirect(reverse("users:settings-teams"))

            team = membership.team
            membership.delete()
            _cleanup_after_membership_removal(request.user, request.user, team)

        messages.success(request, "You left the team.")
        return redirect(reverse("users:settings-teams"))


class TeamDeleteView(LoginRequiredMixin, View):
    def post(self, request, team_pk):
        _owner_membership_or_404(request.user, team_pk)
        team = get_object_or_404(Team, pk=team_pk)
        team_name = team.name

        with transaction.atomic():
            snapshot = _cleanup_before_team_delete(team)
            team.delete()
            _cleanup_after_team_delete(snapshot)

        messages.success(request, f"Deleted team “{team_name}”.")
        return redirect(reverse("users:settings-teams"))
