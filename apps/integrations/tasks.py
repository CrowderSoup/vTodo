import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def sync_all_skylight_connections():
    from apps.integrations.models import SkylightConnection
    from apps.integrations.skylight.sync import sync_connection

    for connection in SkylightConnection.objects.filter(is_active=True):
        try:
            sync_connection(connection)
        except Exception:
            logger.exception("Skylight sync failed for connection %s (team %s)", connection.pk, connection.team_id)
