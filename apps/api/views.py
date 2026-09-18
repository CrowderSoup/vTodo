from django.urls import reverse
from drf_spectacular.utils import extend_schema
from oauth2_provider.contrib.rest_framework import OAuth2Authentication, TokenHasScope
from oauth2_provider.oauth2_validators import validate_resource_as_url_prefix
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tasks.models import Task, TaskComment, TaskStatus
from apps.tasks.selectors import InvalidStatusError, move_task, visible_tasks_qs

from .serializers import TaskCommentSerializer, TaskSerializer, TaskStatusSerializer


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


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = visible_tasks_qs(self.request.user)
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
        serializer.save(user=self.request.user, order=order)

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
            move_task(request.user, task, new_status_slug)
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
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TaskCommentViewSet(viewsets.GenericViewSet, mixins.DestroyModelMixin):
    serializer_class = TaskCommentSerializer

    def get_queryset(self):
        return TaskComment.objects.filter(task__in=visible_tasks_qs(self.request.user))


def validate_whoami_resource_token(request_uri: str, audiences: list[str]) -> bool:
    """RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR (config/settings.py:OAUTH2_PROVIDER)
    for RFC 8707 resource-restricted access tokens.

    mcp_server's caller tokens are minted for its own resource identifier
    (VTODO_MCP_PUBLIC_URL, e.g. https://mcp.vtodo.crowdersoup.com/mcp), then
    handed to WhoAmIView -- on a different host entirely -- to resolve who
    they belong to. WhoAmIView isn't itself the resource those tokens were
    restricted to, so the default prefix-match audience check
    (validate_resource_as_url_prefix) rejects every one of them with
    "The access token is not valid for this resource." Exempt this one
    endpoint; everything else still gets the default check.
    """
    path = request_uri.split("?", 1)[0].rstrip("/")
    if path.endswith(reverse("mcp-whoami").rstrip("/")):
        return True
    return validate_resource_as_url_prefix(request_uri, audiences)


class WhoAmIView(APIView):
    """Resolves an OAuth access token (from a remote MCP client) to the
    caller's vtodo DRF API token, so mcp_server can call the rest of this
    API exactly as it does for stdio/local use. Deliberately the only place
    an OAuth-authenticated request ever gets a raw DRF token back."""

    authentication_classes = [OAuth2Authentication]
    permission_classes = [IsAuthenticated, TokenHasScope]
    required_scopes = ["tasks"]

    def get(self, request):
        from rest_framework.authtoken.models import Token

        token, _ = Token.objects.get_or_create(user=request.user)
        return Response(
            {
                "user_id": request.user.pk,
                "username": request.user.username,
                "api_token": token.key,
            }
        )
