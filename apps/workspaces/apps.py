from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    name = "apps.workspaces"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from apps.workspaces.signals import connect_workspace_assignment

        connect_workspace_assignment()
