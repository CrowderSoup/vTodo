from django.contrib import admin
from django.db import transaction

from . import lifecycle
from .models import Task, TaskComment, TaskStatus


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "is_archived", "created_at")
    list_filter = ("is_archived",)
    search_fields = ("title",)


@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "user", "is_done", "order")

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if change and "is_done" in form.changed_data:
                lifecycle.status_redefined(obj)


admin.site.register(TaskComment)
