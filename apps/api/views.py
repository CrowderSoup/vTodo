from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.tasks.models import Task, TaskStatus

from .serializers import TaskSerializer, TaskStatusSerializer


class TaskStatusViewSet(viewsets.ModelViewSet):
    serializer_class = TaskStatusSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return TaskStatus.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        order = TaskStatus.objects.filter(user=self.request.user).count()
        serializer.save(user=self.request.user, order=order)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Task.objects.filter(user=self.request.user)
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

        valid_slugs = list(
            TaskStatus.objects.filter(user=request.user).values_list("slug", flat=True)
        )
        if new_status_slug not in valid_slugs:
            return Response(
                {"detail": "Invalid status slug."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        task.status = new_status_slug
        is_done = TaskStatus.objects.filter(
            user=request.user, slug=new_status_slug, is_done=True
        ).exists()
        if is_done and not task.completed_at:
            task.completed_at = timezone.now()
        elif not is_done:
            task.completed_at = None
        task.save(update_fields=["status", "completed_at", "updated_at"])

        return Response(TaskSerializer(task).data)
