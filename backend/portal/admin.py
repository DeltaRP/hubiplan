from django.contrib import admin

from .models import ChangeRequest, LoginLink, PortalAccess

admin.site.register(PortalAccess)
admin.site.register(ChangeRequest)


@admin.register(LoginLink)
class LoginLinkAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "created_at", "expires_at", "used_at"]
    exclude = ["token_hash"]
