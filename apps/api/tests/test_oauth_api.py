"""The task API accepts OAuth access tokens forwarded by mcp_server, so
remote MCP clients never need a permanent DRF token."""

from datetime import timedelta

import pytest
from django.urls import reverse

from apps.tasks.models import Task
from apps.users.models import User

MCP_RESOURCE = "https://mcp.vtodo.crowdersoup.com/mcp"


@pytest.fixture(autouse=True)
def mcp_resource(settings):
    settings.VTODO_MCP_RESOURCE_URL = MCP_RESOURCE


@pytest.mark.django_db
def test_task_list_accepts_token_restricted_to_the_mcp_resource(oauth_client_for):
    user = User.objects.create_user(username="oauth-api-user")
    other = User.objects.create_user(username="oauth-api-other")
    Task.objects.create(user=user, title="Mine", status="todo")
    Task.objects.create(user=other, title="Theirs", status="todo")
    client = oauth_client_for(user, resource=[MCP_RESOURCE])

    response = client.get(reverse("task-list"))

    assert response.status_code == 200
    assert {t["title"] for t in response.data} == {"Mine"}


@pytest.mark.django_db
def test_task_create_accepts_unrestricted_tasks_token(oauth_client_for):
    user = User.objects.create_user(username="oauth-api-create")
    client = oauth_client_for(user)

    response = client.post(reverse("task-list"), {"title": "From MCP"}, format="json")

    assert response.status_code == 201
    assert Task.objects.filter(user=user, title="From MCP").exists()


@pytest.mark.django_db
def test_task_list_rejects_token_for_another_resource(oauth_client_for):
    user = User.objects.create_user(username="oauth-api-elsewhere")
    client = oauth_client_for(user, resource=["https://elsewhere.example.com/api"])

    response = client.get(reverse("task-list"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_mcp_audience_is_not_accepted_outside_the_api(oauth_client_for, settings):
    """The MCP-audience exemption is scoped to /api/v1/ only."""
    from apps.api.views import validate_api_resource_token

    assert validate_api_resource_token("https://vtodo.crowdersoup.com/api/v1/tasks/", [MCP_RESOURCE])
    assert not validate_api_resource_token("https://vtodo.crowdersoup.com/o/applications/", [MCP_RESOURCE])
    assert not validate_api_resource_token(
        "https://vtodo.crowdersoup.com/api/v1/tasks/", ["https://mcp.vtodo.crowdersoup.com/mcp-other"]
    )
    settings.VTODO_MCP_RESOURCE_URL = ""
    assert not validate_api_resource_token("https://vtodo.crowdersoup.com/api/v1/tasks/", [MCP_RESOURCE])


@pytest.mark.django_db
def test_task_list_rejects_token_without_tasks_scope(oauth_client_for):
    user = User.objects.create_user(username="oauth-api-scope")
    client = oauth_client_for(user, scope="read")

    response = client.get(reverse("task-list"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_task_list_rejects_expired_token(oauth_client_for):
    user = User.objects.create_user(username="oauth-api-expired")
    client = oauth_client_for(user, expires_in=timedelta(hours=-1))

    response = client.get(reverse("task-list"))

    assert response.status_code == 401
