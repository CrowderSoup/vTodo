from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from oauth2_provider.contrib.rest_framework import OAuth2Authentication, TokenHasScope
from oauth2_provider.oauth2_validators import validate_resource_as_url_prefix
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
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
from apps.tasks.models import Task, TaskActivity, TaskComment, TaskStatus
from apps.tasks.selectors import (
    InvalidStatusError,
    default_status_slug,
    move_task,
    visible_statuses_qs,
    visible_tasks_qs,
)

from .models import DeviceToken
from .serializers import TaskActivitySerializer, TaskCommentSerializer, TaskSerializer, TaskStatusSerializer


class TaskStatusViewSet(viewsets.ModelViewSet):
    serializer_class = TaskStatusSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return TaskStatus.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        order = TaskStatus.objects.filter(user=self.request.user).count()
        serializer.save(user=self.request.user, order=order)

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
            owns_scope = all(s.user_id == request.user.id for s in statuses.values())
            if not owns_scope:
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
        ],
    ),
)
class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = visible_tasks_qs(self.request.user)
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
        order = Task.objects.filter(user=self.request.user).count()
        extra = {}
        if "status" not in serializer.validated_data:
            extra["status"] = default_status_slug(self.request.user)
        with transaction.atomic():
            task = serializer.save(user=self.request.user, order=order, **extra)
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
        rows = TaskActivity.objects.filter(user=request.user, task_pk=task_pk).select_related("actor")
        if not rows.exists() and not visible_tasks_qs(request.user).filter(pk=task_pk).exists():
            raise NotFound()
        return Response(TaskActivitySerializer(rows, many=True).data)


class TaskCommentViewSet(viewsets.GenericViewSet, mixins.DestroyModelMixin):
    serializer_class = TaskCommentSerializer

    def get_queryset(self):
        return TaskComment.objects.filter(task__in=visible_tasks_qs(self.request.user))

    def perform_destroy(self, instance):
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
    """Exchange a Google ID token for the account's DRF API token.

    The Android app uses this so a person can sign in with Google instead of
    pasting the token from Settings. The token it returns is that same DRF
    token. This is not the MCP OAuth server (django-oauth-toolkit stays for
    remote MCP clients only).
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
