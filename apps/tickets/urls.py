from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    # ==================== DASHBOARD ====================
    path('dash/', views.TicketDashboardView.as_view(), name='dashboard'),

    # ==================== TICKETS ====================
    path('tickets/', views.TicketListView.as_view(), name='ticket_list'),
    path('tickets/novo/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('tickets/<int:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('tickets/<int:pk>/editar/', views.TicketUpdateView.as_view(), name='ticket_update'),
    path('tickets/<int:pk>/excluir/', views.TicketDeleteView.as_view(), name='ticket_delete'),

    # Ações no ticket
    path('tickets/<int:pk>/acao/', views.adicionar_acao, name='adicionar_acao'),
    path('tickets/<int:pk>/anexo/', views.adicionar_anexo, name='adicionar_anexo'),
    path('tickets/<int:pk>/status/', views.alterar_status_rapido, name='alterar_status'),
    path('tickets/<int:pk>/responsavel/', views.alterar_responsavel_rapido, name='alterar_responsavel'),
    path('tickets/<int:pk>/ativos/', views.gerenciar_ativos_ticket, name='gerenciar_ativos'),
    path('tickets/<int:pk>/ativos/buscar/', views.buscar_ativos_json, name='buscar_ativos_json'),

    # ==================== CLASSIFICAÇÕES ====================

    # Categorias
    path('config/categorias/', views.CategoriaListView.as_view(), name='categoria_list'),
    path('config/categorias/criar/', views.CategoriaCreateView.as_view(), name='categoria_create'),
    path('config/categorias/<int:pk>/editar/', views.CategoriaUpdateView.as_view(), name='categoria_update'),
    path('config/categorias/<int:pk>/excluir/', views.CategoriaDeleteView.as_view(), name='categoria_delete'),

    # Urgências
    path('config/urgencias/', views.UrgenciaListView.as_view(), name='urgencia_list'),
    path('config/urgencias/criar/', views.UrgenciaCreateView.as_view(), name='urgencia_create'),
    path('config/urgencias/<int:pk>/editar/', views.UrgenciaUpdateView.as_view(), name='urgencia_update'),
    path('config/urgencias/<int:pk>/excluir/', views.UrgenciaDeleteView.as_view(), name='urgencia_delete'),

    # Status
    path('config/status/', views.StatusListView.as_view(), name='status_list'),
    path('config/status/criar/', views.StatusCreateView.as_view(), name='status_create'),
    path('config/status/<int:pk>/editar/', views.StatusUpdateView.as_view(), name='status_update'),
    path('config/status/<int:pk>/excluir/', views.StatusDeleteView.as_view(), name='status_delete'),

    # Justificativas
    path('config/justificativas/', views.JustificativaListView.as_view(), name='justificativa_list'),
    path('config/justificativas/criar/', views.JustificativaCreateView.as_view(), name='justificativa_create'),
    path('config/justificativas/<int:pk>/editar/', views.JustificativaUpdateView.as_view(),
         name='justificativa_update'),
    path('config/justificativas/<int:pk>/excluir/', views.JustificativaDeleteView.as_view(),
         name='justificativa_delete'),

    # Serviços
    path('config/servicos/', views.ServicoListView.as_view(), name='servico_list'),
    path('config/servicos/criar/', views.ServicoCreateView.as_view(), name='servico_create'),
    path('config/servicos/<int:pk>/editar/', views.ServicoUpdateView.as_view(), name='servico_update'),
    path('config/servicos/<int:pk>/excluir/', views.ServicoDeleteView.as_view(), name='servico_delete'),

    # ==================== SLA ====================
    path('config/sla/', views.ContratoSLAListView.as_view(), name='contrato_sla_list'),
    path('config/sla/criar/', views.ContratoSLACreateView.as_view(), name='contrato_sla_create'),
    path('config/sla/<int:pk>/', views.ContratoSLADetailView.as_view(), name='contrato_sla_detail'),
    path('config/sla/<int:pk>/editar/', views.ContratoSLAUpdateView.as_view(), name='contrato_sla_update'),
    path('config/sla/<int:pk>/excluir/', views.ContratoSLADeleteView.as_view(), name='contrato_sla_delete'),

    # Regras SLA
    path('config/sla/<int:contrato_pk>/regras/criar/', views.RegraSLACreateView.as_view(),
         name='regra_sla_create'),
    path('config/sla/regras/<int:pk>/editar/', views.RegraSLAUpdateView.as_view(), name='regra_sla_update'),
    path('config/sla/regras/<int:pk>/excluir/', views.RegraSLADeleteView.as_view(), name='regra_sla_delete'),

    # ==================== CAMPOS ADICIONAIS ====================
    path('config/campos/', views.CampoAdicionalListView.as_view(), name='campo_adicional_list'),
    path('config/campos/criar/', views.CampoAdicionalCreateView.as_view(), name='campo_adicional_create'),
    path('config/campos/<int:pk>/editar/', views.CampoAdicionalUpdateView.as_view(),
         name='campo_adicional_update'),
    path('config/campos/<int:pk>/excluir/', views.CampoAdicionalDeleteView.as_view(),
         name='campo_adicional_delete'),

    # Regras de Exibição
    path('config/regras-exibicao/', views.RegraExibicaoCampoListView.as_view(), name='regra_exibicao_list'),
    path('config/regras-exibicao/criar/', views.RegraExibicaoCampoCreateView.as_view(),
         name='regra_exibicao_create'),
    path('config/regras-exibicao/<int:pk>/editar/', views.RegraExibicaoCampoUpdateView.as_view(),
         name='regra_exibicao_update'),
    path('config/regras-exibicao/<int:pk>/excluir/', views.RegraExibicaoCampoDeleteView.as_view(),
         name='regra_exibicao_delete'),

    # ==================== AUTOMAÇÕES ====================
    path('config/gatilhos/', views.GatilhoListView.as_view(), name='gatilho_list'),
    path('config/gatilhos/criar/', views.GatilhoCreateView.as_view(), name='gatilho_create'),
    path('config/gatilhos/<int:pk>/editar/', views.GatilhoUpdateView.as_view(), name='gatilho_update'),
    path('config/gatilhos/<int:pk>/excluir/', views.GatilhoDeleteView.as_view(), name='gatilho_delete'),

    path('config/macros/', views.MacroListView.as_view(), name='macro_list'),
    path('config/macros/criar/', views.MacroCreateView.as_view(), name='macro_create'),
    path('config/macros/<int:pk>/editar/', views.MacroUpdateView.as_view(), name='macro_update'),
    path('config/macros/<int:pk>/excluir/', views.MacroDeleteView.as_view(), name='macro_delete'),

    # ==================== HORÁRIO DE ATENDIMENTO ====================
    path('config/horarios/', views.HorarioAtendimentoListView.as_view(), name='horario_list'),
    path('config/horarios/criar/', views.HorarioAtendimentoCreateView.as_view(), name='horario_create'),
    path('config/horarios/<int:pk>/editar/', views.HorarioAtendimentoUpdateView.as_view(), name='horario_update'),
    path('config/horarios/<int:pk>/excluir/', views.HorarioAtendimentoDeleteView.as_view(), name='horario_delete'),

    # ==================== FERIADOS ====================
    path('config/feriados/', views.FeriadoListView.as_view(), name='feriado_list'),
    path('config/feriados/criar/', views.FeriadoCreateView.as_view(), name='feriado_create'),
    path('config/feriados/<int:pk>/editar/', views.FeriadoUpdateView.as_view(), name='feriado_update'),
    path('config/feriados/<int:pk>/excluir/', views.FeriadoDeleteView.as_view(), name='feriado_delete'),

# ==================== TEMPLATES DE RESPOSTA ====================
    path('config/templates-resposta/', views.TemplateRespostaListView.as_view(), name='template_resposta_list'),
    path('config/templates-resposta/criar/', views.TemplateRespostaCreateView.as_view(), name='template_resposta_create'),
    path('config/templates-resposta/<int:pk>/editar/', views.TemplateRespostaUpdateView.as_view(), name='template_resposta_update'),
    path('config/templates-resposta/<int:pk>/excluir/', views.TemplateRespostaDeleteView.as_view(), name='template_resposta_delete'),
    path('api/templates-resposta/<int:pk>/preview/', views.template_resposta_preview, name='template_resposta_preview'),

    # ==================== EQUIPES ====================
    path('config/equipes/', views.EquipeListView.as_view(), name='equipe_list'),
    path('config/equipes/criar/', views.EquipeCreateView.as_view(), name='equipe_create'),
    path('config/equipes/<int:pk>/editar/', views.EquipeUpdateView.as_view(), name='equipe_update'),
    path('config/equipes/<int:pk>/excluir/', views.EquipeDeleteView.as_view(), name='equipe_delete'),

# ==================== NOTIFICAÇÕES ====================
    path('notificacoes/', views.NotificacaoListView.as_view(), name='notificacoes'),
    path('notificacoes/<int:pk>/ler/', views.marcar_notificacao_lida, name='notificacao_lida'),
    path('notificacoes/ler-todas/', views.marcar_todas_lidas, name='notificacoes_ler_todas'),
    path('api/notificacoes/count/', views.notificacoes_count, name='notificacoes_count'),

    # ==================== AJAX / API ====================
    path('api/urgencias/<int:categoria_id>/', views.urgencias_por_categoria, name='urgencias_por_categoria'),
    path('api/justificativas/<int:status_id>/', views.justificativas_por_status, name='justificativas_por_status'),
    path('api/toggle/<str:model_name>/<int:pk>/', views.toggle_ativo, name='toggle_ativo'),

    # Configuração de e-mail (admin do cliente)
    path(
        'config/configuracao-email/',
        views.ConfiguracaoEmailView.as_view(),
        name='configuracao_email',
    ),
    path(
        'config/configuracao-email/testar/',
        views.ConfiguracaoEmailTesteView.as_view(),
        name='configuracao_email_teste',
    ),

    # ==================== API AGENTE ====================
    path('api/agent/list/', views.AgentTicketListAPIView.as_view(), name='agent_ticket_list'),
    path('api/agent/criar/', views.AgentTicketCreateAPIView.as_view(), name='agent_ticket_create'),
    path('api/agent/<int:pk>/', views.AgentTicketDetailAPIView.as_view(), name='agent_ticket_detail'),
    path('api/agent/<int:pk>/reply/', views.AgentTicketReplyAPIView.as_view(), name='agent_ticket_reply'),

    # ==================== RELATÓRIOS ====================
    path('relatorio/', views.RelatorioTicketsView.as_view(), name='relatorio'),
    path('relatorio/exportar-csv/', views.exportar_tickets_csv, name='exportar_csv'),
]