from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "display_name", "is_staff", "date_joined")
    list_filter = ("is_staff", "is_active", "daily_summary_enabled")
    search_fields = ("username", "display_name")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("display_name", "avatar_url")}),
        ("Micropub", {"fields": ("micropub_endpoint", "micropub_token")}),
        (
            "Daily Summary",
            {"fields": ("daily_summary_enabled", "daily_summary_time")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )
