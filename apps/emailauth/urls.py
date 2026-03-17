from django.urls import path

from . import views

app_name = "emailauth"

urlpatterns = [
    path("request/", views.RequestOTPView.as_view(), name="request"),
    path("verify/", views.VerifyOTPView.as_view(), name="verify"),
]
