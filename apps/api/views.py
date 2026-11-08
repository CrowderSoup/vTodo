from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from oauth2_provider.contrib.rest_framework import OAuth2Authentication, TokenHasScope
from oauth2_provider.oauth2_validators import validate_resource_as_url_prefix
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.google_accounts import (
    AccountDisabled,
    GoogleSignInError,
    GoogleSignInNotConfigured,
    GoogleUnavailable,
    InvalidGoogleIdToken,
    SignupClosed,
    UnverifiedGoogleEmail,
    sign_in_with_google_id_token,
)
from apps.tasks import activity
from apps.tasks.activity import source_for_request
from apps.tasks.claims import (
    ClaimConflict,
    assignable_users,
    claim_next_task,
    claim_task,
    lease_from,
    release_task,
)
from apps.tasks.models import Task, TaskActivity, TaskComment, TaskStatus
from apps.tasks.selectors import (
    InvalidStatusError,
    default_status_slug,
    move_task,
    visible_statuses_qs,
    visible_tasks_qs,
)
from apps.workspaces.access import can_delete_comment, memberships_for

from .models import DeviceToken
from .permissions import OAuthTokenHasTasksScope, WorkspaceRolePermission
from .serializers import (
    AssigneeSerializer,
    TaskActivitySerializer,
    TaskCommentSerializer,
    TaskSerializer,
    TaskStatusSerializer,
    WorkspaceMembershipSerializer,
)

WORKSPACE_PERMISSIONS = [IsAuthenticated, OAuthTokenHasTasksScope, WorkspaceRolePermission]


class WorkspaceViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """The workspaces the caller belongs to, with their role in each. Send a
    workspace's id as X-Workspace-Id to act in it. Without that header, API
    calls use the caller's personal workspace."""

    serializer_class = WorkspaceMembershipSerializer
    permission_classes = [IsAuthenticated, OAuthTokenHasTasksScope]

    def get_queryset(self):
        # Personal first, then shared workspaces by name.
        return sorted(
            memberships_for(self.request.user),
            key=lambda m: (m.workspace.kind, m.workspace.name, m.workspace_id),
        )


class AssigneeViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """People and agents a task in the active workspace can be assigned to:
    everyone who can change its tasks, and their agents."""

    serializer_class = AssigneeSerializer
    permission_classes = WORKSPACE_PERMISSIONS

    def get_queryset(self):
        return assignable_users(self.request.active_workspace)


