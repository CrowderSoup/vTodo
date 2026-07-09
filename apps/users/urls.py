from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("", views.SettingsGeneralView.as_view(), name="settings"),
    path("board/", views.SettingsBoardView.as_view(), name="settings-board"),
    path("api/", views.SettingsApiView.as_view(), name="settings-api"),
    path("statuses/create/", views.TaskStatusCreateView.as_view(), name="status-create"),
    path("statuses/<int:pk>/delete/", views.TaskStatusDeleteView.as_view(), name="status-delete"),
    path("columns/create/", views.ColumnCreateView.as_view(), name="column-create"),
    path("columns/<int:pk>/delete/", views.ColumnDeleteView.as_view(), name="column-delete"),
    path("saved-views/<int:pk>/delete/", views.SavedViewDeleteView.as_view(), name="saved-view-delete"),
    path("api-token/", views.ApiTokenView.as_view(), name="api-token"),
    path("api-token/regenerate/", views.ApiTokenRegenerateView.as_view(), name="api-token-regenerate"),
]
