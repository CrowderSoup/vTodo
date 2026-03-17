from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import apps.tasks.signals  # noqa: F401
