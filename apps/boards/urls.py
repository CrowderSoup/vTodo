from django.urls import path

from . import views

app_name = "boards"

urlpatterns = [
    path("", views.BoardView.as_view(), name="board"),
    path("tasks/create/", views.TaskCreateView.as_view(), name="task-create"),
    path("tasks/<int:pk>/update/", views.TaskUpdateView.as_view(), name="task-update"),
    path("tasks/<int:pk>/move/", views.TaskMoveView.as_view(), name="task-move"),
    path("tasks/<int:pk>/delete/", views.TaskDeleteView.as_view(), name="task-delete"),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:pk>/edit/", views.TaskEditView.as_view(), name="task-edit"),
]
