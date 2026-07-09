from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.tasks.models import Task, TaskComment, TaskStatus
from apps.tasks.selectors import (
    AssignmentError,
    assign_task,
    user_team_ids,
    visible_statuses_qs,
    visible_tasks_qs,
)
from apps.users.models import User

from .serializers import (
    TaskActivitySerializer,
    TaskCommentSerializer,
    TaskSerializer,
    TaskStatusSerializer,
    TeamSerializer,
)


class TaskStatusViewSet(viewsets.ModelViewSet):
    serializer_class = TaskStatusSerializer
    lookup_field = "slug"

    def get_queryset(self):
        team_id = self.request.query_params.get("team")
        if team_id:
            return TaskStatus.objects.filter(team_id=team_id, team_id__in=user_team_ids(self.request.user))
        return TaskStatus.objects.filter(user=self.request.user, team__isnull=True)

    def perform_create(self, serializer):
        team_id = self.request.data.get("team")
        if team_id and int(team_id) in user_team_ids(self.request.user):
            order = TaskStatus.objects.filter(team_id=team_id).count()
            serializer.save(team_id=team_id, order=order)
        else:
            order = TaskStatus.objects.filter(user=self.request.user, team__isnull=True).count()
            serializer.save(user=self.request.user, order=order)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = visible_tasks_qs(self.request.user)
        team_id = self.request.query_params.get("team")
        if team_id:
            qs = qs.filter(team_id=team_id)
        status_slug = self.request.query_params.get("status")
        if status_slug:
            qs = qs.filter(status=status_slug)
        tags = self.request.query_params.getlist("tags")
        if tags:
            matching_pks = [t.pk for t in qs if all(tag in (t.tags or []) for tag in tags)]
            qs = qs.filter(pk__in=matching_pks)
        return qs

    def perform_create(self, serializer):
        order = Task.objects.filter(user=self.request.user).count()
        serializer.save(user=self.request.user, order=order)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"new_status": {"type": "string"}}}},
        responses={200: TaskSerializer},
    )
    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        task = self.get_object()
        new_status_slug = request.data.get("new_status", "")

        task_statuses = visible_statuses_qs(request.user, team=task.team)
        valid_slugs = list(task_statuses.values_list("slug", flat=True))
        if new_status_slug not in valid_slugs:
            return Response(
                {"detail": "Invalid status slug."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        task.status = new_status_slug
        is_done = task_statuses.filter(slug=new_status_slug, is_done=True).exists()
        if is_done and not task.completed_at:
            task.completed_at = timezone.now()
        elif not is_done:
            task.completed_at = None
        task.save(update_fields=["status", "completed_at", "updated_at"])

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

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"assignee_id": {"type": "integer"}}}},
        responses={200: TaskSerializer},
    )
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        task = self.get_object()
        assignee_id = request.data.get("assignee_id")
        assignee = get_object_or_404(User, pk=assignee_id) if assignee_id else None

        try:
            assign_task(request.user, task, assignee)
        except AssignmentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        task = self.get_object()
        return Response(TaskActivitySerializer(task.activity.all(), many=True).data)


class TaskCommentViewSet(viewsets.GenericViewSet, mixins.DestroyModelMixin):
    serializer_class = TaskCommentSerializer

    def get_queryset(self):
        return TaskComment.objects.filter(task__in=visible_tasks_qs(self.request.user))


class TeamViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeamSerializer

    def get_queryset(self):
        from apps.tasks.selectors import user_teams_qs

        return user_teams_qs(self.request.user)
