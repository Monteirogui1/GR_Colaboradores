from django.urls import path
from core import settings
from django.conf.urls.static import static

from .views import ProdutoListView, ProdutoCreateView, ProdutoDetailView, ProdutoUpdateView, \
    ProdutoDeleteView, ProdutoExportView, ProdutoImportView, \
    VariacaoProdutoExportView, VariacaoProdutoImportView, UnidadeMedidaListView, UnidadeMedidaCreateView, \
    UnidadeMedidaUpdateView, CampoDinamicoListView, CampoDinamicoCreateView, CampoDinamicoUpdateView

app_name = 'produtos'

urlpatterns = [
    path('Produto/', ProdutoListView.as_view(), name='produtos_list'),
    path('Produto/criar/', ProdutoCreateView.as_view(), name='produtos_form'),
    path('Produto/<int:pk>/detalhe/', ProdutoDetailView.as_view(), name='produtos_detail'),
    path('Produto/<int:pk>/atualizar/', ProdutoUpdateView.as_view(), name='produtos_form'),
    path('Produto/<int:pk>/deletar/', ProdutoDeleteView.as_view(), name='produtos_delete'),
    path('export/', ProdutoExportView.as_view(), name='produto_export'),
    path('import/', ProdutoImportView.as_view(), name='produto_import'),
    path('variacao/export/', VariacaoProdutoExportView.as_view(), name='variacao_export'),
    path('variacao/import/', VariacaoProdutoImportView.as_view(), name='variacao_import'),

    # Unidades de Medida
    path('unidade/', UnidadeMedidaListView.as_view(), name='unidade_medida_list'),
    path('unidade/novo/', UnidadeMedidaCreateView.as_view(), name='unidade_medida_create'),
    path('unidade/editar/<int:pk>/', UnidadeMedidaUpdateView.as_view(), name='unidade_medida_edit'),

    # Campos Dinâmicos
    path('campo-dinamico/', CampoDinamicoListView.as_view(), name='campo_dinamico_list'),
    path('campo-dinamico/novo/', CampoDinamicoCreateView.as_view(), name='campo_dinamico_create'),
    path('campo-dinamico/editar/<int:pk>/', CampoDinamicoUpdateView.as_view(), name='campo_dinamico_edit'),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)