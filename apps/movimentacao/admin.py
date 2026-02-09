from django.contrib import admin
from .models import Movimentacao, Lote, HistoricoEstoque, TipoMovimentacao


class LoteAdmin(admin.ModelAdmin):
    list_display = ('numero_lote', 'variacao', 'fornecedor', 'quantidade', 'data_entrada')
    search_fields = ('numero_lote', 'variacao__produto__nome', 'fornecedor__nome')
    list_filter = ('fornecedor', 'data_entrada')


class HistoricoEstoqueAdmin(admin.ModelAdmin):
    list_display = ('variacao', 'tipo_operacao', 'quantidade_anterior', 'quantidade_nova', 'usuario', 'created_at')
    search_fields = ('variacao__produto__nome', 'tipo_operacao', 'usuario__username')
    list_filter = ('tipo_operacao', 'created_at', 'usuario')


admin.site.register(Movimentacao)
admin.site.register(Lote)
admin.site.register(HistoricoEstoque, HistoricoEstoqueAdmin)
admin.site.register(TipoMovimentacao)