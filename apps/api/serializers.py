from rest_framework import serializers

from apps.tasks.models import Task, TaskActivity, TaskComment, TaskStatus
from apps.workspaces.models import Membership


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


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    """One of the caller's workspaces, seen through their membership."""

    id = serializers.IntegerField(source="workspace_id", read_only=True)
    name = serializers.CharField(source="workspace.name", read_only=True)
    kind = serializers.CharField(source="workspace.kind", read_only=True)
    can_write = serializers.SerializerMethodField()
    can_admin = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "name", "kind", "role", "can_write", "can_admin"]
        read_only_fields = fields

    def get_can_write(self, obj):
        return obj.can_write()

    def get_can_admin(self, obj):
        return obj.can_admin()
