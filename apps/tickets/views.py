from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse, FileResponse
from django.db.models import Q, Count, Avg, F
from django.utils import timezone
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from datetime import datetime, timedelta
import json
import zipfile
import io

from .models import (
    Ticket, AcaoTicket, AnexoTicket, HistoricoTicket,
    Categoria, Urgencia, Status, Justificativa, Servico,
    ContratoSLA, RegraSLA, StatusBase, PesquisaSatisfacao,
    CampoAdicional, RegraExibicaoCampo,
    Gatilho, Macro, CategoriaUrgencia
)
from .forms import (
    TicketForm, TicketFiltroForm, AcaoTicketForm, AnexoTicketForm,
    AlterarStatusForm, AlterarResponsavelForm, MesclarTicketsForm,
    ReabrirTicketForm, AlterarPrevisaoSLAForm, CategoriaForm,
    UrgenciaForm, StatusForm, JustificativaForm, ServicoForm,
    ContratoSLAForm, RegraSLAForm, CampoAdicionalForm, RegraExibicaoCampoForm,
    GatilhoForm, MacroForm
)


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

class TicketListView(LoginRequiredMixin, ListView):
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
            'regra_sla_aplicada', 'ticket_pai'
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

        # Ações do ticket
        context['acoes'] = self.object.acoes.all().order_by('criado_em')

        # Anexos
        context['anexos'] = self.object.anexos.all().order_by('criado_em')

        # Histórico
        context['historico'] = self.object.historico.all().order_by('-criado_em')[:20]

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

        # Se não especificou responsável, tenta distribuir automaticamente
        if not form.instance.responsavel:
            # TODO: Implementar lógica de distribuição automática
            pass

        response = super().form_valid(form)

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

    def form_valid(self, form):
        messages.success(self.request, 'Categoria criada com sucesso!')
        return super().form_valid(form)


class CategoriaUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'tickets/config/categoria_form.html'
    success_url = reverse_lazy('tickets:categoria_list')

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
    context_object_name = 'urgencias'
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

    def form_valid(self, form):
        messages.success(self.request, 'Justificativa criada com sucesso!')
        return super().form_valid(form)


class JustificativaUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Justificativa
    form_class = JustificativaForm
    template_name = 'tickets/config/justificativa_form.html'
    success_url = reverse_lazy('tickets:justificativa_list')

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

    def form_valid(self, form):
        messages.success(self.request, 'Gatilho criado com sucesso!')
        return super().form_valid(form)


class GatilhoUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Gatilho
    form_class = GatilhoForm
    template_name = 'tickets/config/gatilho_form.html'
    success_url = reverse_lazy('tickets:gatilho_list')

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


class MacroCreateView(LoginRequiredMixin, ClienteCreateMixin, CreateView):
    model = Macro
    form_class = MacroForm
    template_name = 'tickets/config/macro_form.html'
    success_url = reverse_lazy('tickets:macro_list')

    def form_valid(self, form):
        messages.success(self.request, 'Macro criada com sucesso!')
        return super().form_valid(form)


class MacroUpdateView(LoginRequiredMixin, ClienteObjectMixin, UpdateView):
    model = Macro
    form_class = MacroForm
    template_name = 'tickets/config/macro_form.html'
    success_url = reverse_lazy('tickets:macro_list')

    def form_valid(self, form):
        messages.success(self.request, 'Macro atualizada com sucesso!')
        return super().form_valid(form)


class MacroDeleteView(LoginRequiredMixin, ClienteObjectMixin, DeleteView):
    model = Macro
    success_url = reverse_lazy('tickets:macro_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Macro excluída com sucesso!')
        return super().delete(request, *args, **kwargs)


# ==================== AJAX / API ====================

@login_required
def urgencias_por_categoria(request, categoria_id):
    """Retorna urgências permitidas para uma categoria (AJAX)"""
    try:
        categoria = Categoria.objects.get(pk=categoria_id)

        # Busca urgências permitidas
        urgencias_ids = categoria.urgencias_permitidas.values_list('urgencia_id', flat=True)

        if urgencias_ids:
            urgencias = Urgencia.objects.filter(id__in=urgencias_ids, ativo=True)
        else:
            # Se não há restrição, retorna todas
            urgencias = Urgencia.objects.filter(cliente=categoria.cliente, ativo=True)

        data = [
            {'id': u.id, 'nome': u.nome, 'nivel': u.nivel, 'cor': u.cor}
            for u in urgencias
        ]

        return JsonResponse({'success': True, 'urgencias': data})

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