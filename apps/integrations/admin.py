from django.contrib import admin

from .models import ExternalLink


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("provider", "external_id", "task", "synced_at")
    list_filter = ("provider",)
    search_fields = ("external_id", "task__title")
