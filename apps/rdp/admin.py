from django.contrib import admin

from apps.rdp.models import RDPMachinePolicy, RDPSessionAudit, RDPSessionToken


@admin.register(RDPMachinePolicy)
class RDPMachinePolicyAdmin(admin.ModelAdmin):
    list_display = (
        "machine",
        "connection_mode",
        "default_quality",
        "allow_elevated_input",
        "require_justification",
        "silent_access_only",
        "updated_at",
    )
    list_filter = ("connection_mode", "default_quality", "allow_elevated_input", "require_justification", "silent_access_only")
    search_fields = ("machine__hostname",)


@admin.register(RDPSessionToken)
class RDPSessionTokenAdmin(admin.ModelAdmin):
    list_display = ("machine", "created_by", "requested_mode", "created_at", "expires_at", "used_at", "is_active")
    list_filter = ("is_active", "created_at", "expires_at")
    search_fields = ("machine__hostname", "created_by__username")


@admin.register(RDPSessionAudit)
class RDPSessionAuditAdmin(admin.ModelAdmin):
    list_display = ("event_type", "machine", "user", "connection_mode", "session_id", "created_at")
    list_filter = ("event_type", "connection_mode", "created_at")
    search_fields = ("machine__hostname", "user__username", "session_id", "reason")
