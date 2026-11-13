from django.apps import AppConfig


class AttachmentsConfig(AppConfig):
    name = "apps.attachments"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import apps.attachments.signals  # noqa: F401
