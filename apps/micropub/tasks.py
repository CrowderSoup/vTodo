import logging

import requests
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def send_daily_summaries():
    """
    Runs every hour via Celery beat. Finds users whose daily_summary_time
    matches the current UTC hour and POSTs an h-entry to their Micropub endpoint.
    Only runs for users with has_micropub == True.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    current_hour = timezone.now().hour

    users = User.objects.filter(
        daily_summary_enabled=True,
        micropub_token__gt="",
        micropub_endpoint__gt="",
        daily_summary_time__hour=current_hour,
    )

    for user in users:
        try:
            _send_summary_for_user(user)
        except Exception:
            logger.exception("Failed to send daily summary for user %s", user.pk)


def _send_summary_for_user(user) -> None:
    from apps.tasks.models import Task, TaskStatus

    now = timezone.now()
    today = now.date()

    done_slugs = list(TaskStatus.objects.filter(user=user, is_done=True).values_list("slug", flat=True))
    active_slugs = list(TaskStatus.objects.filter(user=user, is_done=False).values_list("slug", flat=True))

    done_today = Task.objects.filter(
        user=user,
        status__in=done_slugs,
        completed_at__date=today,
    )
    in_progress = Task.objects.filter(user=user, status__in=active_slugs)
    new_today = Task.objects.filter(user=user, created_at__date=today)

    done_count = done_today.count()
    in_progress_count = in_progress.count()
    new_count = new_today.count()

    if done_count == 0 and in_progress_count == 0 and new_count == 0:
        return  # nothing to report

    done_lines = "\n".join(f"- {t.title}" for t in done_today) or "  (none)"
    content = (
        f"Daily summary for {now.strftime('%B %-d')}:\n\n"
        f"Completed today ({done_count}):\n{done_lines}\n\n"
        f"In progress: {in_progress_count} task(s)\n"
        f"New today: {new_count} task(s)\n\n"
        f"Sent by vtodo"
    )

    resp = requests.post(
        user.micropub_endpoint,
        data={"h": "entry", "content": content},
        headers={
            "Authorization": f"Bearer {user.micropub_token}",
            "Accept": "application/json",
        },
        timeout=15,
        allow_redirects=False,
    )
    resp.raise_for_status()
    logger.info("Sent daily summary to %s (status %s)", user.micropub_endpoint, resp.status_code)
