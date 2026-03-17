from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("", views.SettingsView.as_view(), name="settings"),
    path("statuses/create/", views.TaskStatusCreateView.as_view(), name="status-create"),
    path("statuses/<int:pk>/delete/", views.TaskStatusDeleteView.as_view(), name="status-delete"),
    path("columns/create/", views.ColumnCreateView.as_view(), name="column-create"),
    path("columns/<int:pk>/delete/", views.ColumnDeleteView.as_view(), name="column-delete"),
]
