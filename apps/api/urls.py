from rest_framework.routers import DefaultRouter

from .views import TaskCommentViewSet, TaskStatusViewSet, TaskViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("statuses", TaskStatusViewSet, basename="taskstatus")
router.register("comments", TaskCommentViewSet, basename="taskcomment")

urlpatterns = router.urls
