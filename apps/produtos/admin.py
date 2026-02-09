from django.contrib import admin
from .models import (
    Produto, VariacaoProduto, UnidadeMedida, ProdutoUnidade,
    CampoDinamico, ValorCampoDinamico,
    ProdutoComposicao, ParametroEstoque
)

class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'num_serie',)
    search_fields = ('nome',)


admin.site.register(Produto)
admin.site.register(VariacaoProduto)
admin.site.register(UnidadeMedida)
admin.site.register(ProdutoUnidade)
admin.site.register(CampoDinamico)
admin.site.register(ValorCampoDinamico)
admin.site.register(ProdutoComposicao)
admin.site.register(ParametroEstoque)