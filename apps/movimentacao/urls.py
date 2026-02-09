from django.urls import path
from .views import (
    MovimentacaoListView, MovimentacaoCreateView, MovimentacaoDetailView, MovimentacaoDeleteView,
    LoteListView, LoteCreateView, LoteDetailView, LoteUpdateView, LoteDeleteView,
    HistoricoEstoqueListView, HistoricoEstoqueDetailView, AjusteEstoqueCreateView,
    BuscarProdutoPorCodigoView, ValidarNumeroLoteView, ImportarNFeView, TipoMovimentacaoListView,
    TipoMovimentacaoCreateView, TipoMovimentacaoUpdateView
)

app_name = 'movimentacao'

urlpatterns = [
    path('movimentacao/', MovimentacaoListView.as_view(), name='movimentacao_list'),
    path('movimentacao/criar/', MovimentacaoCreateView.as_view(), name='movimentacao_create'),
    path('movimentacao/<int:pk>/detalhe/', MovimentacaoDetailView.as_view(), name='movimentacao_detail'),
    path('movimentacao/excluir/<int:pk>/', MovimentacaoDeleteView.as_view(), name='movimentacao_delete'),
    path('movimentacao/buscar-produto/', BuscarProdutoPorCodigoView.as_view(), name='buscar_produto_por_codigo'),
    path('lote/', LoteListView.as_view(), name='lote_list'),
    path('lote/criar/', LoteCreateView.as_view(), name='lote_create'),
    path('lote/<int:pk>/detalhe/', LoteDetailView.as_view(), name='lote_detail'),
    path('lote/<int:pk>/atualizar/', LoteUpdateView.as_view(), name='lote_update'),
    path('lote/<int:pk>/deletar/', LoteDeleteView.as_view(), name='lote_delete'),
    path('historico-estoque/', HistoricoEstoqueListView.as_view(), name='historico_estoque_list'),
    path('historico-estoque/<int:pk>/detalhe/', HistoricoEstoqueDetailView.as_view(), name='historico_estoque_detail'),
    path('ajuste-estoque/criar/', AjusteEstoqueCreateView.as_view(), name='ajuste_estoque_create'),
    path('lote/validar-numero/', ValidarNumeroLoteView.as_view(), name='validar_numero_lote'),
    # Tipos de Movimentação
    path('tipo/', TipoMovimentacaoListView.as_view(), name='tipo_movimentacao_list'),
    path('tipo/novo/', TipoMovimentacaoCreateView.as_view(), name='tipo_movimentacao_create'),
    path('tipo/editar/<int:pk>/', TipoMovimentacaoUpdateView.as_view(), name='tipo_movimentacao_edit'),
    
    # Importação de Nota Fiscal (NFe) via Lote
    path('lote/importar-nfe/', ImportarNFeView.as_view(), name='importar_nfe'),
]