from django.urls import path

from . import views_list

app_name = "list"

urlpatterns = [
    path("", views_list.ListView.as_view(), name="list"),
    path("layout/", views_list.ListLayoutView.as_view(), name="layout"),
    path("groups/toggle/", views_list.ListGroupToggleView.as_view(), name="group-toggle"),
]
