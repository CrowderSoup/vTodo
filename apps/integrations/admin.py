from django.contrib import admin

from .models import ExternalLink, SkylightConnection, SkylightMemberMapping


class SkylightMemberMappingInline(admin.TabularInline):
    model = SkylightMemberMapping
    extra = 0
    fields = ("category_id", "category_label", "user")


@admin.register(SkylightConnection)
class SkylightConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "team", "frame_id", "is_active", "is_ready",
        "last_synced_at", "last_sync_error",
    )
    list_filter = ("is_active",)
    search_fields = ("team__name", "frame_id")
    readonly_fields = ("refresh_token_encrypted", "token_encrypted", "token_fetched_at")
    inlines = [SkylightMemberMappingInline]


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("provider", "external_id", "task", "synced_at")
    list_filter = ("provider",)
    search_fields = ("external_id", "task__title")
