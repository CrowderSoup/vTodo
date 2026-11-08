"""Agent sub-accounts: users that act for a person through an API token."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.api.models import DeviceToken
from apps.users.models import User

AGENT_TOKEN_NAME = "Agent token"


def create_agent(*, parent, name):
    """A new agent for `parent`, and its token. The raw token is only
    returned here, so show it once."""
    if parent.is_agent:
        raise ValidationError("An agent can't have agents of its own.")
    name = (name or "").strip()
    if not name:
        raise ValidationError("Give the agent a name.")
    if len(name) > 255:
        raise ValidationError("That name is too long.")
    with transaction.atomic():
        agent = User.objects.create_user(
            kind=User.KIND_AGENT,
            parent=parent,
            display_name=name,
            timezone=parent.timezone,
        )
        _token, raw = DeviceToken.issue(agent, AGENT_TOKEN_NAME)
    return agent, raw


def reissue_agent_token(agent):
    """Revoke the agent's tokens and return a new one."""
    with transaction.atomic():
        agent.device_tokens.all().delete()
        _token, raw = DeviceToken.issue(agent, AGENT_TOKEN_NAME)
    return raw


def agents_of(user):
    return User.objects.filter(parent=user, kind=User.KIND_AGENT).order_by("display_name", "pk")
