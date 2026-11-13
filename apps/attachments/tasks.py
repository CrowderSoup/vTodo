from celery import shared_task


@shared_task
def purge_vupload_deletions():
    """Retry vUpload deletes that didn't go through right after commit."""
    from apps.attachments.services import process_pending_deletions

    total = 0
    while True:
        n = process_pending_deletions()
        total += n
        if n < 200:
            return total
