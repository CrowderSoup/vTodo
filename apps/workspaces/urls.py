from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("switch/", views.SwitchWorkspaceView.as_view(), name="switch"),
    path("new/", views.CreateWorkspaceView.as_view(), name="create"),
    path("members/add/", views.MemberAddView.as_view(), name="member-add"),
    path("members/<int:pk>/role/", views.MemberRoleView.as_view(), name="member-role"),
    path("members/<int:pk>/remove/", views.MemberRemoveView.as_view(), name="member-remove"),
]
