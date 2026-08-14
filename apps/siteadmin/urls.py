from django.urls import path

from . import views

app_name = "siteadmin"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("signup-mode/", views.SignupModeUpdateView.as_view(), name="signup-mode-update"),
    path("invites/", views.SiteInviteCreateView.as_view(), name="invite-create"),
]
