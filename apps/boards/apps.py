from django.apps import AppConfig


class BoardsConfig(AppConfig):
    name = "apps.boards"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import apps.boards.signals  # noqa: F401
