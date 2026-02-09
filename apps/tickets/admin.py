from django.contrib import admin
from .models import (
    Categoria, Urgencia, CategoriaUrgencia, Status, Justificativa, Servico,
    ContratoSLA, RegraSLA, CampoAdicional, RegraExibicaoCampo,
    Ticket, AcaoTicket, AnexoTicket, HistoricoTicket,
    Gatilho, Macro, PesquisaSatisfacao
)


# ==================== CLASSIFICAÇÕES ====================

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'disponivel_para', 'ativo', 'cliente', 'criado_em']
    list_filter = ['disponivel_para', 'ativo', 'criado_em']
    search_fields = ['nome', 'descricao']
    date_hierarchy = 'criado_em'


@admin.register(Urgencia)
class UrgenciaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'nivel', 'cor', 'ativo', 'cliente', 'criado_em']
    list_filter = ['ativo', 'nivel', 'criado_em']
    search_fields = ['nome']
    date_hierarchy = 'criado_em'


@admin.register(CategoriaUrgencia)
class CategoriaUrgenciaAdmin(admin.ModelAdmin):
    list_display = ['categoria', 'urgencia']
    list_filter = ['categoria', 'urgencia']


@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ['nome', 'status_base', 'requer_justificativa', 'disponivel_para', 'ordem', 'ativo', 'cliente']
    list_filter = ['status_base', 'requer_justificativa', 'disponivel_para', 'ativo']
    search_fields = ['nome']
    ordering = ['ordem', 'nome']

    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editando
            return ['status_base']
        return []


@admin.register(Justificativa)
class JustificativaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ativo', 'cliente', 'criado_em']
    list_filter = ['ativo', 'criado_em']
    search_fields = ['nome', 'descricao']
    date_hierarchy = 'criado_em'


@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ativo', 'cliente', 'criado_em']
    list_filter = ['ativo', 'criado_em']
    search_fields = ['nome', 'descricao']
    date_hierarchy = 'criado_em'


# ==================== SLA ====================

class RegraSLAInline(admin.TabularInline):
    model = RegraSLA
    extra = 0
    fields = ['nome', 'ordem', 'prazo_solucao', 'tipo_horario', 'ativo']
    ordering = ['ordem']


@admin.register(ContratoSLA)
class ContratoSLAAdmin(admin.ModelAdmin):
    list_display = ['nome', 'is_padrao', 'ativo', 'cliente', 'criado_em']
    list_filter = ['is_padrao', 'ativo', 'criado_em']
    search_fields = ['nome', 'descricao']
    date_hierarchy = 'criado_em'
    inlines = [RegraSLAInline]


@admin.register(RegraSLA)
class RegraSLAAdmin(admin.ModelAdmin):
    list_display = ['nome', 'contrato', 'ordem', 'prazo_solucao', 'tipo_horario', 'ativo']
    list_filter = ['contrato', 'tipo_horario', 'ativo']
    search_fields = ['nome']
    filter_horizontal = ['categorias', 'urgencias', 'servicos', 'status_pausam', 'justificativas_pausam']
    ordering = ['contrato', 'ordem']


# ==================== CAMPOS ADICIONAIS ====================

@admin.register(CampoAdicional)
class CampoAdicionalAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'ativo', 'cliente', 'criado_em']
    list_filter = ['tipo', 'ativo', 'criado_em']
    search_fields = ['nome', 'descricao']
    date_hierarchy = 'criado_em'


@admin.register(RegraExibicaoCampo)
class RegraExibicaoCampoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'campo', 'exibir_para', 'obrigatoriedade', 'ordem', 'ativo']
    list_filter = ['exibir_para', 'obrigatoriedade', 'ativo']
    search_fields = ['nome']
    ordering = ['ordem']


# ==================== TICKETS ====================

class AcaoTicketInline(admin.TabularInline):
    model = AcaoTicket
    extra = 0
    fields = ['tipo', 'autor', 'conteudo', 'criado_em']
    readonly_fields = ['criado_em']
    ordering = ['-criado_em']


