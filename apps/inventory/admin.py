from django.contrib import admin, messages
from .models import Machine, MachineGroup, BlockedSite, Notification
from import_export.admin import ImportExportMixin

@admin.register(MachineGroup)
class MachineGroupAdmin(ImportExportMixin, admin.ModelAdmin):
    list_display  = ('name', 'description')
    search_fields = ('name',)

@admin.register(Machine)
class MachineAdmin(ImportExportMixin, admin.ModelAdmin):
    list_display    = ('hostname', 'loggedUser', 'TpmInfo', 'ip_address', 'group', 'is_online', 'last_seen', 'ram_gb', 'disk_free_gb')
    list_filter     = ('group', 'is_online', 'last_seen')
    search_fields   = ('hostname', 'ip_address')
    readonly_fields = ('last_seen',)

@admin.register(BlockedSite)
class BlockedSiteAdmin(ImportExportMixin, admin.ModelAdmin):
    list_display  = ('url', 'machine', 'group')
    list_filter   = ('group', 'machine')
    search_fields = ('url',)

@admin.register(Notification)
class NotificationAdmin(ImportExportMixin, admin.ModelAdmin):
    list_display       = ('title', 'created_at', 'sent_to_all')
    list_filter        = ('sent_to_all', 'created_at')
    filter_horizontal  = ('machines', 'groups')

    def save_model(self, request, obj, form, change):
        # só salva no banco, sem tentar enviar nada por WinRM
        super().save_model(request, obj, form, change)
        self.message_user(
            request,
            "Notificação salva. O agente irá buscá-la e exibi-la localmente.",
            level=messages.INFO
        )
