import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def sync_all_google_calendar_connections():
    from apps.integrations.google_calendar.client import GoogleCalendarAuthError
    from apps.integrations.google_calendar.sync import sync_connection
    from apps.integrations.models import GoogleCalendarConnection

    for connection in GoogleCalendarConnection.objects.filter(is_active=True):
        try:
            sync_connection(connection)
        except GoogleCalendarAuthError:
            # sync_connection already deactivated the connection -- the refresh
            # token is permanently rejected, so retrying every cycle is futile.
            logger.exception(
                "Google Calendar refresh token rejected for connection %s (user %s); deactivated",
                connection.pk, connection.user_id,
            )
        except Exception:
            logger.exception(
                "Google Calendar sync failed for connection %s (user %s)", connection.pk, connection.user_id,
            )
