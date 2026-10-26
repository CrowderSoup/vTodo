from rest_framework import serializers

from apps.tasks.models import Task, TaskActivity, TaskComment, TaskStatus


class TaskStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskStatus
        fields = ["id", "name", "slug", "order", "color", "is_done"]
        read_only_fields = ["slug"]


class TaskCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskComment
        fields = ["id", "task", "author", "body", "created_at"]
        read_only_fields = ["author", "created_at"]


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
            "due_time",
            "duration_minutes",
            "tags",
            "is_archived",
            "recurrence_days",
            "recurrence_from",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = ["created_at", "updated_at", "completed_at"]


class TaskActivitySerializer(serializers.ModelSerializer):
    task = serializers.IntegerField(source="task_pk", read_only=True)
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskActivity
        fields = [
            "id", "task", "actor", "actor_name", "source", "action",
            "field", "old_value", "new_value", "created_at",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor is None:
            return None
        return obj.actor.display_name or obj.actor.username
