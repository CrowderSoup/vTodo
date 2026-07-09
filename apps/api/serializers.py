from rest_framework import serializers

from apps.tasks.models import Task, TaskActivity, TaskComment, TaskStatus
from apps.teams.models import Team


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name", "created_at"]


class TaskStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskStatus
        fields = ["id", "name", "slug", "order", "color", "is_done"]
        read_only_fields = ["slug"]


class TaskCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskComment
        fields = ["id", "task", "body", "created_at"]
        read_only_fields = ["created_at"]


class TaskActivitySerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskActivity
        fields = ["id", "field", "old_value", "new_value", "actor_name", "created_at"]

    def get_actor_name(self, obj):
        if obj.actor is None:
            return None
        return obj.actor.display_name or obj.actor.username


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
            "team",
            "assignee",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = ["created_at", "updated_at", "completed_at", "assignee"]

    def validate_team(self, team):
        if team is None:
            return team
        request = self.context.get("request")
        if request is None or not team.memberships.filter(user=request.user).exists():
            raise serializers.ValidationError("You are not a member of this team.")
        return team
