from django.contrib import admin

from .models import ExternalLink, GoogleCalendarConnection


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("provider", "external_id", "task", "synced_at")
    list_filter = ("provider",)
    search_fields = ("external_id", "task__title")


@admin.register(GoogleCalendarConnection)
class GoogleCalendarConnectionAdmin(admin.ModelAdmin):
    # refresh_token_encrypted is deliberately excluded from every list/fieldset.
    list_display = ("user", "calendar_id", "is_active", "last_synced_at")
    list_filter = ("is_active",)
    search_fields = ("user__username", "user__display_name", "calendar_id")
    readonly_fields = ("created_at", "last_synced_at", "last_sync_error")
    fields = ("user", "calendar_id", "is_active", "created_at", "last_synced_at", "last_sync_error")