class TaskStatusViewSet(viewsets.ModelViewSet):
    serializer_class = TaskStatusSerializer
    lookup_field = "slug"
    permission_classes = WORKSPACE_PERMISSIONS
    workspace_admin = True

    def get_queryset(self):
        return TaskStatus.objects.filter(workspace=self.request.active_workspace)

    def perform_create(self, serializer):
        workspace = self.request.active_workspace
        order = TaskStatus.objects.filter(workspace=workspace).count()
        serializer.save(user=self.request.user, workspace=workspace, order=order)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "integer"}}}}},
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def reorder(self, request):
        order = request.data.get("order")
        if not isinstance(order, list):
            return Response({"detail": "order must be a list of status IDs."}, status=status.HTTP_400_BAD_REQUEST)

        statuses = {s.pk: s for s in TaskStatus.objects.filter(pk__in=order)}
        if statuses:
            workspace_id = request.active_workspace.pk
            if any(s.workspace_id != workspace_id for s in statuses.values()):
                return Response(status=status.HTTP_403_FORBIDDEN)

        for i, pk in enumerate(order):
            if pk in statuses:
                statuses[pk].order = i
                statuses[pk].save(update_fields=["order"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "open",
                bool,
                description=(
                    "Only tasks still to do: not archived, not completed, and not in a "
                    "done status. The Android app syncs just these."
                ),
            ),
            OpenApiParameter(
                "assignee",
                str,
                description='A user id, "me" for the caller, or "none" for unassigned tasks.',
            ),
            OpenApiParameter(
                "claimable",
                bool,
                description="Only tasks nobody holds a live claim on.",
            ),
        ],
    ),
)
class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = WORKSPACE_PERMISSIONS

    def get_queryset(self):
        qs = visible_tasks_qs(self.request.user).select_related("assignee", "claimed_by")
        assignee = self.request.query_params.get("assignee", "").strip().lower()
        if assignee == "me":
            qs = qs.filter(assignee=self.request.user)
        elif assignee == "none":
            qs = qs.filter(assignee__isnull=True)
        elif assignee.isdigit():
            qs = qs.filter(assignee_id=int(assignee))
        elif assignee:
            raise ValidationError({"assignee": ['Use a user id, "me" or "none".']})
        if self.request.query_params.get("claimable") in ("1", "true"):
            now = timezone.now()
            qs = qs.filter(
                Q(claimed_by__isnull=True) | Q(claim_expires_at__isnull=True) | Q(claim_expires_at__lte=now)
            )
        if self.request.query_params.get("open") in ("1", "true"):
            done_slugs = visible_statuses_qs(self.request.user).filter(is_done=True).values("slug")
            qs = qs.filter(is_archived=False, completed_at__isnull=True).exclude(status__in=done_slugs)
        status_slug = self.request.query_params.get("status")
        if status_slug:
            qs = qs.filter(status=status_slug)
        tags = self.request.query_params.getlist("tags")
        if tags:
            matching_pks = [t.pk for t in qs if all(tag in (t.tags or []) for tag in tags)]
            qs = qs.filter(pk__in=matching_pks)
        exclude_tags = self.request.query_params.getlist("exclude_tags")
        if exclude_tags:
            excluded_pks = [t.pk for t in qs if any(tag in (t.tags or []) for tag in exclude_tags)]
            qs = qs.exclude(pk__in=excluded_pks)
        return qs

    def perform_create(self, serializer):
        workspace = self.request.active_workspace
        order = Task.objects.filter(workspace=workspace).count()
        extra = {}
        if "status" not in serializer.validated_data:
            extra["status"] = default_status_slug(self.request.user)
        with transaction.atomic():
            task = serializer.save(
                user=self.request.user, workspace=workspace, order=order, **extra
            )
            activity.record_created(task, actor=self.request.user, source=source_for_request(self.request))

    def perform_update(self, serializer):
        # A status change has to go through move_task so completing a task
        # sets completed_at / previous_status and spawns the next recurrence,
        # the same as the board and the move action. Saving `status` as a
        # plain field skipped all of that (e.g. the MCP's update_task).
        new_status = serializer.validated_data.pop("status", None)
        source = source_for_request(self.request)
        with transaction.atomic():
            before = activity.snapshot(serializer.instance)
            task = serializer.save()
            activity.record_changes(task, before, actor=self.request.user, source=source)
            if new_status is not None and new_status != task.status:
                try:
                    move_task(self.request.user, task, new_status, source=source)
                except InvalidStatusError as e:
                    raise ValidationError({"status": [str(e)]})

    def perform_destroy(self, instance):
        with transaction.atomic():
            activity.record_deleted(instance, actor=self.request.user, source=source_for_request(self.request))
            instance.delete()

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "integer"}}}}},
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def reorder(self, request):
        order = request.data.get("order")
        if not isinstance(order, list):
            return Response({"detail": "order must be a list of task IDs."}, status=status.HTTP_400_BAD_REQUEST)

        tasks = {t.pk: t for t in visible_tasks_qs(request.user).filter(pk__in=order)}
        for i, pk in enumerate(order):
            if pk in tasks:
                tasks[pk].order = i
                tasks[pk].save(update_fields=["order"])

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"new_status": {"type": "string"}}}},
        responses={200: TaskSerializer},
    )
    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        task = self.get_object()
        new_status_slug = request.data.get("new_status", "")

        try:
            move_task(request.user, task, new_status_slug, source=source_for_request(request))
        except InvalidStatusError:
            return Response(
                {"detail": "Invalid status slug."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        return Response(TaskSerializer(task).data)

    def _lease(self, request):
        data = request.data if hasattr(request.data, "get") else {}
        try:
            return lease_from(data.get("lease_seconds"))
        except ValueError as e:
            raise ValidationError({"lease_seconds": [str(e)]})

    def _conflict(self, exc):
        return Response(
            {
                "detail": str(exc),
                "claimed_by": exc.task.claimed_by_id,
                "claim_expires_at": exc.task.claim_expires_at,
            },
            status=status.HTTP_409_CONFLICT,
        )

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"lease_seconds": {"type": "integer"}}}},
        responses={200: TaskSerializer, 409: None},
    )
    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        """Claim this task for lease_seconds (default 900, 30 to 86400), or
        renew your own claim. 409 while someone else holds it."""
        task = self.get_object()
        lease = self._lease(request)
        try:
            claim_task(task, request.user, lease=lease, source=source_for_request(request))
        except ClaimConflict as exc:
            return self._conflict(exc)
        return Response(TaskSerializer(task).data)

    @extend_schema(request=None, responses={200: TaskSerializer, 409: None})
    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        """Drop the claim on this task. A person may release anyone's claim;
        an agent only its own."""
        task = self.get_object()
        try:
            release_task(task, request.user, source=source_for_request(request))
        except ClaimConflict as exc:
            return self._conflict(exc)
        return Response(TaskSerializer(task).data)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"lease_seconds": {"type": "integer"}}}},
        responses={200: TaskSerializer, 204: None},
    )
    @action(detail=False, methods=["post"], url_path="claim-next", url_name="claim-next")
    def claim_next(self, request):
        """Claim the next open task assigned to you that nobody holds, in board
        order. 204 when there is none. Agents poll this for work."""
        lease = self._lease(request)
        task = claim_next_task(
            request.user, request.active_workspace, lease=lease, source=source_for_request(request)
        )
        if task is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        task = self.get_object()
        if request.method == "GET":
            return Response(TaskCommentSerializer(task.comments.all(), many=True).data)
        serializer = TaskCommentSerializer(data={**request.data, "task": task.pk})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            comment = serializer.save(author=request.user)
            activity.record_comment(
                comment, TaskActivity.COMMENTED, actor=request.user, source=source_for_request(request)
            )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: TaskActivitySerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="activity", url_name="activity")
    def activity_log(self, request, pk=None):
        """Read-only change history for a task, oldest first. Still answers
        after the task is deleted: rows are looked up by the requester and
        task_pk, not through the task."""
        try:
            task_pk = int(pk)
        except (TypeError, ValueError):
            raise NotFound()
        rows = TaskActivity.objects.filter(
            workspace=request.active_workspace, task_pk=task_pk
        ).select_related("actor")
        if not rows.exists() and not visible_tasks_qs(request.user).filter(pk=task_pk).exists():
            raise NotFound()
        return Response(TaskActivitySerializer(rows, many=True).data)


class TaskCommentViewSet(viewsets.GenericViewSet, mixins.DestroyModelMixin):
    serializer_class = TaskCommentSerializer
    permission_classes = WORKSPACE_PERMISSIONS

    def get_queryset(self):
        return TaskComment.objects.filter(task__in=visible_tasks_qs(self.request.user))

    def perform_destroy(self, instance):
        if not can_delete_comment(self.request, instance):
            raise PermissionDenied("Only its author or an owner can delete this comment.")
        with transaction.atomic():
            activity.record_comment(
                instance, TaskActivity.COMMENT_DELETED,
                actor=self.request.user, source=source_for_request(self.request),
            )
            instance.delete()


def validate_api_resource_token(request_uri: str, audiences: list[str]) -> bool:
    """RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR (config/settings.py:OAUTH2_PROVIDER)
    for RFC 8707 resource-restricted access tokens.

    mcp_server's callers get tokens minted for its own resource identifier
    (VTODO_MCP_PUBLIC_URL, e.g. https://mcp.vtodo.crowdersoup.com/mcp), and it
    forwards them to this API on a different host. The default prefix match
    (validate_resource_as_url_prefix) rejects those, so also accept exactly
    that audience, and only under /api/v1/. A token restricted to any other
    resource still gets the default check.
    """
    if validate_resource_as_url_prefix(request_uri, audiences):
        return True
    mcp_resource = settings.VTODO_MCP_RESOURCE_URL
    if not mcp_resource or mcp_resource not in audiences:
        return False
    path = urlsplit(request_uri).path
    return path.startswith(reverse("api-root"))


class GoogleSignInView(APIView):
    """Exchange a Google ID token for a new device token.

    The Android app uses this so a person can sign in with Google instead of
    pasting the token from Settings. Each sign-in gets its own token. That
    token is not the Settings → API token, and this is not the MCP OAuth
    server (django-oauth-toolkit stays for remote MCP clients only).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "google_sign_in"

    def get_throttles(self):
        # The GET only reads a setting. The POST makes an outbound call to
        # Google and can create an account, so that is what gets limited.
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return []

    @extend_schema(
        responses={200: {"type": "object", "properties": {"client_id": {"type": "string"}}}},
    )
    def get(self, request):
        client_id = settings.GOOGLE_CLIENT_ID
        if not client_id:
            return Response(
                {"detail": "Google sign-in is not configured on this server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"client_id": client_id})

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {"id_token": {"type": "string"}, "device_name": {"type": "string"}},
            }
        },
        responses={200: {"type": "object", "properties": {"token": {"type": "string"}}}},
    )
    def post(self, request):
        data = request.data if hasattr(request.data, "get") else {}
        raw = data.get("id_token")
        device_name = data.get("device_name")
        if not isinstance(device_name, str):
            device_name = ""
        try:
            token = sign_in_with_google_id_token(raw, device_name)
        except GoogleSignInNotConfigured as exc:
            return Response({"detail": exc.message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except GoogleUnavailable as exc:
            return Response({"detail": exc.message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except InvalidGoogleIdToken as exc:
            return Response({"detail": exc.message}, status=status.HTTP_401_UNAUTHORIZED)
        except (UnverifiedGoogleEmail, SignupClosed, AccountDisabled) as exc:
            return Response({"detail": exc.message}, status=status.HTTP_403_FORBIDDEN)
        except GoogleSignInError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"token": token})


class SignOutView(APIView):
    """Revoke the device token this request was made with. The Android app
    calls it on sign-out. A request made with the Settings → API token is a
    no-op: that token is shared with other clients and is only replaced from
    Settings."""

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        if isinstance(request.auth, DeviceToken):
            request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WhoAmIView(APIView):
    """Tells mcp_server which vtodo account an OAuth access token (from a
    remote MCP client) belongs to. mcp_server then calls the rest of this API
    with that same token. It never hands back a DRF API token: a short-lived,
    revocable OAuth grant must not turn into a permanent credential."""

    authentication_classes = [OAuth2Authentication]
    permission_classes = [IsAuthenticated, TokenHasScope]
    required_scopes = ["tasks"]

    def get(self, request):
        return Response({"user_id": request.user.pk, "username": request.user.username})
