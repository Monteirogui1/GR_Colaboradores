import csv

from django.db.models.functions import TruncDate
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse, FileResponse
from django.db.models import Q, Count, Avg, F, ExpressionWrapper, DurationField
from django.utils import timezone
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from apps.inventory.views import AgentTokenRequiredMixin
from datetime import datetime, timedelta
import json
import zipfile
import io

from .models import (
    Ticket, AcaoTicket, AnexoTicket, HistoricoTicket,
    Categoria, Urgencia, Status, Justificativa, Servico,
    ContratoSLA, RegraSLA, StatusBase, PesquisaSatisfacao,
    CampoAdicional, RegraExibicaoCampo,
    Gatilho, Macro, CategoriaUrgencia, ConfiguracaoEmail, Feriado, HorarioAtendimento, TemplateResposta,
    NotificacaoTicket, Equipe
)
from .forms import (
    TicketForm, TicketFiltroForm, AcaoTicketForm, AnexoTicketForm,
    AlterarStatusForm, AlterarResponsavelForm, MesclarTicketsForm,
    ReabrirTicketForm, AlterarPrevisaoSLAForm, CategoriaForm,
    UrgenciaForm, StatusForm, JustificativaForm, ServicoForm,
    ContratoSLAForm, RegraSLAForm, CampoAdicionalForm, RegraExibicaoCampoForm,
    GatilhoForm, MacroForm, ConfiguracaoEmailForm, FeriadoForm, HorarioAtendimentoForm, TemplateRespostaForm, EquipeForm
)
from apps.inventory.models import AgentTokenUsage


# ==================== MIXINS ====================

class ClienteQuerySetMixin:
    """Mixin para filtrar por cliente (multi-tenancy)"""

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_superuser:
            return queryset

        cliente = user if user.is_staff else user
        return queryset.filter(cliente=cliente)


class ClienteObjectMixin:
    """Mixin para validar acesso a objeto específico"""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user

        if user.is_superuser:
            return obj

        cliente = user if user.is_staff else user
        if hasattr(obj, 'cliente') and obj.cliente != cliente:
            raise PermissionDenied("Você não tem permissão para acessar este objeto")

        return obj


class ClienteCreateMixin:
    """Mixin para associar cliente na criação"""

    def form_valid(self, form):
        user = self.request.user
        cliente = user if user.is_staff else user
        form.instance.cliente = cliente
        return super().form_valid(form)


# ─── Helper: listas de opções para o template do gatilho ──────────────────────
def _gatilho_context(user):
    """
    Retorna dicionário com listas JSON usadas pelo template do gatilho
    para popular os selects de condições e ações dinamicamente.
    """
    cliente = user

    def to_json(qs, label_field='nome'):
        return json.dumps([{'v': str(obj.pk), 'l': getattr(obj, label_field)} for obj in qs])

    return {
        'status_list_json': to_json(Status.objects.filter(ativo=True).order_by('ordem', 'nome')),
        'categoria_list_json': to_json(Categoria.objects.filter(ativo=True).order_by('nome')),
        'urgencia_list_json': to_json(Urgencia.objects.filter(ativo=True).order_by('nivel')),
        'servico_list_json': to_json(Servico.objects.filter(ativo=True).order_by('nome')),
        'justificativa_list_json': to_json(Justificativa.objects.filter(ativo=True).order_by('nome')),
    }


# ==================== DASHBOARD ====================

