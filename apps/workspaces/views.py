from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.workspaces.access import SESSION_KEY, active_workspace, ensure_can_admin
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.services import (
    MemberError,
    add_workspace_member,
    create_shared_workspace,
    remove_workspace_member,
    set_member_role,
)


def _safe_next(request):
    next_url = request.POST.get("next", "")
    if not next_url.startswith("/") or next_url.startswith("//"):
        return reverse("boards:board")
    return next_url


class SwitchWorkspaceView(LoginRequiredMixin, View):
    def post(self, request):
        raw = request.POST.get("workspace", "")
        if not raw.isdigit():
            raise Http404("No such workspace.")
        membership = Membership.objects.filter(user=request.user, workspace_id=int(raw)).first()
        if membership is None:
            raise Http404("No such workspace.")
        request.session[SESSION_KEY] = membership.workspace_id
        return redirect(_safe_next(request))


class CreateWorkspaceView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "workspaces/create.html", {"name": ""})

    def post(self, request):
        name = request.POST.get("name", "")
        try:
            workspace = create_shared_workspace(user=request.user, name=name)
        except ValidationError as exc:
            message = exc.messages[0] if getattr(exc, "messages", None) else "Give the workspace a name."
            return render(request, "workspaces/create.html", {"name": name.strip(), "error": message})
        request.session[SESSION_KEY] = workspace.pk
        messages.success(request, f"Created {workspace.name}.")
        return redirect("boards:board")


class MemberAddView(LoginRequiredMixin, View):
    def post(self, request):
        ensure_can_admin(request)
        workspace = active_workspace(request)
        if workspace.kind != Workspace.KIND_SHARED:
            messages.error(request, "People can only be added to a shared workspace.")
            return redirect("users:settings-board")
        try:
            add_workspace_member(
                workspace=workspace,
                email=request.POST.get("email", ""),
                role=request.POST.get("role", Membership.ROLE_MEMBER),
            )
        except MemberError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Added them to the workspace.")
        return redirect("users:settings-board")


class MemberRoleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ensure_can_admin(request)
        workspace = active_workspace(request)
        membership = get_object_or_404(Membership, pk=pk, workspace=workspace)
        try:
            set_member_role(membership=membership, role=request.POST.get("role", ""))
        except MemberError as exc:
            messages.error(request, str(exc))
        return redirect("users:settings-board")


class MemberRemoveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ensure_can_admin(request)
        workspace = active_workspace(request)
        membership = get_object_or_404(Membership, pk=pk, workspace=workspace)
        try:
            remove_workspace_member(membership=membership)
        except MemberError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Removed them from the workspace.")
        return redirect("users:settings-board")
