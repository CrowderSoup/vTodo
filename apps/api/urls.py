from rest_framework.routers import DefaultRouter

from .views import TaskStatusViewSet, TaskViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("statuses", TaskStatusViewSet, basename="taskstatus")

urlpatterns = router.urls
