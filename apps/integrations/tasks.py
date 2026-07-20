import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def sync_all_skylight_connections():
    from apps.integrations.models import SkylightConnection
    from apps.integrations.skylight.client import SkylightAuthError
    from apps.integrations.skylight.sync import sync_connection

    for connection in SkylightConnection.objects.filter(is_active=True):
        try:
            sync_connection(connection)
        except SkylightAuthError:
            # The refresh token is single-use/rotating -- if Skylight ever
            # permanently rejects it (revoked, password changed), retrying every
            # cycle is futile. Stop trying until the owner reconnects.
            connection.is_active = False
            connection.save(update_fields=["is_active"])
            logger.exception("Skylight refresh token rejected for connection %s (team %s); deactivated", connection.pk, connection.team_id)
        except Exception:
            logger.exception("Skylight sync failed for connection %s (team %s)", connection.pk, connection.team_id)
