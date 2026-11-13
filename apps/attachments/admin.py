from django.contrib import admin

from apps.attachments.models import Attachment, PendingDeletion


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "content_type", "size", "task", "workspace", "created_at")
    list_filter = ("content_type",)
    raw_id_fields = ("workspace", "task", "comment", "uploaded_by")
    readonly_fields = ("file_id",)


@admin.register(PendingDeletion)
class PendingDeletionAdmin(admin.ModelAdmin):
    list_display = ("kind", "target", "attempts", "last_error", "created_at")
