from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.http import JsonResponse
from django.views import View

from .forms import (
    AtivoForm, LocalizacaoForm, AtivoUtilizadorForm,
    AtivoAnexoForm, StatusAtivoForm
)
from .models import Ativo, Localizacao, AtivoUtilizador, AtivoAnexo, AtivoHistorico, StatusAtivo
from ..shared.mixins import ClienteQuerySetMixin, ClienteCreateMixin, ClienteObjectMixin


# ==================== LOCALIZAÇÕES ====================

class LocalizacaoListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = Localizacao
    template_name = 'ativos/localizacao_list.html'
    context_object_name = 'localizacoes'

    def get_queryset(self):
        queryset = super().get_queryset()
        nome = self.request.GET.get('nome')
        status = self.request.GET.get('status')

        if nome:
            queryset = queryset.filter(nome__icontains=nome)
        if status in ['true', 'false']:
            queryset = queryset.filter(status=(status == 'true'))

        return queryset


class LocalizacaoCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = Localizacao
    form_class = LocalizacaoForm
    template_name = 'ativos/localizacao_form.html'
    success_url = reverse_lazy('ativos:localizacao_list')


class LocalizacaoUpdateView(ClienteObjectMixin, LoginRequiredMixin, UpdateView):
    model = Localizacao
    form_class = LocalizacaoForm
    template_name = 'ativos/localizacao_form.html'
    success_url = reverse_lazy('ativos:localizacao_list')


