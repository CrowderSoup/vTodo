from rest_framework import serializers

from apps.tasks.models import Task, TaskStatus


class TaskStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskStatus
        fields = ["id", "name", "slug", "order", "color", "is_done"]
        read_only_fields = ["slug"]


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "notes",
            "status",
            "order",
            "due_date",
            "tags",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = ["created_at", "updated_at", "completed_at"]
