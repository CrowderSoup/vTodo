from django.urls import path

from . import views

app_name = "indieauth"

urlpatterns = [
    path("", views.LoginView.as_view(), name="login"),
    path("start/", views.StartView.as_view(), name="start"),
    path("callback/", views.CallbackView.as_view(), name="callback"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
]