class LocalizacaoDeleteView(ClienteObjectMixin, LoginRequiredMixin, DeleteView):
    model = Localizacao
    success_url = reverse_lazy('ativos:localizacao_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ==================== STATUS ====================

class StatusAtivoListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = StatusAtivo
    template_name = 'ativos/status_list.html'
    context_object_name = 'status_list'

    def get_queryset(self):
        queryset = super().get_queryset()
        nome = self.request.GET.get('nome')
        is_active = self.request.GET.get('is_active')

        if nome:
            queryset = queryset.filter(nome__icontains=nome)
        if is_active in ['true', 'false']:
            queryset = queryset.filter(is_active=(is_active == 'true'))

        return queryset


class StatusAtivoCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = StatusAtivo
    form_class = StatusAtivoForm
    template_name = 'ativos/status_form.html'
    success_url = reverse_lazy('ativos:status_list')


class StatusAtivoUpdateView(ClienteObjectMixin, LoginRequiredMixin, UpdateView):
    model = StatusAtivo
    form_class = StatusAtivoForm
    template_name = 'ativos/status_form.html'
    success_url = reverse_lazy('ativos:status_list')


class StatusAtivoDeleteView(ClienteObjectMixin, LoginRequiredMixin, DeleteView):
    model = StatusAtivo
    success_url = reverse_lazy('ativos:status_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ==================== ATIVOS ====================

class AtivoListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = Ativo
    template_name = 'ativos/ativo_list.html'
    context_object_name = 'ativos'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtros
        nome = self.request.GET.get('nome')
        etiqueta = self.request.GET.get('etiqueta')
        categoria = self.request.GET.get('categoria')
        status = self.request.GET.get('status')
        localizacao = self.request.GET.get('localizacao')

        if nome:
            queryset = queryset.filter(nome__icontains=nome)
        if etiqueta:
            queryset = queryset.filter(etiqueta__icontains=etiqueta)
        if categoria:
            queryset = queryset.filter(categoria_id=categoria)
        if status:
            queryset = queryset.filter(status_id=status)
        if localizacao:
            queryset = queryset.filter(localizacao_id=localizacao)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.categorias.models import Categoria
        context['categorias'] = Categoria.objects.filter(cliente=self.request.user.cliente, status=True)
        context['localizacoes'] = Localizacao.objects.filter(cliente=self.request.user.cliente, status=True)
        context['status_ativos'] = StatusAtivo.objects.filter(cliente=self.request.user.cliente, is_active=True)
        return context


class AtivoCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = Ativo
    form_class = AtivoForm
    template_name = 'ativos/ativo_form.html'

    def get_success_url(self):
        return reverse_lazy('ativos:ativo_update', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        # Atualizar histórico com usuário
        historico = AtivoHistorico.objects.filter(
            ativo=self.object,
            usuario__isnull=True
        ).first()
        if historico:
            historico.usuario = self.request.user
            historico.save()
        return response


class AtivoDetailView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = Ativo
    template_name = 'ativos/ativo_detail.html'
    context_object_name = 'ativo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['utilizadores'] = self.object.utilizadores.all()
        context['anexos'] = self.object.anexos.all()
        context['historico'] = self.object.historico.all()
        return context


class AtivoUpdateView(ClienteObjectMixin, LoginRequiredMixin, UpdateView):
    model = Ativo
    form_class = AtivoForm
    template_name = 'ativos/ativo_update.html'

    def get_success_url(self):
        return reverse_lazy('ativos:ativo_update', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['utilizadores'] = self.object.utilizadores.all()
        context['anexos'] = self.object.anexos.all()
        context['historico'] = self.object.historico.all()
        context['utilizador_form'] = AtivoUtilizadorForm()
        context['anexo_form'] = AtivoAnexoForm()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        # Atualizar históricos sem usuário
        AtivoHistorico.objects.filter(
            ativo=self.object,
            usuario__isnull=True
        ).update(usuario=self.request.user)
        return response


class AtivoDeleteView(ClienteObjectMixin, LoginRequiredMixin, DeleteView):
    model = Ativo
    success_url = reverse_lazy('ativos:ativo_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ==================== UTILIZADORES (AJAX) ====================

class AtivoUtilizadorCreateView(LoginRequiredMixin, View):
    def post(self, request, ativo_id):
        ativo = get_object_or_404(Ativo, pk=ativo_id, cliente=request.user.cliente)
        form = AtivoUtilizadorForm(request.POST)

        if form.is_valid():
            utilizador = form.save(commit=False)
            utilizador.ativo = ativo
            utilizador.save()

            # Atualizar histórico
            AtivoHistorico.objects.create(
                ativo=ativo,
                descricao=f"Utilizador {utilizador.usuario.get_full_name() or utilizador.usuario.username} atribuído",
                usuario=request.user
            )

            return JsonResponse({'status': 'success'})

        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)


class AtivoUtilizadorDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        utilizador = get_object_or_404(
            AtivoUtilizador,
            pk=pk,
            ativo__cliente=request.user.cliente
        )

        ativo = utilizador.ativo
        usuario_nome = utilizador.usuario.get_full_name() or utilizador.usuario.username

        # Criar histórico
        AtivoHistorico.objects.create(
            ativo=ativo,
            descricao=f"Utilizador {usuario_nome} removido",
            usuario=request.user
        )

        utilizador.delete()
        return JsonResponse({'status': 'success'})


# ==================== ANEXOS (AJAX) ====================

class AtivoAnexoCreateView(LoginRequiredMixin, View):
    def post(self, request, ativo_id):
        ativo = get_object_or_404(Ativo, pk=ativo_id, cliente=request.user.cliente)
        form = AtivoAnexoForm(request.POST, request.FILES)

        if form.is_valid():
            anexo = form.save(commit=False)
            anexo.ativo = ativo
            anexo.save()

            # Criar histórico
            AtivoHistorico.objects.create(
                ativo=ativo,
                descricao=f"Anexo adicionado: {anexo.titulo}",
                usuario=request.user
            )

            return JsonResponse({'status': 'success'})

        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)


class AtivoAnexoDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        anexo = get_object_or_404(
            AtivoAnexo,
            pk=pk,
            ativo__cliente=request.user.cliente
        )

        ativo = anexo.ativo
        titulo = anexo.titulo

        # Criar histórico
        AtivoHistorico.objects.create(
            ativo=ativo,
            descricao=f"Anexo removido: {titulo}",
            usuario=request.user
        )

        anexo.delete()
        return JsonResponse({'status': 'success'})