class TicketDashboardView(LoginRequiredMixin, ListView):
    """Dashboard principal de tickets"""
    model = Ticket
    template_name = 'tickets/dashboard.html'
    context_object_name = 'tickets'

    def get_queryset(self):
        user = self.request.user
        cliente = user if user.is_staff else user

        # Tickets não concluídos por padrão
        queryset = Ticket.objects.filter(cliente=cliente).exclude(
            status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
        ).select_related(
            'solicitante', 'responsavel', 'status', 'categoria', 'urgencia'
        ).order_by('-criado_em')

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        cliente = user if user.is_staff else user

        # Estatísticas
        hoje = timezone.now().date()
        inicio_mes = hoje.replace(day=1)

        tickets_query = Ticket.objects.filter(cliente=cliente)

        # Estatísticas de Tickets
        context['stats'] = {
            'total_abertos': tickets_query.exclude(
                status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
            ).count(),
            'novos_hoje': tickets_query.filter(criado_em__date=hoje).count(),
            'vencidos': tickets_query.filter(
                previsao_solucao__lt=timezone.now()
            ).exclude(
                status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO, StatusBase.RESOLVIDO]
            ).count(),
            'resolvidos_mes': tickets_query.filter(
                resolvido_em__gte=inicio_mes,
                status__status_base=StatusBase.RESOLVIDO
            ).count(),
        }

        # Estatísticas de Ativos (se o app ativos estiver disponível)
        try:
            from apps.ativos.models import Ativo
            context['stats']['total_ativos'] = Ativo.objects.filter(
                cliente=cliente
            ).count()
            context['stats']['ativos_ativos'] = Ativo.objects.filter(
                cliente=cliente,
                status__nome__icontains='ativo'
            ).count()
        except (ImportError, Exception):
            context['stats']['total_ativos'] = 0
            context['stats']['ativos_ativos'] = 0

        # Estatísticas de Máquinas (se o app inventory estiver disponível)
        try:
            from apps.inventory.models import Machine
            context['stats']['total_maquinas'] = Machine.objects.filter(
                cliente=cliente
            ).count()
            context['stats']['maquinas_online'] = Machine.objects.filter(
                cliente=cliente,
                is_online=True
            ).count()
        except (ImportError, Exception):
            context['stats']['total_maquinas'] = 0
            context['stats']['maquinas_online'] = 0

        # Tickets por status
        context['por_status'] = tickets_query.values(
            'status__nome', 'status__cor'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        # Tickets por categoria
        context['por_categoria'] = tickets_query.values(
            'categoria__nome'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        # Meus tickets (se for agente)
        if user.is_staff:
            context['meus_tickets'] = tickets_query.filter(
                responsavel=user
            ).exclude(
                status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
            ).count()

        return context


# ==================== LISTAGEM E DETALHES ====================

class TicketListView(LoginRequiredMixin, ClienteQuerySetMixin, ListView):
    """Listagem de tickets com filtros"""
    model = Ticket
    template_name = 'tickets/ticket_list.html'
    context_object_name = 'tickets'
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.select_related(
            'solicitante', 'responsavel', 'status', 'categoria', 'urgencia', 'servico'
        ).order_by('-criado_em')

        # Filtros
        form = TicketFiltroForm(self.request.GET, usuario=self.request.user)

        if form.is_valid():
            if form.cleaned_data.get('numero'):
                queryset = queryset.filter(numero__icontains=form.cleaned_data['numero'])

            if form.cleaned_data.get('solicitante'):
                queryset = queryset.filter(
                    Q(solicitante__username__icontains=form.cleaned_data['solicitante']) |
                    Q(solicitante__email__icontains=form.cleaned_data['solicitante']) |
                    Q(solicitante__first_name__icontains=form.cleaned_data['solicitante'])
                )

            if form.cleaned_data.get('assunto'):
                queryset = queryset.filter(assunto__icontains=form.cleaned_data['assunto'])

            if form.cleaned_data.get('status'):
                queryset = queryset.filter(status=form.cleaned_data['status'])

            if form.cleaned_data.get('categoria'):
                queryset = queryset.filter(categoria=form.cleaned_data['categoria'])

            if form.cleaned_data.get('urgencia'):
                queryset = queryset.filter(urgencia=form.cleaned_data['urgencia'])

            if form.cleaned_data.get('responsavel'):
                queryset = queryset.filter(responsavel=form.cleaned_data['responsavel'])

            if form.cleaned_data.get('data_inicio'):
                queryset = queryset.filter(criado_em__date__gte=form.cleaned_data['data_inicio'])

            if form.cleaned_data.get('data_fim'):
                queryset = queryset.filter(criado_em__date__lte=form.cleaned_data['data_fim'])

            if form.cleaned_data.get('nao_concluidos'):
                queryset = queryset.exclude(
                    status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
                )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filtro_form'] = TicketFiltroForm(self.request.GET, usuario=self.request.user)

        # Visualização (lista ou kanban)
        context['visualizacao'] = self.request.GET.get('view', 'lista')

        return context


class TicketDetailView(LoginRequiredMixin, ClienteObjectMixin, DetailView):
    """Detalhes do ticket"""
    model = Ticket
    template_name = 'tickets/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'solicitante', 'responsavel', 'status', 'categoria',
            'urgencia', 'servico', 'justificativa', 'contrato_sla',
            'regra_sla_aplicada', 'ticket_pai',
            'machine',
        ).prefetch_related(
            'acoes__autor',
            'anexos',
            'historico__usuario',
            'tickets_filhos',
            'tickets_mesclados',
            'tickets_relacionados'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Formulários
        context['acao_form'] = AcaoTicketForm(usuario=self.request.user)
        context['anexo_form'] = AnexoTicketForm()
        context['alterar_status_form'] = AlterarStatusForm(
            usuario=self.request.user,
            ticket=self.object
        )
        context['alterar_responsavel_form'] = AlterarResponsavelForm()

        # Ações do ticket (mais nova primeiro)
        context['acoes'] = self.object.acoes.all().order_by('-criado_em')

        # Anexos
        context['anexos'] = self.object.anexos.all().order_by('-criado_em')

        # Histórico
        context['historico'] = self.object.historico.all().order_by('-criado_em')[:20]

        # Assinatura do agente (para o editor Quill)
        assinatura = ''
        if self.request.user.is_staff:
            assinatura = getattr(self.request.user, 'assinatura', '') or ''
        context['assinatura_json'] = json.dumps(assinatura)

        # Templates de resposta rápida
        from apps.tickets.models import TemplateResposta
        context['templates_resposta'] = TemplateResposta.objects.filter(
            cliente=self.object.cliente, ativo=True
        ).order_by('nome')

        # Ativos vinculados
        try:
            context['ativos_vinculados'] = self.object.ativos.select_related(
                'categoria', 'status'
            ).all()
        except Exception:
            context['ativos_vinculados'] = []

        # Informações de SLA
        if self.object.regra_sla_aplicada:
            context['sla_info'] = {
                'contrato': self.object.contrato_sla,
                'regra': self.object.regra_sla_aplicada,
                'previsao': self.object.previsao_solucao,
                'vencido': self.object.esta_vencido,
                'percentual': self.object.percentual_sla_usado,
            }

        return context


# ==================== CRIAÇÃO E EDIÇÃO ====================

class TicketCreateView(LoginRequiredMixin, CreateView):
    """Criação de novo ticket"""
    model = Ticket
    form_class = TicketForm
    template_name = 'tickets/ticket_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        user = self.request.user
        cliente = user if user.is_staff else user

        # Status padrão (Novo)
        status_novo = Status.objects.filter(
            cliente=cliente,
            status_base=StatusBase.NOVO,
            ativo=True
        ).first()

        if status_novo:
            initial['status'] = status_novo

        # Se não for agente, define como solicitante
        if not user.is_staff:
            initial['solicitante'] = user

        return initial

    def form_valid(self, form):
        user = self.request.user
        cliente = user if user.is_staff else user

        form.instance.cliente = cliente
        form.instance.canal_abertura = 'web'

        response = super().form_valid(form)

        # Distribuição automática por equipe (substitui o TODO)
        from apps.tickets.views import distribuir_ticket_para_equipe
        if self.object.equipe and not self.object.responsavel:
            distribuir_ticket_para_equipe(self.object)

        # Registra histórico
        HistoricoTicket.objects.create(
            ticket=self.object,
            usuario=user,
            campo='criacao',
            valor_novo='Ticket criado'
        )

        messages.success(self.request, f'Ticket #{self.object.numero} criado com sucesso!')
        return response

    def get_success_url(self):
        return reverse('tickets:ticket_detail', kwargs={'pk': self.object.pk})


class TicketUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    """Edição de ticket"""
    model = Ticket
    form_class = TicketForm
    template_name = 'tickets/ticket_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Rastreia alterações
        original = Ticket.objects.get(pk=self.object.pk)

        response = super().form_valid(form)

        # Registra histórico de alterações
        campos_rastreados = [
            'status', 'categoria', 'urgencia', 'servico', 'justificativa',
            'responsavel', 'assunto', 'previsao_solucao'
        ]

        for campo in campos_rastreados:
            valor_original = getattr(original, campo)
            valor_novo = getattr(self.object, campo)

            if valor_original != valor_novo:
                HistoricoTicket.objects.create(
                    ticket=self.object,
                    usuario=self.request.user,
                    campo=campo,
                    valor_anterior=str(valor_original) if valor_original else '',
                    valor_novo=str(valor_novo) if valor_novo else ''
                )

        messages.success(self.request, 'Ticket atualizado com sucesso!')
        return response

    def get_success_url(self):
        return reverse('tickets:ticket_detail', kwargs={'pk': self.object.pk})


class TicketDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    """Exclusão de ticket"""
    model = Ticket
    success_url = reverse_lazy('tickets:ticket_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Verifica se pode excluir
        if self.object.status.status_base == StatusBase.FECHADO:
            messages.error(request, 'Não é possível excluir tickets fechados')
            return redirect('tickets:ticket_detail', pk=self.object.pk)

        messages.success(request, f'Ticket #{self.object.numero} excluído com sucesso')
        return super().delete(request, *args, **kwargs)


# ==================== TEMPLATES DE RESPOSTA ====================

class TemplateRespostaListView(LoginRequiredMixin, ListView):
    model = TemplateResposta
    template_name = 'tickets/config/template_resposta_list.html'
    context_object_name = 'templates'
    ordering = ['ordem', 'nome']

    def get_queryset(self):
        return TemplateResposta.objects.filter(cliente=self.request.user)


class TemplateRespostaCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = TemplateResposta
    form_class = TemplateRespostaForm
    template_name = 'tickets/config/template_resposta_form.html'
    success_url = reverse_lazy('tickets:template_resposta_list')

    def form_valid(self, form):
        # Captura HTML do Quill se enviado
        html = self.request.POST.get('conteudo_html', '').strip()
        if html and html != '<p><br></p>':
            form.instance.conteudo = html
        messages.success(self.request, 'Template criado com sucesso!')
        return super().form_valid(form)


class TemplateRespostaUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = TemplateResposta
    form_class = TemplateRespostaForm
    template_name = 'tickets/config/template_resposta_form.html'
    success_url = reverse_lazy('tickets:template_resposta_list')

    def form_valid(self, form):
        html = self.request.POST.get('conteudo_html', '').strip()
        if html and html != '<p><br></p>':
            form.instance.conteudo = html
        messages.success(self.request, 'Template atualizado com sucesso!')
        return super().form_valid(form)


class TemplateRespostaDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = TemplateResposta
    success_url = reverse_lazy('tickets:template_resposta_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Template excluído com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== AÇÕES NO TICKET ====================

@login_required
def adicionar_acao(request, pk):
    """Adiciona ação (resposta) ao ticket"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST':
        form = AcaoTicketForm(request.POST, usuario=request.user)

        if form.is_valid():
            acao = form.save(commit=False)
            acao.ticket = ticket
            acao.autor = request.user
            acao.save()

            # Aplica macro se selecionada
            if form.cleaned_data.get('aplicar_macro'):
                aplicar_macro_ao_ticket(ticket, form.cleaned_data['aplicar_macro'], request.user)

            messages.success(request, 'Ação adicionada com sucesso!')
            return redirect('tickets:ticket_detail', pk=ticket.pk)

    return redirect('tickets:ticket_detail', pk=ticket.pk)


@login_required
def adicionar_anexo(request, pk):
    """Adiciona anexo ao ticket"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST' and request.FILES.get('arquivo'):
        for arquivo in request.FILES.getlist('arquivo'):
            AnexoTicket.objects.create(
                ticket=ticket,
                arquivo=arquivo,
                nome_original=arquivo.name,
                tamanho=arquivo.size,
                tipo_mime=arquivo.content_type,
                autor=request.user
            )

        messages.success(request, 'Anexo(s) adicionado(s) com sucesso!')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


@login_required
def alterar_status_rapido(request, pk):
    """Altera status do ticket rapidamente"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST':
        form = AlterarStatusForm(request.POST, usuario=request.user, ticket=ticket)

        if form.is_valid():
            status_anterior = ticket.status

            ticket.status = form.cleaned_data['status']
            ticket.justificativa = form.cleaned_data.get('justificativa')
            ticket.save()

            # Registra histórico
            HistoricoTicket.objects.create(
                ticket=ticket,
                usuario=request.user,
                campo='status',
                valor_anterior=str(status_anterior),
                valor_novo=str(ticket.status)
            )

            # Adiciona ação se fornecida
            if form.cleaned_data.get('adicionar_acao'):
                AcaoTicket.objects.create(
                    ticket=ticket,
                    tipo='interna',
                    autor=request.user,
                    conteudo=form.cleaned_data['adicionar_acao']
                )

            messages.success(request, 'Status alterado com sucesso!')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


@login_required
def alterar_responsavel_rapido(request, pk):
    """Altera responsável do ticket rapidamente"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST':
        form = AlterarResponsavelForm(request.POST)

        if form.is_valid():
            responsavel_anterior = ticket.responsavel

            ticket.responsavel = form.cleaned_data['responsavel']
            ticket.save()

            # Registra histórico
            HistoricoTicket.objects.create(
                ticket=ticket,
                usuario=request.user,
                campo='responsavel',
                valor_anterior=str(responsavel_anterior) if responsavel_anterior else '',
                valor_novo=str(ticket.responsavel)
            )

            # TODO: Notificar novo responsável se marcado

            messages.success(request, 'Responsável alterado com sucesso!')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


# ==================== HELPER FUNCTIONS ====================

def aplicar_macro_ao_ticket(ticket, macro, usuario):
    """Aplica uma macro ao ticket"""
    try:
        acoes = macro.acoes

        # Altera campos conforme macro
        campos_alterados = []

        if 'status' in acoes:
            status = Status.objects.get(pk=acoes['status'])
            ticket.status = status
            campos_alterados.append(f'Status alterado para {status}')

        if 'responsavel' in acoes:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            responsavel = User.objects.get(pk=acoes['responsavel'])
            ticket.responsavel = responsavel
            campos_alterados.append(f'Responsável alterado para {responsavel}')

        if 'adicionar_acao' in acoes:
            AcaoTicket.objects.create(
                ticket=ticket,
                tipo='interna',
                autor=usuario,
                conteudo=f"[MACRO: {macro.nome}] {acoes['adicionar_acao']}"
            )

        ticket.save()

        # Registra no histórico
        if campos_alterados:
            HistoricoTicket.objects.create(
                ticket=ticket,
                usuario=usuario,
                campo='macro_aplicada',
                valor_novo=f"Macro '{macro.nome}' aplicada: " + ', '.join(campos_alterados)
            )

        return True
    except Exception as e:
        return False


# ==================== AÇÕES NO TICKET ====================

@login_required
def adicionar_acao(request, pk):
    """Adiciona ação (resposta) ao ticket — com suporte a rich text"""
    ticket = get_object_or_404(Ticket, pk=pk)

    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST':
        form = AcaoTicketForm(request.POST, usuario=request.user)

        if form.is_valid():
            acao = form.save(commit=False)
            acao.ticket = ticket
            acao.autor = request.user

            # NOVO: salva HTML do Quill em conteudo_html
            conteudo_html = request.POST.get('conteudo_html', '').strip()
            if conteudo_html and conteudo_html != '<p><br></p>':
                acao.conteudo_html = conteudo_html
                # Extrai texto plano para conteudo (fallback e busca)
                import re
                texto_plano = re.sub(r'<[^>]+>', '', conteudo_html).strip()
                acao.conteudo = texto_plano or acao.conteudo

            acao.save()

            if form.cleaned_data.get('aplicar_macro'):
                aplicar_macro_ao_ticket(ticket, form.cleaned_data['aplicar_macro'], request.user)

            messages.success(request, 'Ação adicionada com sucesso!')
            return redirect('tickets:ticket_detail', pk=ticket.pk)

    return redirect('tickets:ticket_detail', pk=ticket.pk)



@login_required
def adicionar_anexo(request, pk):
    """Adiciona anexo ao ticket"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST' and request.FILES.get('arquivo'):
        for arquivo in request.FILES.getlist('arquivo'):
            AnexoTicket.objects.create(
                ticket=ticket,
                arquivo=arquivo,
                nome_original=arquivo.name,
                tamanho=arquivo.size,
                tipo_mime=arquivo.content_type,
                autor=request.user
            )

        messages.success(request, 'Anexo(s) adicionado(s) com sucesso!')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


@login_required
def alterar_status_rapido(request, pk):
    """Altera status do ticket rapidamente"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST':
        form = AlterarStatusForm(request.POST, usuario=request.user, ticket=ticket)

        if form.is_valid():
            status_anterior = ticket.status

            ticket.status = form.cleaned_data['status']
            ticket.justificativa = form.cleaned_data.get('justificativa')
            ticket.save()

            # Registra histórico
            HistoricoTicket.objects.create(
                ticket=ticket,
                usuario=request.user,
                campo='status',
                valor_anterior=str(status_anterior),
                valor_novo=str(ticket.status)
            )

            # Adiciona ação se fornecida
            if form.cleaned_data.get('adicionar_acao'):
                AcaoTicket.objects.create(
                    ticket=ticket,
                    tipo='interna',
                    autor=request.user,
                    conteudo=form.cleaned_data['adicionar_acao']
                )

            messages.success(request, 'Status alterado com sucesso!')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


@login_required
def alterar_responsavel_rapido(request, pk):
    """Altera responsável do ticket rapidamente"""
    ticket = get_object_or_404(Ticket, pk=pk)

    # Verifica acesso
    if not request.user.is_superuser:
        cliente = request.user if request.user.is_staff else request.user
        if ticket.cliente != cliente:
            raise PermissionDenied()

    if request.method == 'POST':
        form = AlterarResponsavelForm(request.POST)

        if form.is_valid():
            responsavel_anterior = ticket.responsavel

            ticket.responsavel = form.cleaned_data['responsavel']
            ticket.save()

            # Registra histórico
            HistoricoTicket.objects.create(
                ticket=ticket,
                usuario=request.user,
                campo='responsavel',
                valor_anterior=str(responsavel_anterior) if responsavel_anterior else '',
                valor_novo=str(ticket.responsavel)
            )

            # TODO: Notificar novo responsável se marcado

            messages.success(request, 'Responsável alterado com sucesso!')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


# ==================== ATIVOS DO TICKET ====================

@login_required
def gerenciar_ativos_ticket(request, pk):
    """Vincula ou desvincula ativos do ticket via POST"""
    ticket = get_object_or_404(Ticket, pk=pk)

    if not request.user.is_superuser:
        if ticket.cliente != (request.user if request.user.is_staff else request.user):
            raise PermissionDenied()

    if request.method == 'POST':
        acao = request.POST.get('acao')  # 'adicionar' ou 'remover'
        ativo_id = request.POST.get('ativo_id')

        try:
            from apps.ativos.models import Ativo
            ativo = get_object_or_404(Ativo, pk=ativo_id)

            if acao == 'adicionar':
                ticket.ativos.add(ativo)
                HistoricoTicket.objects.create(
                    ticket=ticket,
                    usuario=request.user,
                    campo='ativo_vinculado',
                    valor_novo=f"{ativo.etiqueta} — {ativo.nome}"
                )
                messages.success(request, f'Ativo "{ativo.etiqueta} — {ativo.nome}" vinculado.')

            elif acao == 'remover':
                ticket.ativos.remove(ativo)
                HistoricoTicket.objects.create(
                    ticket=ticket,
                    usuario=request.user,
                    campo='ativo_desvinculado',
                    valor_anterior=f"{ativo.etiqueta} — {ativo.nome}"
                )
                messages.success(request, f'Ativo "{ativo.etiqueta}" desvinculado.')

        except Exception as e:
            messages.error(request, f'Erro: {str(e)}')

    return redirect('tickets:ticket_detail', pk=ticket.pk)


@login_required
def buscar_ativos_json(request, pk):
    """Retorna JSON com ativos disponíveis para vincular ao ticket (para autocomplete)"""
    from django.http import JsonResponse

    ticket = get_object_or_404(Ticket, pk=pk)
    q = request.GET.get('q', '').strip()

    try:
        from apps.ativos.models import Ativo
        ativos = Ativo.objects.filter(cliente=ticket.cliente)

        if q:
            ativos = ativos.filter(
                Q(nome__icontains=q) |
                Q(etiqueta__icontains=q) |
                Q(numero_serie__icontains=q)
            )

        # Excluir já vinculados
        ja_vinculados = ticket.ativos.values_list('pk', flat=True)
        ativos = ativos.exclude(pk__in=ja_vinculados).select_related('categoria', 'status')[:20]

        data = [
            {
                'id': a.pk,
                'etiqueta': a.etiqueta,
                'nome': a.nome,
                'categoria': a.categoria.nome if a.categoria else '',
                'status': a.status.nome if a.status else '',
                'status_cor': a.status.cor if a.status else '#888',
            }
            for a in ativos
        ]
        return JsonResponse({'ativos': data})

    except Exception as e:
        return JsonResponse({'ativos': [], 'erro': str(e)})

# ==================== CATEGORIAS ====================

class CategoriaListView(LoginRequiredMixin, ListView):
    model = Categoria
    template_name = 'tickets/config/categoria_list.html'
    context_object_name = 'categorias'
    ordering = ['nome']


class CategoriaCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'tickets/config/categoria_form.html'
    success_url = reverse_lazy('tickets:categoria_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        form._salvar_urgencias(self.object)  # Salva vínculos após criação (tem pk agora)
        messages.success(self.request, 'Categoria criada com sucesso!')
        return response


class CategoriaUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'tickets/config/categoria_form.html'
    success_url = reverse_lazy('tickets:categoria_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Categoria atualizada com sucesso!')
        return super().form_valid(form)


class CategoriaDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Categoria
    success_url = reverse_lazy('tickets:categoria_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Categoria excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== URGÊNCIAS ====================

class UrgenciaListView(LoginRequiredMixin, ListView):
    model = Urgencia
    template_name = 'tickets/config/urgencia_list.html'
    context_object_name = 'urgencia_list'
    ordering = ['nivel']


class UrgenciaCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Urgencia
    form_class = UrgenciaForm
    template_name = 'tickets/config/urgencia_form.html'
    success_url = reverse_lazy('tickets:urgencia_list')

    def form_valid(self, form):
        messages.success(self.request, 'Urgência criada com sucesso!')
        return super().form_valid(form)


class UrgenciaUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Urgencia
    form_class = UrgenciaForm
    template_name = 'tickets/config/urgencia_form.html'
    success_url = reverse_lazy('tickets:urgencia_list')

    def form_valid(self, form):
        messages.success(self.request, 'Urgência atualizada com sucesso!')
        return super().form_valid(form)


class UrgenciaDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Urgencia
    success_url = reverse_lazy('tickets:urgencia_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Urgência excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== STATUS ====================

class StatusListView(LoginRequiredMixin, ListView):
    model = Status
    template_name = 'tickets/config/status_list.html'
    context_object_name = 'status_list'
    ordering = ['ordem', 'nome']


class StatusCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Status
    form_class = StatusForm
    template_name = 'tickets/config/status_form.html'
    success_url = reverse_lazy('tickets:status_list')

    def form_valid(self, form):
        messages.success(self.request, 'Status criado com sucesso!')
        messages.warning(
            self.request,
            'Lembre-se: O status base não pode ser alterado após a criação!'
        )
        return super().form_valid(form)


class StatusUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Status
    form_class = StatusForm
    template_name = 'tickets/config/status_form.html'
    success_url = reverse_lazy('tickets:status_list')

    def form_valid(self, form):
        messages.success(self.request, 'Status atualizado com sucesso!')
        return super().form_valid(form)


class StatusDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Status
    success_url = reverse_lazy('tickets:status_list')

    def delete(self, request, *args, **kwargs):
        messages.warning(
            request,
            'Cuidado ao excluir status: pode afetar outras funcionalidades do sistema!'
        )
        return super().delete(request, *args, **kwargs)


# ==================== JUSTIFICATIVAS ====================

class JustificativaListView(LoginRequiredMixin, ListView):
    model = Justificativa
    template_name = 'tickets/config/justificativa_list.html'
    context_object_name = 'justificativas'
    ordering = ['nome']


class JustificativaCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Justificativa
    form_class = JustificativaForm
    template_name = 'tickets/config/justificativa_form.html'
    success_url = reverse_lazy('tickets:justificativa_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Justificativa criada com sucesso!')
        return super().form_valid(form)


class JustificativaUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Justificativa
    form_class = JustificativaForm
    template_name = 'tickets/config/justificativa_form.html'
    success_url = reverse_lazy('tickets:justificativa_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Justificativa atualizada com sucesso!')
        return super().form_valid(form)


class JustificativaDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Justificativa
    success_url = reverse_lazy('tickets:justificativa_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Justificativa excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== SERVIÇOS ====================

class ServicoListView(LoginRequiredMixin, ListView):
    model = Servico
    template_name = 'tickets/config/servico_list.html'
    context_object_name = 'servicos'
    ordering = ['nome']


class ServicoCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Servico
    form_class = ServicoForm
    template_name = 'tickets/config/servico_form.html'
    success_url = reverse_lazy('tickets:servico_list')

    def form_valid(self, form):
        messages.success(self.request, 'Serviço criado com sucesso!')
        return super().form_valid(form)


class ServicoUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Servico
    form_class = ServicoForm
    template_name = 'tickets/config/servico_form.html'
    success_url = reverse_lazy('tickets:servico_list')

    def form_valid(self, form):
        messages.success(self.request, 'Serviço atualizado com sucesso!')
        return super().form_valid(form)


class ServicoDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Servico
    success_url = reverse_lazy('tickets:servico_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Serviço excluído com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== CONTRATOS SLA ====================

class ContratoSLAListView(LoginRequiredMixin, ListView):
    model = ContratoSLA
    template_name = 'tickets/config/contrato_sla_list.html'
    context_object_name = 'contratos'
    ordering = ['-is_padrao', 'nome']


class ContratoSLACreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = ContratoSLA
    form_class = ContratoSLAForm
    template_name = 'tickets/config/contrato_sla_form.html'
    success_url = reverse_lazy('tickets:contrato_sla_list')

    def form_valid(self, form):
        messages.success(self.request, 'Contrato SLA criado com sucesso!')
        return super().form_valid(form)


class ContratoSLAUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = ContratoSLA
    form_class = ContratoSLAForm
    template_name = 'tickets/config/contrato_sla_form.html'
    success_url = reverse_lazy('tickets:contrato_sla_list')

    def form_valid(self, form):
        messages.success(self.request, 'Contrato SLA atualizado com sucesso!')
        return super().form_valid(form)


class ContratoSLADeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = ContratoSLA
    success_url = reverse_lazy('tickets:contrato_sla_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Contrato SLA excluído com sucesso!')
        return super().delete(request, *args, **kwargs)


class ContratoSLADetailView(LoginRequiredMixin, ClienteObjectMixin, ListView):
    """Visualiza regras de um contrato SLA"""
    model = RegraSLA
    template_name = 'tickets/config/contrato_sla_detail.html'
    context_object_name = 'regras'

    def get_queryset(self):
        self.contrato = get_object_or_404(ContratoSLA, pk=self.kwargs['pk'])
        return self.contrato.regras.all().order_by('ordem', 'nome')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['contrato'] = self.contrato
        return context


# ==================== REGRAS SLA ====================

class RegraSLACreateView(LoginRequiredMixin, CreateView):
    model = RegraSLA
    form_class = RegraSLAForm
    template_name = 'tickets/config/regra_sla_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.contrato = get_object_or_404(ContratoSLA, pk=kwargs['contrato_pk'])

        # Verifica acesso
        if not request.user.is_superuser:
            cliente = request.user if request.user.is_staff else request.user
            if self.contrato.cliente != cliente:
                raise PermissionDenied()

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.contrato = self.contrato
        messages.success(self.request, 'Regra SLA criada com sucesso!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('tickets:contrato_sla_detail', kwargs={'pk': self.contrato.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['contrato'] = self.contrato
        return context


class RegraSLAUpdateView(LoginRequiredMixin, UpdateView):
    model = RegraSLA
    form_class = RegraSLAForm
    template_name = 'tickets/config/regra_sla_form.html'

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()

        # Verifica acesso
        if not request.user.is_superuser:
            cliente = request.user if request.user.is_staff else request.user
            if obj.contrato.cliente != cliente:
                raise PermissionDenied()

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, 'Regra SLA atualizada com sucesso!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('tickets:contrato_sla_detail', kwargs={'pk': self.object.contrato.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['contrato'] = self.object.contrato
        return context


class RegraSLADeleteView(LoginRequiredMixin, DeleteView):
    model = RegraSLA

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()

        # Verifica acesso
        if not request.user.is_superuser:
            cliente = request.user if request.user.is_staff else request.user
            if obj.contrato.cliente != cliente:
                raise PermissionDenied()

        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        contrato_pk = self.get_object().contrato.pk
        messages.success(request, 'Regra SLA excluída com sucesso!')
        response = super().delete(request, *args, **kwargs)
        return response

    def get_success_url(self):
        return reverse_lazy('tickets:contrato_sla_detail', kwargs={'pk': self.object.contrato.pk})


# ==================== CAMPOS ADICIONAIS ====================

class CampoAdicionalListView(LoginRequiredMixin, ListView):
    model = CampoAdicional
    template_name = 'tickets/config/campo_adicional_list.html'
    context_object_name = 'campos'
    ordering = ['nome']


class CampoAdicionalCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = CampoAdicional
    form_class = CampoAdicionalForm
    template_name = 'tickets/config/campo_adicional_form.html'
    success_url = reverse_lazy('tickets:campo_adicional_list')

    def form_valid(self, form):
        messages.success(self.request, 'Campo adicional criado com sucesso!')
        return super().form_valid(form)


class CampoAdicionalUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = CampoAdicional
    form_class = CampoAdicionalForm
    template_name = 'tickets/config/campo_adicional_form.html'
    success_url = reverse_lazy('tickets:campo_adicional_list')

    def form_valid(self, form):
        messages.success(self.request, 'Campo adicional atualizado com sucesso!')
        return super().form_valid(form)


class CampoAdicionalDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = CampoAdicional
    success_url = reverse_lazy('tickets:campo_adicional_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Campo adicional excluído com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== REGRAS DE EXIBIÇÃO ====================

class RegraExibicaoCampoListView(LoginRequiredMixin, ListView):
    model = RegraExibicaoCampo
    template_name = 'tickets/config/regra_exibicao_list.html'
    context_object_name = 'regras'
    ordering = ['ordem', 'nome']


class RegraExibicaoCampoCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = RegraExibicaoCampo
    form_class = RegraExibicaoCampoForm
    template_name = 'tickets/config/regra_exibicao_form.html'
    success_url = reverse_lazy('tickets:regra_exibicao_list')

    def form_valid(self, form):
        messages.success(self.request, 'Regra de exibição criada com sucesso!')
        return super().form_valid(form)


class RegraExibicaoCampoUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = RegraExibicaoCampo
    form_class = RegraExibicaoCampoForm
    template_name = 'tickets/config/regra_exibicao_form.html'
    success_url = reverse_lazy('tickets:regra_exibicao_list')

    def form_valid(self, form):
        messages.success(self.request, 'Regra de exibição atualizada com sucesso!')
        return super().form_valid(form)


class RegraExibicaoCampoDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = RegraExibicaoCampo
    success_url = reverse_lazy('tickets:regra_exibicao_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Regra de exibição excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== GATILHOS ====================

class GatilhoListView(LoginRequiredMixin, ListView):
    model = Gatilho
    template_name = 'tickets/config/gatilho_list.html'
    context_object_name = 'gatilhos'
    ordering = ['ordem', 'nome']


class GatilhoCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Gatilho
    form_class = GatilhoForm
    template_name = 'tickets/config/gatilho_form.html'
    success_url = reverse_lazy('tickets:gatilho_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_gatilho_context(self.request.user))
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Gatilho criado com sucesso!')
        return super().form_valid(form)


class GatilhoUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Gatilho
    form_class = GatilhoForm
    template_name = 'tickets/config/gatilho_form.html'
    success_url = reverse_lazy('tickets:gatilho_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_gatilho_context(self.request.user))
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Gatilho atualizado com sucesso!')
        return super().form_valid(form)


class GatilhoDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Gatilho
    success_url = reverse_lazy('tickets:gatilho_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Gatilho excluído com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== MACROS ====================

class MacroListView(LoginRequiredMixin, ListView):
    model = Macro
    template_name = 'tickets/config/macro_list.html'
    context_object_name = 'macros'
    ordering = ['nome']

    def get_queryset(self):
        return super().get_queryset().filter(cliente=self.request.user)


class MacroCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Macro
    form_class = MacroForm
    template_name = 'tickets/config/macro_form.html'
    success_url = reverse_lazy('tickets:macro_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_macro_opcoes_contexto(self.request.user))
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Macro criada com sucesso!')
        return super().form_valid(form)


class MacroUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Macro
    form_class = MacroForm
    template_name = 'tickets/config/macro_form.html'
    success_url = reverse_lazy('tickets:macro_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_macro_opcoes_contexto(self.request.user))
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Macro atualizada com sucesso!')
        return super().form_valid(form)


class MacroDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Macro
    success_url = reverse_lazy('tickets:macro_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Macro excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


@login_required
def aplicar_macro_direto(request, pk):
    """
    Aplica uma macro diretamente ao ticket via POST, sem exigir texto de ação.
    Chamada AJAX pelo botão "Aplicar" no detail do ticket.

    POST body: { "macro_id": <int> }
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'erro': 'Método não permitido.'}, status=405)

    ticket = get_object_or_404(Ticket, pk=pk)
    if not request.user.is_superuser:
        if ticket.cliente != request.user and ticket.solicitante != request.user:
            return JsonResponse({'ok': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        macro_id = int(data.get('macro_id', 0))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'erro': 'macro_id inválido.'}, status=400)

    macro = get_object_or_404(Macro, pk=macro_id, ativo=True, cliente=request.user)
    ok = aplicar_macro_ao_ticket(ticket, macro, request.user)

    if ok:
        return JsonResponse({'ok': True, 'mensagem': f'Macro "{macro.nome}" aplicada.'})
    return JsonResponse({'ok': False, 'erro': 'Falha ao aplicar a macro.'}, status=500)


# ==================== HORÁRIO DE ATENDIMENTO ====================

class HorarioAtendimentoListView(LoginRequiredMixin, ListView):
    model = HorarioAtendimento
    template_name = 'tickets/config/horario_list.html'
    context_object_name = 'horarios'
    ordering = ['dia_semana', 'hora_inicio']

    def get_queryset(self):
        return super().get_queryset().filter(cliente=self.request.user)


class HorarioAtendimentoCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = HorarioAtendimento
    form_class = HorarioAtendimentoForm
    template_name = 'tickets/config/horario_form.html'
    success_url = reverse_lazy('tickets:horario_list')

    def form_valid(self, form):
        messages.success(self.request, 'Horário criado com sucesso!')
        return super().form_valid(form)


class HorarioAtendimentoUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = HorarioAtendimento
    form_class = HorarioAtendimentoForm
    template_name = 'tickets/config/horario_form.html'
    success_url = reverse_lazy('tickets:horario_list')

    def form_valid(self, form):
        messages.success(self.request, 'Horário atualizado com sucesso!')
        return super().form_valid(form)


class HorarioAtendimentoDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = HorarioAtendimento
    success_url = reverse_lazy('tickets:horario_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Horário excluído com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== FERIADOS ====================

class FeriadoListView(LoginRequiredMixin, ListView):
    model = Feriado
    template_name = 'tickets/config/feriado_list.html'
    context_object_name = 'feriados'
    ordering = ['data']

    def get_queryset(self):
        return super().get_queryset().filter(cliente=self.request.user)


class FeriadoCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Feriado
    form_class = FeriadoForm
    template_name = 'tickets/config/feriado_form.html'
    success_url = reverse_lazy('tickets:feriado_list')

    def form_valid(self, form):
        messages.success(self.request, 'Feriado criado com sucesso!')
        return super().form_valid(form)


class FeriadoUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Feriado
    form_class = FeriadoForm
    template_name = 'tickets/config/feriado_form.html'
    success_url = reverse_lazy('tickets:feriado_list')

    def form_valid(self, form):
        messages.success(self.request, 'Feriado atualizado com sucesso!')
        return super().form_valid(form)


class FeriadoDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Feriado
    success_url = reverse_lazy('tickets:feriado_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Feriado excluído com sucesso!')
        return super().delete(request, *args, **kwargs)



# ==================== AJAX / API ====================

@login_required
def justificativas_por_status(request, status_id):
    """
    BUG 1 FIX: Retorna justificativas válidas para o status selecionado (AJAX).
    Também retorna se o status exige justificativa obrigatória.
    """
    try:
        status = Status.objects.get(pk=status_id, cliente=request.user)
        vinculadas = status.justificativas_vinculadas.filter(ativo=True)

        if vinculadas.exists():
            justificativas = vinculadas
        else:
            justificativas = Justificativa.objects.filter(
                cliente=request.user, ativo=True
            )

        data = [{'id': j.id, 'nome': j.nome} for j in justificativas]
        return JsonResponse({
            'success': True,
            'justificativas': data,
            'requer_justificativa': status.requer_justificativa,
        })
    except Status.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Status não encontrado'}, status=404)


@login_required
def urgencias_por_categoria(request, categoria_id):
    """
    BUG 2 + BUG 3 FIX: Retorna urgências permitidas para a categoria selecionada (AJAX).
    Inclui flag 'restrito' para o front-end exibir hint adequado.
    """
    try:
        categoria = Categoria.objects.get(pk=categoria_id)
        urgencias_ids = categoria.urgencias_permitidas.values_list('urgencia_id', flat=True)

        if urgencias_ids:
            urgencias = Urgencia.objects.filter(id__in=urgencias_ids, ativo=True)
            restrito = True
        else:
            urgencias = Urgencia.objects.filter(cliente=categoria.cliente, ativo=True)
            restrito = False

        data = [
            {'id': u.id, 'nome': u.nome, 'nivel': u.nivel, 'cor': u.cor}
            for u in urgencias
        ]
        return JsonResponse({'success': True, 'urgencias': data, 'restrito': restrito})

    except Categoria.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Categoria não encontrada'}, status=404)


@login_required
def toggle_ativo(request, model_name, pk):
    """Ativa/desativa registro (AJAX)"""
    models_map = {
        'categoria': Categoria,
        'urgencia': Urgencia,
        'status': Status,
        'justificativa': Justificativa,
        'servico': Servico,
        'campo': CampoAdicional,
        'gatilho': Gatilho,
        'macro': Macro,
    }

    if model_name not in models_map:
        return JsonResponse({'success': False, 'error': 'Modelo inválido'}, status=400)

    try:
        model_class = models_map[model_name]
        obj = model_class.objects.get(pk=pk)

        # Verifica acesso
        if not request.user.is_superuser:
            cliente = request.user if request.user.is_staff else request.user
            if hasattr(obj, 'cliente') and obj.cliente != cliente:
                raise PermissionDenied()

        obj.ativo = not obj.ativo
        obj.save()

        return JsonResponse({
            'success': True,
            'ativo': obj.ativo,
            'message': f'{"Ativado" if obj.ativo else "Desativado"} com sucesso!'
        })

    except model_class.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Registro não encontrado'}, status=404)


class ConfiguracaoEmailView(LoginRequiredMixin, View):
    """
    View única que cria ou edita a ConfiguracaoEmail do cliente logado.
    Se já existe um registro → edita. Se não existe → cria.
    Acesso restrito a staff (administradores do cliente).
    """
    template_name = 'tickets/config/configuracao_email_form.html'

    def _get_instance(self, request):
        """Retorna a instância existente ou None."""
        try:
            return ConfiguracaoEmail.objects.get(cliente=request.user)
        except ConfiguracaoEmail.DoesNotExist:
            return None

    def get(self, request):
        if not request.user.is_staff:
            messages.error(request, 'Acesso restrito a administradores.')
            return redirect('tickets:dashboard')

        instance = self._get_instance(request)
        form = ConfiguracaoEmailForm(instance=instance)
        return render(request, self.template_name, {
            'form': form,
            'instance': instance,
            'presets': ConfiguracaoEmail.PRESETS,
        })

    def post(self, request):
        if not request.user.is_staff:
            messages.error(request, 'Acesso restrito a administradores.')
            return redirect('tickets:dashboard')

        instance = self._get_instance(request)
        form = ConfiguracaoEmailForm(request.POST, instance=instance)

        if form.is_valid():
            config = form.save(commit=False)
            config.cliente = request.user
            config.save()
            messages.success(request, '✅ Configuração de e-mail salva com sucesso.')
            return redirect('tickets:configuracao_email')

        messages.error(request, 'Corrija os erros abaixo.')
        return render(request, self.template_name, {
            'form': form,
            'instance': instance,
            'presets': ConfiguracaoEmail.PRESETS,
        })


@login_required
def template_resposta_preview(request, pk):
    """Retorna o conteúdo do template com variáveis substituídas (AJAX)."""
    tpl = get_object_or_404(TemplateResposta, pk=pk, cliente=request.user)
    ticket_id = request.GET.get('ticket_id')

    if ticket_id:
        try:
            ticket = Ticket.objects.get(pk=ticket_id, cliente=request.user)
            conteudo = tpl.substituir_variaveis(ticket)
        except Ticket.DoesNotExist:
            conteudo = tpl.conteudo
    else:
        conteudo = tpl.conteudo

    return JsonResponse({'success': True, 'conteudo': conteudo, 'nome': tpl.nome})


class ConfiguracaoEmailTesteView(LoginRequiredMixin, View):
    """
    Testa a conexão IMAP com as configurações salvas.
    POST /tickets/configuracao-email/testar/
    Retorna JSON com resultado do teste.
    """

    def post(self, request):
        if not request.user.is_staff:
            return JsonResponse({'success': False, 'error': 'Acesso negado.'}, status=403)

        try:
            config = ConfiguracaoEmail.objects.get(cliente=request.user, ativo=True)
        except ConfiguracaoEmail.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Nenhuma configuração ativa encontrada.'})

        import imaplib
        try:
            mail = imaplib.IMAP4_SSL(config.imap_server, config.imap_port)
            mail.login(config.email_usuario, config.get_senha())
            mail.select('INBOX')
            mail.logout()
            return JsonResponse({'success': True, 'message': f'Conexão com {config.imap_server} bem-sucedida.'})
        except imaplib.IMAP4.error as e:
            return JsonResponse({'success': False, 'error': f'Erro de autenticação IMAP: {e}'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Erro de conexão: {e}'})


@method_decorator(csrf_exempt, name='dispatch')
class AgentTicketListAPIView(AgentTokenRequiredMixin, APIView):
    """
    GET /tickets/api/agent/list/?email=X
    Authorization: Bearer <token_hash>
    X-Machine-Name: DESKTOP-ABC123       ← obrigatório (enviado pelo agent_service)
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()

        agent_token, err = self._authenticate(request)
        if err:
            return err

        email = request.GET.get("email", "").strip()
        logged_user = request.GET.get("logged_user", "").strip()

        if not email:
            return Response({'ok': False, 'error': 'Parâmetro email obrigatório.'}, status=400)

        solicitante = User.objects.filter(email=email).first()
        if not solicitante:
            return Response({'ok': True, 'tickets': [],
                             'warning': f'Usuário com e-mail {email} não cadastrado.'})

        # Resolve máquina (pode ser None se não encontrada — não bloqueia a listagem)
        machine = None
        machine_name = self._get_machine_name(request, agent_token)
        if machine_name:
            from apps.inventory.models import Machine
            try:
                machine = Machine.objects.get(hostname__iexact=machine_name)
                # Registra uso do token nesta máquina
                AgentTokenUsage.objects.update_or_create(
                    agent_token=agent_token,
                    machine_name=machine.hostname,
                )
            except Machine.DoesNotExist:
                pass

        # Filtro: chamados deste solicitante
        # Se souber a máquina: mostra chamados desta máquina + chamados sem máquina
        if machine:
            filtro = Q(solicitante=solicitante) & (
                    Q(machine=machine) | Q(machine__isnull=True)
            )
        else:
            filtro = Q(solicitante=solicitante)

        tickets = (
            Ticket.objects
            .filter(filtro)
            .select_related('status', 'servico')
            .order_by('-criado_em')
            .distinct()[:50]
        )

        return Response({
            'ok': True,
            'email': email,
            'machine': machine_name or '',
            'tickets': [
                {
                    'id': t.pk,
                    'numero': t.numero,
                    'assunto': t.assunto,
                    'status': t.status.nome,
                    'status_cor': t.status.cor,
                    'servico': t.servico.nome if t.servico else '',
                    'criado_em': t.criado_em.strftime('%d/%m/%Y %H:%M'),
                }
                for t in tickets
            ],
        })


@method_decorator(csrf_exempt, name='dispatch')
class AgentTicketDetailAPIView(AgentTokenRequiredMixin, APIView):
    """
    GET /tickets/api/agent/<pk>/
    Retorna detalhes do ticket e histórico de ações públicas (mais recente primeiro).
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk):
        agent_token, err = self._authenticate(request)
        if err:
            return err

        try:
            ticket = Ticket.objects.select_related(
                'status', 'servico', 'solicitante'
            ).get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'ok': False, 'error': 'Ticket não encontrado.'}, status=404)

        acoes = (
            AcaoTicket.objects
            .filter(ticket=ticket, tipo='publica')
            .select_related('autor')
            .order_by('-criado_em')
        )

        historico = [
            {
                'id': a.pk,
                'autor': a.autor.get_full_name() or a.autor.username,
                'is_staff': a.autor.is_staff,
                'conteudo': a.conteudo,
                'criado_em': a.criado_em.strftime('%d/%m/%Y %H:%M'),
            }
            for a in acoes
        ]

        return Response({
            'ok': True,
            'ticket': {
                'id': ticket.pk,
                'numero': ticket.numero,
                'assunto': ticket.assunto,
                'descricao': ticket.descricao,
                'status': ticket.status.nome,
                'status_cor': ticket.status.cor,
                'servico': ticket.servico.nome if ticket.servico else '',
                'criado_em': ticket.criado_em.strftime('%d/%m/%Y %H:%M'),
            },
            'historico': historico,
        })


@method_decorator(csrf_exempt, name='dispatch')
class AgentTicketReplyAPIView(AgentTokenRequiredMixin, APIView):
    """
    POST /tickets/api/agent/<pk>/reply/
    Adiciona uma resposta pública ao ticket.
    Body JSON: { "email": "...", "conteudo": "..." }
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk):
        agent_token, err = self._authenticate(request)
        if err:
            return err

        from django.contrib.auth import get_user_model
        User = get_user_model()

        email = request.data.get('email', '').strip()
        conteudo = request.data.get('conteudo', '').strip()

        if not conteudo:
            return Response({'ok': False, 'error': 'Campo conteudo é obrigatório.'}, status=400)

        try:
            ticket = Ticket.objects.get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'ok': False, 'error': 'Ticket não encontrado.'}, status=404)

        try:
            autor = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'ok': False, 'error': f'Usuário com e-mail {email} não encontrado.'}, status=404)

        acao = AcaoTicket.objects.create(
            ticket=ticket,
            tipo='publica',
            autor=autor,
            conteudo=conteudo,
        )

        return Response({
            'ok': True,
            'acao': {
                'id': acao.pk,
                'autor': autor.get_full_name() or autor.username,
                'is_staff': autor.is_staff,
                'conteudo': acao.conteudo,
                'criado_em': acao.criado_em.strftime('%d/%m/%Y %H:%M'),
            },
        })


@method_decorator(csrf_exempt, name='dispatch')
class AgentTicketCreateAPIView(AgentTokenRequiredMixin, APIView):
    """
    POST /tickets/api/agent/criar/
    Authorization: Bearer <token_hash>
    X-Machine-Name: DESKTOP-ABC123

    Body: { email_solicitante, logged_user, tipo_chamado, assunto, descricao }
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        agent_token, err = self._authenticate(request)
        if err:
            return err

        email_solicitante = request.data.get('email_solicitante', '').strip()
        logged_user = request.data.get('logged_user', '').strip()
        tipo_chamado_nome = request.data.get('tipo_chamado', '').strip()
        assunto = request.data.get('assunto', '').strip()
        descricao = request.data.get('descricao', '').strip()

        if not all([email_solicitante, assunto, descricao]):
            return Response(
                {'ok': False, 'error': 'Campos obrigatórios: email_solicitante, assunto, descricao.'},
                status=400)

        solicitante = User.objects.filter(email=email_solicitante).first()
        if not solicitante:
            return Response(
                {'ok': False, 'error': f'Nenhum usuário com e-mail {email_solicitante} encontrado.'},
                status=404)

        status_inicial = Status.objects.filter(
            status_base=StatusBase.ABERTO, ativo=True).first()
        if not status_inicial:
            return Response(
                {'ok': False, 'error': 'Nenhum status "Aberto" configurado.'}, status=500)

        servico = None
        if tipo_chamado_nome:
            servico = Servico.objects.filter(
                nome__icontains=tipo_chamado_nome, ativo=True).first()

        # Resolve máquina via header X-Machine-Name (multi-máquina)
        machine = None
        machine_name = self._get_machine_name(request, agent_token)
        if machine_name:
            from apps.inventory.models import Machine
            try:
                machine = Machine.objects.get(hostname__iexact=machine_name)
                AgentTokenUsage.objects.update_or_create(
                    agent_token=agent_token,
                    machine_name=machine.hostname,
                )
            except Machine.DoesNotExist:
                pass

        ticket = Ticket.objects.create(
            solicitante=solicitante,
            machine=machine,
            status=status_inicial,
            servico=servico,
            assunto=assunto,
            descricao=descricao,
            canal_abertura='api',
            cliente=solicitante if solicitante.is_staff else solicitante,
        )

        return Response({'ok': True, 'numero': ticket.numero, 'id': ticket.pk})


# ==================== EQUIPES ====================

class EquipeListView(LoginRequiredMixin, ListView):
    model = Equipe
    template_name = 'tickets/config/equipe_list.html'
    context_object_name = 'equipes'
    ordering = ['ordem', 'nome']

    def get_queryset(self):
        return Equipe.objects.filter(cliente=self.request.user).prefetch_related('agentes')


class EquipeCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Equipe
    form_class = EquipeForm
    template_name = 'tickets/config/equipe_form.html'
    success_url = reverse_lazy('tickets:equipe_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Equipe criada com sucesso!')
        return super().form_valid(form)


class EquipeUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Equipe
    form_class = EquipeForm
    template_name = 'tickets/config/equipe_form.html'
    success_url = reverse_lazy('tickets:equipe_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['usuario'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Equipe atualizada com sucesso!')
        return super().form_valid(form)


class EquipeDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Equipe
    success_url = reverse_lazy('tickets:equipe_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Equipe excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


def distribuir_ticket_para_equipe(ticket):
    """
    Distribui um ticket automaticamente para o agente com menor carga
    dentro da equipe atribuída ao ticket.
    Chamado em TicketCreateView.form_valid e pelo sistema de gatilhos.
    """
    if not ticket.equipe:
        return None
    if ticket.responsavel:
        return ticket.responsavel  # Já tem responsável, não redistribui

    agente = ticket.equipe.agente_com_menor_carga()
    if agente:
        ticket.responsavel = agente
        ticket.save(update_fields=['responsavel'])

        HistoricoTicket.objects.create(
            ticket=ticket,
            usuario=ticket.cliente,
            campo='responsavel',
            valor_anterior='',
            valor_novo=f'{agente.get_full_name() or agente.username} (auto-distribuído via equipe {ticket.equipe.nome})'
        )
    return agente


# ==================== NOTIFICAÇÕES ====================

class NotificacaoListView(LoginRequiredMixin, ListView):
    """Lista todas as notificações do usuário logado."""
    model = NotificacaoTicket
    template_name = 'tickets/notificacoes.html'
    context_object_name = 'notificacoes'
    paginate_by = 30

    def get_queryset(self):
        qs = NotificacaoTicket.objects.filter(
            usuario=self.request.user
        ).select_related('ticket').order_by('-criado_em')

        filtro = self.request.GET.get('filtro', 'todas')
        if filtro == 'nao_lidas':
            qs = qs.filter(lida=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_nao_lidas'] = NotificacaoTicket.objects.filter(
            usuario=self.request.user, lida=False
        ).count()
        ctx['filtro'] = self.request.GET.get('filtro', 'todas')
        return ctx


@login_required
def marcar_notificacao_lida(request, pk):
    """Marca uma notificação como lida (AJAX ou redirect)."""
    notif = get_object_or_404(NotificacaoTicket, pk=pk, usuario=request.user)
    notif.marcar_lida()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    if notif.ticket:
        return redirect('tickets:ticket_detail', pk=notif.ticket.pk)
    return redirect('tickets:notificacoes')


@login_required
def marcar_todas_lidas(request):
    """Marca todas as notificações do usuário como lidas."""
    NotificacaoTicket.objects.filter(
        usuario=request.user, lida=False
    ).update(lida=True, lida_em=timezone.now())

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect('tickets:notificacoes')


@login_required
def notificacoes_count(request):
    """
    Retorna contagem de notificações não lidas (polling AJAX).
    Chamado a cada 30s pelo header da aplicação.
    """
    count = NotificacaoTicket.objects.filter(
        usuario=request.user, lida=False
    ).count()

    # Retorna as últimas 5 notificações não lidas para o dropdown
    recentes = NotificacaoTicket.objects.filter(
        usuario=request.user, lida=False
    ).select_related('ticket').order_by('-criado_em')[:5]

    return JsonResponse({
        'count': count,
        'notificacoes': [
            {
                'id': n.pk,
                'titulo': n.titulo,
                'mensagem': n.mensagem,
                'tipo': n.tipo,
                'icone': n.icone,
                'cor': n.cor,
                'ticket_id': n.ticket_id,
                'ticket_numero': n.ticket.numero if n.ticket else None,
                'criado_em': n.criado_em.strftime('%d/%m %H:%M'),
                'url': f'/tickets/tickets/{n.ticket_id}/' if n.ticket_id else '/tickets/notificacoes/',
            }
            for n in recentes
        ]
    })


# ==================== RELATÓRIOS ====================

class RelatorioTicketsView(LoginRequiredMixin, View):
    """
    Relatório de desempenho do helpdesk com métricas:
    TMR, TMA, FCR, CSAT, tickets por status/categoria/agente.
    """
    template_name = 'tickets/relatorio.html'

    def get(self, request):
        from datetime import date, timedelta

        # ── Filtros de período ──
        data_inicio_str = request.GET.get('data_inicio', '')
        data_fim_str = request.GET.get('data_fim', '')
        agente_id = request.GET.get('agente', '')
        categoria_id = request.GET.get('categoria', '')

        hoje = date.today()
        try:
            data_inicio = date.fromisoformat(data_inicio_str) if data_inicio_str else hoje.replace(day=1)
            data_fim = date.fromisoformat(data_fim_str) if data_fim_str else hoje
        except ValueError:
            data_inicio = hoje.replace(day=1)
            data_fim = hoje

        user = request.user
        cliente = user if user.is_staff else user

        qs = Ticket.objects.filter(
            cliente=cliente,
            criado_em__date__gte=data_inicio,
            criado_em__date__lte=data_fim,
        )

        if agente_id:
            qs = qs.filter(responsavel_id=agente_id)
        if categoria_id:
            qs = qs.filter(categoria_id=categoria_id)

        # ── Métricas gerais ──
        total = qs.count()
        total_fechados = qs.filter(status__status_base__in=['resolvido', 'fechado']).count()
        total_vencidos = qs.filter(
            previsao_solucao__lt=timezone.now()
        ).exclude(status__status_base__in=['resolvido', 'fechado', 'cancelado']).count()

        # TMR — Tempo Médio de Resposta (criado_em → primeira_resposta_em)
        tmr_qs = qs.filter(
            primeira_resposta_em__isnull=False
        ).annotate(
            duracao_resposta=ExpressionWrapper(
                F('primeira_resposta_em') - F('criado_em'),
                output_field=DurationField()
            )
        ).aggregate(tmr=Avg('duracao_resposta'))
        tmr = tmr_qs['tmr']
        tmr_horas = round(tmr.total_seconds() / 3600, 1) if tmr else None

        # TMA — Tempo Médio de Atendimento (criado_em → resolvido_em)
        tma_qs = qs.filter(
            resolvido_em__isnull=False
        ).annotate(
            duracao_atendimento=ExpressionWrapper(
                F('resolvido_em') - F('criado_em'),
                output_field=DurationField()
            )
        ).aggregate(tma=Avg('duracao_atendimento'))
        tma = tma_qs['tma']
        tma_horas = round(tma.total_seconds() / 3600, 1) if tma else None

        # FCR — First Contact Resolution
        # Considera FCR tickets resolvidos com apenas 1 ação pública do agente
        fcr_total = qs.filter(
            status__status_base__in=['resolvido', 'fechado']
        ).annotate(
            acoes_pub=Count('acoes', filter=Q(acoes__tipo='publica', acoes__autor__is_staff=True))
        ).filter(acoes_pub__lte=1).count()
        fcr_pct = round((fcr_total / total_fechados * 100), 1) if total_fechados else None

        # CSAT — média das avaliações de satisfação
        from apps.tickets.models import PesquisaSatisfacao
        csat_qs = PesquisaSatisfacao.objects.filter(
            ticket__cliente=cliente,
            ticket__criado_em__date__gte=data_inicio,
            ticket__criado_em__date__lte=data_fim,
            nota__isnull=False,
        ).aggregate(media=Avg('nota'), total=Count('id'))
        csat_media = round(csat_qs['media'], 1) if csat_qs['media'] else None

        # ── Por status ──
        por_status = qs.values(
            'status__nome', 'status__cor'
        ).annotate(total=Count('id')).order_by('-total')

        # ── Por categoria ──
        por_categoria = qs.values(
            'categoria__nome'
        ).annotate(total=Count('id')).order_by('-total')[:10]

        # ── Por agente ──
        por_agente = qs.filter(responsavel__isnull=False).values(
            'responsavel__first_name', 'responsavel__last_name', 'responsavel__username'
        ).annotate(total=Count('id')).order_by('-total')[:10]

        # ── Por dia (últimos 30 dias) ──
        por_dia = qs.annotate(
            dia=TruncDate('criado_em')
        ).values('dia').annotate(total=Count('id')).order_by('dia')

        # ── Contexto ──
        from apps.authentication.models import User
        agentes_qs = User.objects.filter(is_staff=True, is_active=True)
        categorias_qs = Categoria.objects.filter(cliente=cliente, ativo=True)

        return render(request, self.template_name, {
            'data_inicio': data_inicio,
            'data_fim': data_fim,
            'agente_id': agente_id,
            'categoria_id': categoria_id,
            'agentes': agentes_qs,
            'categorias': categorias_qs,
            # Métricas
            'total': total,
            'total_fechados': total_fechados,
            'total_vencidos': total_vencidos,
            'tmr_horas': tmr_horas,
            'tma_horas': tma_horas,
            'fcr_pct': fcr_pct,
            'csat_media': csat_media,
            'csat_total': csat_qs['total'],
            # Distribuições
            'por_status': list(por_status),
            'por_categoria': list(por_categoria),
            'por_agente': list(por_agente),
            'por_dia': list(por_dia),
        })


@login_required
def exportar_tickets_csv(request):
    """
    Exporta tickets filtrados como CSV.
    Aceita os mesmos parâmetros GET da RelatorioTicketsView.
    """
    from datetime import date

    user = request.user
    cliente = user if user.is_staff else user

    data_inicio_str = request.GET.get('data_inicio', '')
    data_fim_str = request.GET.get('data_fim', '')
    agente_id = request.GET.get('agente', '')
    categoria_id = request.GET.get('categoria', '')

    hoje = date.today()
    try:
        data_inicio = date.fromisoformat(data_inicio_str) if data_inicio_str else hoje.replace(day=1)
        data_fim = date.fromisoformat(data_fim_str) if data_fim_str else hoje
    except ValueError:
        data_inicio = hoje.replace(day=1)
        data_fim = hoje

    qs = Ticket.objects.filter(
        cliente=cliente,
        criado_em__date__gte=data_inicio,
        criado_em__date__lte=data_fim,
    ).select_related(
        'solicitante', 'responsavel', 'status',
        'categoria', 'urgencia', 'servico'
    ).order_by('-criado_em')

    if agente_id:
        qs = qs.filter(responsavel_id=agente_id)
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)

    # Cria o arquivo CSV
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    filename = f"tickets_{data_inicio}_{data_fim}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Número', 'Assunto', 'Status', 'Status Base',
        'Categoria', 'Urgência', 'Serviço',
        'Solicitante', 'Responsável', 'Equipe',
        'Canal', 'Tipo',
        'Criado em', '1ª Resposta em', 'Resolvido em', 'Fechado em',
        'Previsão SLA', 'Vencido?',
        'TMR (horas)', 'TMA (horas)',
        'Tags',
    ])

    for t in qs:
        tmr = None
        if t.primeira_resposta_em and t.criado_em:
            tmr = round((t.primeira_resposta_em - t.criado_em).total_seconds() / 3600, 2)
        tma = None
        if t.resolvido_em and t.criado_em:
            tma = round((t.resolvido_em - t.criado_em).total_seconds() / 3600, 2)

        writer.writerow([
            t.numero,
            t.assunto,
            t.status.nome if t.status else '',
            t.status.status_base if t.status else '',
            t.categoria.nome if t.categoria else '',
            t.urgencia.nome if t.urgencia else '',
            t.servico.nome if t.servico else '',
            t.solicitante.get_full_name() or t.solicitante.username if t.solicitante else '',
            t.responsavel.get_full_name() or t.responsavel.username if t.responsavel else '',
            t.equipe.nome if hasattr(t, 'equipe') and t.equipe else '',
            t.canal_abertura,
            t.tipo_ticket,
            t.criado_em.strftime('%d/%m/%Y %H:%M') if t.criado_em else '',
            t.primeira_resposta_em.strftime('%d/%m/%Y %H:%M') if t.primeira_resposta_em else '',
            t.resolvido_em.strftime('%d/%m/%Y %H:%M') if t.resolvido_em else '',
            t.fechado_em.strftime('%d/%m/%Y %H:%M') if t.fechado_em else '',
            t.previsao_solucao.strftime('%d/%m/%Y %H:%M') if t.previsao_solucao else '',
            'Sim' if t.esta_vencido else 'Não',
            tmr,
            tma,
            ', '.join(t.tags) if t.tags else '',
        ])

    return response