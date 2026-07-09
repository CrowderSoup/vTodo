from django.contrib import admin

from .models import Team, TeamInvite, TeamMembership


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    inlines = [TeamMembershipInline]


@admin.register(TeamInvite)
class TeamInviteAdmin(admin.ModelAdmin):
    list_display = ("email", "team", "invited_by", "created_at", "expires_at", "accepted_at")
    list_filter = ("team",)
    search_fields = ("email",)
