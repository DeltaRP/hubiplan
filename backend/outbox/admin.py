from django.contrib import admin

from .models import OutgoingMail


@admin.register(OutgoingMail)
class OutgoingMailAdmin(admin.ModelAdmin):
    list_display = ["created_at", "organization", "to", "subject", "status"]
    list_filter = ["status", "kind"]
    search_fields = ["to", "subject"]
