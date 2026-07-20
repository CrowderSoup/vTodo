from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("<int:team_pk>/skylight/connect/", views.SkylightConnectView.as_view(), name="skylight-connect"),
    path(
        "<int:team_pk>/skylight/calendar/",
        views.SkylightSelectCalendarView.as_view(),
        name="skylight-select-calendar",
    ),
    path("<int:team_pk>/skylight/mapping/", views.SkylightMemberMappingView.as_view(), name="skylight-mapping"),
    path("<int:team_pk>/skylight/disconnect/", views.SkylightDisconnectView.as_view(), name="skylight-disconnect"),
]
