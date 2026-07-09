from django.contrib import admin

from .models import Task, TaskActivity, TaskComment, TaskStatus


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "team", "assignee", "status", "is_archived", "created_at")
    list_filter = ("is_archived", "team")
    search_fields = ("title",)


@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "user", "team", "is_done", "order")
    list_filter = ("team",)


admin.site.register(TaskComment)
admin.site.register(TaskActivity)
