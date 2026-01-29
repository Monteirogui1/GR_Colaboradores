from django.contrib import admin
from .models import Localizacao, Ativo, AtivoUtilizador, AtivoAnexo, AtivoHistorico, StatusAtivo


@admin.register(Localizacao)
class LocalizacaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'status', 'created_at')
    search_fields = ('nome',)
    list_filter = ('status',)


@admin.register(StatusAtivo)
class StatusAtivoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cor_display', 'is_active', 'created_at')
    search_fields = ('nome',)
    list_filter = ('is_active',)

    def cor_display(self, obj):
        from django.utils.html import format_html
        return format_html(
            '<div style="width: 20px; height: 20px; background-color: {}; border-radius: 3px; display: inline-block;"></div>',
            obj.cor
        )

    cor_display.short_description = 'Cor'


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ('etiqueta', 'nome', 'categoria', 'status', 'localizacao', 'data_compra')
    search_fields = ('nome', 'etiqueta', 'numero_serie')
    list_filter = ('status', 'categoria', 'localizacao', 'data_compra')
    date_hierarchy = 'created_at'


@admin.register(AtivoUtilizador)
class AtivoUtilizadorAdmin(admin.ModelAdmin):
    list_display = ('ativo', 'usuario', 'data_inicio', 'data_fim')
    search_fields = ('ativo__etiqueta', 'usuario__username')
    list_filter = ('data_inicio',)


@admin.register(AtivoAnexo)
class AtivoAnexoAdmin(admin.ModelAdmin):
    list_display = ('ativo', 'titulo', 'created_at')
    search_fields = ('ativo__etiqueta', 'titulo')


@admin.register(AtivoHistorico)
class AtivoHistoricoAdmin(admin.ModelAdmin):
    list_display = ('ativo', 'campo_alterado', 'usuario', 'created_at')
    search_fields = ('ativo__etiqueta', 'descricao', 'campo_alterado')
    list_filter = ('campo_alterado', 'created_at')
    readonly_fields = ('ativo', 'campo_alterado', 'valor_anterior', 'valor_novo', 'descricao', 'usuario', 'created_at')