class AnexoTicketInline(admin.TabularInline):
    model = AnexoTicket
    extra = 0
    fields = ['nome_original', 'tamanho', 'autor', 'criado_em']
    readonly_fields = ['tamanho', 'criado_em']


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        'numero', 'assunto', 'solicitante', 'responsavel', 'status',
        'categoria', 'urgencia', 'previsao_solucao', 'criado_em'
    ]
    list_filter = [
        'status__status_base', 'categoria', 'urgencia', 'tipo_ticket',
        'canal_abertura', 'criado_em'
    ]
    search_fields = ['numero', 'assunto', 'descricao', 'solicitante__username', 'solicitante__email']
    date_hierarchy = 'criado_em'
    readonly_fields = ['numero', 'criado_em', 'atualizado_em', 'tempo_pausado']
    filter_horizontal = ['tickets_mesclados', 'tickets_relacionados']

    fieldsets = (
        ('Identificação', {
            'fields': ('numero', 'solicitante', 'tipo_ticket', 'canal_abertura')
        }),
        ('Classificação', {
            'fields': ('status', 'categoria', 'urgencia', 'servico', 'justificativa', 'responsavel')
        }),
        ('Conteúdo', {
            'fields': ('assunto', 'descricao', 'tags', 'cc')
        }),
        ('SLA', {
            'fields': ('contrato_sla', 'regra_sla_aplicada', 'previsao_solucao', 'previsao_manual',
                       'primeira_resposta_em'),
            'classes': ('collapse',)
        }),
        ('Relacionamentos', {
            'fields': ('ticket_pai', 'tickets_mesclados', 'tickets_relacionados'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('tempo_pausado', 'pausado_em', 'criado_em', 'atualizado_em', 'resolvido_em', 'fechado_em',
                       'cancelado_em'),
            'classes': ('collapse',)
        }),
        ('Campos Adicionais', {
            'fields': ('campos_adicionais',),
            'classes': ('collapse',)
        }),
    )

    inlines = [AcaoTicketInline, AnexoTicketInline]


@admin.register(AcaoTicket)
class AcaoTicketAdmin(admin.ModelAdmin):
    list_display = ['ticket', 'tipo', 'autor', 'criado_em']
    list_filter = ['tipo', 'criado_em']
    search_fields = ['ticket__numero', 'conteudo', 'autor__username']
    date_hierarchy = 'criado_em'
    readonly_fields = ['criado_em', 'editado_em']


@admin.register(AnexoTicket)
class AnexoTicketAdmin(admin.ModelAdmin):
    list_display = ['ticket', 'nome_original', 'tamanho', 'tipo_mime', 'autor', 'criado_em']
    list_filter = ['tipo_mime', 'criado_em']
    search_fields = ['ticket__numero', 'nome_original']
    date_hierarchy = 'criado_em'
    readonly_fields = ['tamanho', 'criado_em']


@admin.register(HistoricoTicket)
class HistoricoTicketAdmin(admin.ModelAdmin):
    list_display = ['ticket', 'campo', 'usuario', 'criado_em']
    list_filter = ['campo', 'criado_em']
    search_fields = ['ticket__numero', 'valor_anterior', 'valor_novo']
    date_hierarchy = 'criado_em'
    readonly_fields = ['criado_em']


# ==================== AUTOMAÇÕES ====================

@admin.register(Gatilho)
class GatilhoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ordem', 'ativo', 'cliente', 'criado_em']
    list_filter = ['ativo', 'criado_em']
    search_fields = ['nome', 'descricao']
    ordering = ['ordem', 'nome']


@admin.register(Macro)
class MacroAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ativo', 'cliente', 'criado_em']
    list_filter = ['ativo', 'criado_em']
    search_fields = ['nome', 'descricao']


# ==================== PESQUISA DE SATISFAÇÃO ====================

@admin.register(PesquisaSatisfacao)
class PesquisaSatisfacaoAdmin(admin.ModelAdmin):
    list_display = ['ticket', 'nota', 'enviada_em', 'respondida_em']
    list_filter = ['nota', 'enviada_em', 'respondida_em']
    search_fields = ['ticket__numero', 'comentario']
    date_hierarchy = 'enviada_em'
    readonly_fields = ['enviada_em']