from django.urls import path

from . import views

app_name = "boards"

urlpatterns = [
    path("", views.BoardView.as_view(), name="board"),
    path("filter/", views.BoardFilterView.as_view(), name="board-filter"),
    path("filter/add-tag/", views.BoardFilterAddTagView.as_view(), name="board-filter-add-tag"),
    path("filters/save/", views.SavedFilterSaveView.as_view(), name="filter-save"),
    path("filters/<int:pk>/load/", views.SavedFilterLoadView.as_view(), name="filter-load"),
    path("filters/<int:pk>/delete/", views.SavedFilterDeleteView.as_view(), name="filter-delete"),
    path("columns/reorder/", views.ColumnReorderView.as_view(), name="column-reorder"),
    path("columns/<int:pk>/hide/", views.ColumnHideView.as_view(), name="column-hide"),
    path("columns/<int:pk>/archive/", views.ColumnArchiveView.as_view(), name="column-archive"),
    path("tasks/reorder/", views.TaskReorderView.as_view(), name="task-reorder"),
    path("tasks/create/", views.TaskCreateView.as_view(), name="task-create"),
    path("tasks/<int:pk>/update/", views.TaskUpdateView.as_view(), name="task-update"),
    path("tasks/<int:pk>/move/", views.TaskMoveView.as_view(), name="task-move"),
    path("tasks/<int:pk>/delete/", views.TaskDeleteView.as_view(), name="task-delete"),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:pk>/edit/", views.TaskEditView.as_view(), name="task-edit"),
    path("tasks/<int:pk>/panel/", views.TaskPanelView.as_view(), name="task-panel"),
    path("tasks/panel/create/", views.TaskPanelCreateView.as_view(), name="task-panel-create"),
    path("tasks/<int:pk>/panel/edit/", views.TaskPanelEditView.as_view(), name="task-panel-edit"),
    path("tasks/<int:pk>/panel/update/", views.TaskPanelUpdateView.as_view(), name="task-panel-update"),
    path("tasks/<int:pk>/comments/", views.TaskCommentCreateView.as_view(), name="task-comment-create"),
    path("tasks/<int:pk>/comments/<int:comment_pk>/delete/", views.TaskCommentDeleteView.as_view(), name="task-comment-delete"),
]
