from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.tasks.claims import assignable_users
from apps.tasks.models import Task, TaskActivity, TaskComment, TaskStatus
from apps.users.models import User
from apps.workspaces.models import Membership


def _name(user):
    if user is None:
        return None
    return user.display_name or user.username


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
    assignee = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), allow_null=True, required=False
    )
    assignee_name = serializers.SerializerMethodField()
    # Only a live claim is shown. A lapsed one reads as unclaimed.
    claimed_by = serializers.SerializerMethodField()
    claimed_by_name = serializers.SerializerMethodField()
    claim_expires_at = serializers.SerializerMethodField()

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
            "assignee",
            "assignee_name",
            "claimed_by",
            "claimed_by_name",
            "claim_expires_at",
            "recurrence_days",
            "recurrence_from",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = ["created_at", "updated_at", "completed_at"]

    def validate_assignee(self, value):
        if value is None:
            return value
        if self.instance is not None:
            workspace = self.instance.workspace
        else:
            workspace = self.context["request"].active_workspace
        if not assignable_users(workspace).filter(pk=value.pk).exists():
            raise serializers.ValidationError(
                "Assign someone who can change this workspace's tasks, or one of their agents."
            )
        return value

    def get_assignee_name(self, obj) -> str | None:
        return _name(obj.assignee)

    def _live_claim(self, obj):
        return obj.active_claim_holder_id() is not None

    def get_claimed_by(self, obj) -> int | None:
        return obj.claimed_by_id if self._live_claim(obj) else None

    def get_claimed_by_name(self, obj) -> str | None:
        return _name(obj.claimed_by) if self._live_claim(obj) else None

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_claim_expires_at(self, obj):
        if not self._live_claim(obj):
            return None
        return serializers.DateTimeField().to_representation(obj.claim_expires_at)


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
        return _name(obj.actor)


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

    def get_can_write(self, obj) -> bool:
        return obj.can_write()

    def get_can_admin(self, obj) -> bool:
        return obj.can_admin()


class AssigneeSerializer(serializers.ModelSerializer):
    """Someone a task in the active workspace can be assigned to."""

    name = serializers.SerializerMethodField()
    parent = serializers.IntegerField(source="parent_id", read_only=True)

    class Meta:
        model = User
        fields = ["id", "name", "kind", "parent"]
        read_only_fields = fields

    def get_name(self, obj) -> str:
        return _name(obj)
