from django.contrib import admin

from apps.workspaces.models import Membership, Workspace


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "owner", "created_at")
    inlines = [MembershipInline]
