from django.contrib import admin

from .models import Department, DepartmentRole, Imprint, Organization, PlatformSettings


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "parent", "city", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name", "city")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "founding_year", "is_active")
    list_filter = ("organization",)


admin.site.register(DepartmentRole)
admin.site.register(PlatformSettings)
admin.site.register(Imprint)
