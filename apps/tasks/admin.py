from django.contrib import admin

from .models import Task, TaskComment, TaskStatus


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "is_archived", "created_at")
    list_filter = ("is_archived",)
    search_fields = ("title",)


@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "user", "is_done", "order")


admin.site.register(TaskComment)
