from django.contrib import admin

from .models import Role, RoleAssignment


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_board")
    list_filter = ("organization",)


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "organization", "valid_from", "valid_until")
    list_filter = ("organization",)
    search_fields = ("user__email",)
