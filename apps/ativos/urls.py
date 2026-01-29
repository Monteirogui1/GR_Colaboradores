from django.urls import path
from .views import (
    # Localizações
    LocalizacaoListView, LocalizacaoCreateView, LocalizacaoUpdateView, LocalizacaoDeleteView,

    # Status
    StatusAtivoListView, StatusAtivoCreateView, StatusAtivoUpdateView, StatusAtivoDeleteView,

    # Ativos
    AtivoListView, AtivoCreateView, AtivoDetailView, AtivoUpdateView, AtivoDeleteView,

    # Utilizadores
    AtivoUtilizadorCreateView, AtivoUtilizadorDeleteView,

    # Anexos
    AtivoAnexoCreateView, AtivoAnexoDeleteView,
)

app_name = 'ativos'

urlpatterns = [
    # Localizações
    path('localizacoes/', LocalizacaoListView.as_view(), name='localizacao_list'),
    path('localizacoes/criar/', LocalizacaoCreateView.as_view(), name='localizacao_create'),
    path('localizacoes/<int:pk>/editar/', LocalizacaoUpdateView.as_view(), name='localizacao_update'),
    path('localizacoes/<int:pk>/deletar/', LocalizacaoDeleteView.as_view(), name='localizacao_delete'),

    # Status
    path('status/', StatusAtivoListView.as_view(), name='status_list'),
    path('status/criar/', StatusAtivoCreateView.as_view(), name='status_create'),
    path('status/<int:pk>/editar/', StatusAtivoUpdateView.as_view(), name='status_update'),
    path('status/<int:pk>/deletar/', StatusAtivoDeleteView.as_view(), name='status_delete'),

    # Ativos
    path('ativos/', AtivoListView.as_view(), name='ativo_list'),
    path('ativos/criar/', AtivoCreateView.as_view(), name='ativo_create'),
    path('ativos/<int:pk>/', AtivoDetailView.as_view(), name='ativo_detail'),
    path('ativos/<int:pk>/editar/', AtivoUpdateView.as_view(), name='ativo_update'),
    path('ativos/<int:pk>/deletar/', AtivoDeleteView.as_view(), name='ativo_delete'),

    # Utilizadores (AJAX)
    path('ativos/<int:ativo_id>/utilizadores/criar/', AtivoUtilizadorCreateView.as_view(), name='utilizador_create'),
    path('utilizadores/<int:pk>/deletar/', AtivoUtilizadorDeleteView.as_view(), name='utilizador_delete'),

    # Anexos (AJAX)
    path('ativos/<int:ativo_id>/anexos/criar/', AtivoAnexoCreateView.as_view(), name='anexo_create'),
    path('anexos/<int:pk>/deletar/', AtivoAnexoDeleteView.as_view(), name='anexo_delete'),
]