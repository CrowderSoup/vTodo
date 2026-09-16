from django.urls import path

from . import views_calendar

app_name = "calendar"

urlpatterns = [
    path("", views_calendar.CalendarView.as_view(), name="calendar"),
    path("team/<int:team_id>/", views_calendar.CalendarView.as_view(), name="calendar-team"),
    path("tasks/<int:pk>/reschedule/", views_calendar.TaskRescheduleView.as_view(), name="task-reschedule"),
]
