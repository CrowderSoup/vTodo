from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import TaskCommentViewSet, TaskStatusViewSet, TaskViewSet, TeamViewSet, WhoAmIView

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("statuses", TaskStatusViewSet, basename="taskstatus")
router.register("comments", TaskCommentViewSet, basename="taskcomment")
router.register("teams", TeamViewSet, basename="team")

urlpatterns = [
    path("mcp/whoami/", WhoAmIView.as_view(), name="mcp-whoami"),
] + router.urls
