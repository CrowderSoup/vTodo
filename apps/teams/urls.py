from django.urls import path

from . import views

app_name = "teams"

urlpatterns = [
    path("create/", views.TeamCreateView.as_view(), name="create"),
    path("<int:team_pk>/invite/", views.TeamInviteCreateView.as_view(), name="invite-create"),
    path("invite/<str:token>/accept/", views.TeamInviteAcceptView.as_view(), name="invite-accept"),
    path("<int:team_pk>/members/<int:user_pk>/remove/", views.TeamMemberRemoveView.as_view(), name="member-remove"),
    path("<int:team_pk>/leave/", views.TeamLeaveView.as_view(), name="leave"),
    path("<int:team_pk>/delete/", views.TeamDeleteView.as_view(), name="delete"),
]
