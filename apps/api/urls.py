from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    GoogleSignInView,
    SignOutView,
    TaskCommentViewSet,
    TaskStatusViewSet,
    TaskViewSet,
    WhoAmIView,
)

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("statuses", TaskStatusViewSet, basename="taskstatus")
router.register("comments", TaskCommentViewSet, basename="taskcomment")

urlpatterns = [
    path("auth/google/", GoogleSignInView.as_view(), name="google-sign-in"),
    path("auth/sign-out/", SignOutView.as_view(), name="sign-out"),
    path("mcp/whoami/", WhoAmIView.as_view(), name="mcp-whoami"),
] + router.urls
