from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("google-calendar/connect/", views.GoogleCalendarConnectView.as_view(), name="google-calendar-connect"),
    path("google-calendar/callback/", views.GoogleCalendarCallbackView.as_view(), name="google-calendar-callback"),
    path("google-calendar/disconnect/", views.GoogleCalendarDisconnectView.as_view(), name="google-calendar-disconnect"),
]
