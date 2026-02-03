from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.http import JsonResponse
from django.views import View
from django.utils import timezone
from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .forms import AuditoriaForm, AuditoriaItemForm, FinalizarAuditoriaForm
from .models import Auditoria, AuditoriaItem, AuditoriaHistorico
from apps.ativos.models import Ativo, AtivoHistorico
from ..shared.mixins import ClienteQuerySetMixin, ClienteCreateMixin, ClienteObjectMixin
from .serializers import (
    AuditoriaListSerializer,
    AuditoriaDetailSerializer,
    AuditoriaCreateSerializer,
    AuditoriaItemSerializer,
    AuditoriaHistoricoSerializer,
    BuscarAtivoSerializer,
    VerificarItemSerializer,
    FinalizarAuditoriaSerializer,
    EstatisticasAuditoriaSerializer,
)


# Mixins customizados para filtro por cliente
class ClienteQuerySetMixin:
    """Filtra o queryset pelo cliente do usuário"""
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(cliente=self.request.user.cliente)

class ClienteCreateMixin:
    """Adiciona o cliente automaticamente ao criar objeto"""
    def form_valid(self, form):
        form.instance.cliente = self.request.user.cliente
        return super().form_valid(form)

class ClienteObjectMixin:
    """Garante que objeto pertence ao cliente do usuário"""
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.cliente != self.request.user.cliente:
            from django.http import Http404
            raise Http404("Objeto não encontrado")
        return obj


# ==================== AUDITORIAS ====================

class AuditoriaListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = Auditoria
    template_name = 'auditoria/auditoria_list.html'
    context_object_name = 'auditorias'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtros
        titulo = self.request.GET.get('titulo')
        localizacao = self.request.GET.get('localizacao')
        status = self.request.GET.get('status')
        responsavel = self.request.GET.get('responsavel')

        if titulo:
            queryset = queryset.filter(titulo__icontains=titulo)
        if localizacao:
            queryset = queryset.filter(localizacao_id=localizacao)
        if status:
            queryset = queryset.filter(status=status)
        if responsavel:
            queryset = queryset.filter(responsavel_id=responsavel)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.ativos.models import Localizacao
        from apps.authentication.models import User

        context['localizacoes'] = Localizacao.objects.filter(
            cliente=self.request.user.cliente,
            status=True
        )
        context['usuarios'] = User.objects.filter(cliente=self.request.user.cliente)
        return context


class AuditoriaCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = Auditoria
    form_class = AuditoriaForm
    template_name = 'auditoria/auditoria_form.html'

    def get_success_url(self):
        return reverse_lazy('auditoria:auditoria_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        # Salva a auditoria
        response = super().form_valid(form)

        # Busca todos os ativos da localização selecionada
        ativos = Ativo.objects.filter(
            cliente=self.request.user.cliente,
            localizacao=self.object.localizacao
        )

        # Cria os itens da auditoria
        for ativo in ativos:
            AuditoriaItem.objects.create(
                auditoria=self.object,
                ativo=ativo
            )

        # Atualiza o total de ativos
        self.object.total_ativos = ativos.count()
        self.object.save()

        # Registra no histórico
        AuditoriaHistorico.objects.create(
            auditoria=self.object,
            acao='Criação',
            descricao=f'Auditoria criada com {ativos.count()} ativos',
            usuario=self.request.user
        )

        return response

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Filtra localizações e usuários pelo cliente
        form.fields['localizacao'].queryset = form.fields['localizacao'].queryset.filter(
            cliente=self.request.user.cliente,
            status=True
        )
        form.fields['responsavel'].queryset = form.fields['responsavel'].queryset.filter(
            cliente=self.request.user.cliente
        )
        return form


class AuditoriaDetailView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = Auditoria
    template_name = 'auditoria/auditoria_detail.html'
    context_object_name = 'auditoria'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Itens da auditoria com filtros
        itens = self.object.itens.select_related('ativo').all()

        filtro = self.request.GET.get('filtro', 'todos')
        busca = self.request.GET.get('busca', '')

        if filtro == 'verificados':
            itens = itens.filter(verificado=True)
        elif filtro == 'pendentes':
            itens = itens.filter(verificado=False)

        if busca:
            itens = itens.filter(ativo__etiqueta__icontains=busca) | \
                    itens.filter(ativo__nome__icontains=busca)

        context['itens'] = itens
        context['historico'] = self.object.historico.all()[:10]
        context['progresso'] = self.object.calcular_progresso()
        context['filtro_atual'] = filtro
        context['busca_atual'] = busca

        return context


class AuditoriaExecutarView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = Auditoria
    template_name = 'auditoria/auditoria_executar.html'
    context_object_name = 'auditoria'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Itens pendentes
        itens_pendentes = self.object.itens.filter(verificado=False).select_related('ativo')

        # Busca por código de barras
        codigo_busca = self.request.GET.get('codigo', '')
        item_encontrado = None

        if codigo_busca:
            try:
                item_encontrado = self.object.itens.select_related('ativo').get(
                    ativo__etiqueta=codigo_busca
                )
            except AuditoriaItem.DoesNotExist:
                context['erro_busca'] = f'Ativo com etiqueta "{codigo_busca}" não encontrado nesta auditoria'

        context['itens_pendentes'] = itens_pendentes
        context['item_encontrado'] = item_encontrado
        context['progresso'] = self.object.calcular_progresso()
        context['item_form'] = AuditoriaItemForm()

        return context


class AuditoriaVerificarItemView(LoginRequiredMixin, View):
    """View AJAX para verificar um item da auditoria"""

    def post(self, request, pk, item_id):
        try:
            auditoria = get_object_or_404(
                Auditoria,
                pk=pk,
                cliente=request.user.cliente,
                status='0'
            )

            item = get_object_or_404(AuditoriaItem, pk=item_id, auditoria=auditoria)

            # Atualiza o item
            item.verificado = True
            item.data_verificacao = timezone.now()
            item.verificado_por = request.user

            # Dados adicionais do formulário
            item.estado_fisico = request.POST.get('estado_fisico', '')
            item.localizacao_real = request.POST.get('localizacao_real', '')
            item.observacao = request.POST.get('observacao', '')

            item.save()

            # Atualiza estatísticas da auditoria
            auditoria.atualizar_estatisticas()

            # Registra no histórico
            AuditoriaHistorico.objects.create(
                auditoria=auditoria,
                acao='Verificação',
                descricao=f'Ativo {item.ativo.etiqueta} verificado',
                usuario=request.user
            )

            return JsonResponse({
                'status': 'success',
                'progresso': auditoria.calcular_progresso(),
                'ativos_verificados': auditoria.ativos_verificados,
                'total_ativos': auditoria.total_ativos
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)


class AuditoriaDesverificarItemView(LoginRequiredMixin, View):
    """View AJAX para desmarcar verificação de um item"""

    def post(self, request, pk, item_id):
        try:
            auditoria = get_object_or_404(
                Auditoria,
                pk=pk,
                cliente=request.user.cliente,
                status='0'
            )

            item = get_object_or_404(AuditoriaItem, pk=item_id, auditoria=auditoria)

            # Remove a verificação
            item.verificado = False
            item.data_verificacao = None
            item.verificado_por = None
            item.save()

            # Atualiza estatísticas
            auditoria.atualizar_estatisticas()

            # Registra no histórico
            AuditoriaHistorico.objects.create(
                auditoria=auditoria,
                acao='Desverificação',
                descricao=f'Verificação do ativo {item.ativo.etiqueta} removida',
                usuario=request.user
            )

            return JsonResponse({
                'status': 'success',
                'progresso': auditoria.calcular_progresso()
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)


class AuditoriaFinalizarView(LoginRequiredMixin, View):
    """View para finalizar uma auditoria"""

    def get(self, request, pk):
        auditoria = get_object_or_404(
            Auditoria,
            pk=pk,
            cliente=request.user.cliente
        )
        form = FinalizarAuditoriaForm()

        return render(request, 'auditoria/auditoria_finalizar.html', {
            'auditoria': auditoria,
            'form': form,
            'progresso': auditoria.calcular_progresso()
        })

    def post(self, request, pk):
        auditoria = get_object_or_404(
            Auditoria,
            pk=pk,
            cliente=request.user.cliente
        )
        form = FinalizarAuditoriaForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                # Atualiza status da auditoria
                auditoria.status = '1'
                auditoria.data_finalizacao = timezone.now()

                observacoes_finais = form.cleaned_data.get('observacoes_finais')
                if observacoes_finais:
                    if auditoria.observacoes:
                        auditoria.observacoes += f"\n\nObservações Finais: {observacoes_finais}"
                    else:
                        auditoria.observacoes = f"Observações Finais: {observacoes_finais}"

                auditoria.save()

                # Atualiza campo de auditoria nos ativos verificados
                itens_verificados = auditoria.itens.filter(verificado=True)

                for item in itens_verificados:
                    ativo = item.ativo

                    # Atualiza campo auditoria no ativo
                    texto_auditoria = f"Auditoria realizada em {auditoria.data_finalizacao.strftime('%d/%m/%Y %H:%M')} "
                    texto_auditoria += f"por {request.user.get_full_name() or request.user.username}"

                    if item.estado_fisico:
                        texto_auditoria += f" - Estado: {item.get_estado_fisico_display()}"

                    if ativo.auditoria:
                        ativo.auditoria += f"\n{texto_auditoria}"
                    else:
                        ativo.auditoria = texto_auditoria

                    ativo.save()

                    # Cria histórico no ativo
                    AtivoHistorico.objects.create(
                        ativo=ativo,
                        campo_alterado='Auditoria',
                        valor_novo=texto_auditoria,
                        descricao=f'Ativo verificado na auditoria "{auditoria.titulo}"',
                        usuario=request.user
                    )

                # Registra finalização no histórico
                AuditoriaHistorico.objects.create(
                    auditoria=auditoria,
                    acao='Finalização',
                    descricao=f'Auditoria finalizada com {auditoria.ativos_verificados}/{auditoria.total_ativos} ativos verificados',
                    usuario=request.user
                )

            return redirect('auditoria:auditoria_detail', pk=auditoria.pk)

        return render(request, 'auditoria/auditoria_finalizar.html', {
            'auditoria': auditoria,
            'form': form,
            'progresso': auditoria.calcular_progresso()
        })


class AuditoriaCancelarView(LoginRequiredMixin, View):
    """View para cancelar uma auditoria"""

    def post(self, request, pk):
        auditoria = get_object_or_404(
            Auditoria,
            pk=pk,
            cliente=request.user.cliente
        )

        if auditoria.status == '0':
            auditoria.status = '2'
            auditoria.save()

            # Registra no histórico
            AuditoriaHistorico.objects.create(
                auditoria=auditoria,
                acao='Cancelamento',
                descricao='Auditoria cancelada',
                usuario=request.user
            )

            return JsonResponse({'status': 'success'})

        return JsonResponse({'status': 'error', 'message': 'Auditoria não pode ser cancelada'}, status=400)


class AuditoriaDeleteView(ClienteObjectMixin, LoginRequiredMixin, DeleteView):
    model = Auditoria
    success_url = reverse_lazy('auditoria:auditoria_list')

    def delete(self, request, *args, **kwargs):
        try:
            self.object = self.get_object()
            success_url = self.get_success_url()
            self.object.delete()
            return JsonResponse({'status': 'success', 'redirect': success_url})
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)


# ==================== RELATÓRIOS ====================

class AuditoriaRelatorioView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = Auditoria
    template_name = 'auditoria/auditoria_relatorio.html'
    context_object_name = 'auditoria'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Estatísticas detalhadas
        itens = self.object.itens.all()

        context['itens_verificados'] = itens.filter(verificado=True)
        context['itens_pendentes'] = itens.filter(verificado=False)

        # Ativos por estado físico
        context['por_estado'] = {
            'otimo': itens.filter(estado_fisico='0').count(),
            'bom': itens.filter(estado_fisico='1').count(),
            'regular': itens.filter(estado_fisico='2').count(),
            'ruim': itens.filter(estado_fisico='3').count(),
        }

        return context


class AuditoriaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar auditorias

    list: Lista todas as auditorias do cliente
    create: Cria nova auditoria
    retrieve: Retorna detalhes de uma auditoria
    update: Atualiza auditoria (apenas se em andamento)
    partial_update: Atualização parcial
    destroy: Remove auditoria

    Actions personalizadas:
    - buscar_ativo: Busca ativo por código/etiqueta
    - verificar_item: Verifica um item da auditoria
    - desverificar_item: Remove verificação de um item
    - finalizar: Finaliza a auditoria
    - cancelar: Cancela a auditoria
    - estatisticas: Retorna estatísticas detalhadas
    - relatorio: Retorna dados para relatório
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Retorna apenas auditorias do cliente do usuário"""
        return Auditoria.objects.filter(
            cliente=self.request.user.cliente
        ).select_related('localizacao', 'responsavel')

    def get_serializer_class(self):
        """Retorna serializer apropriado para cada action"""
        if self.action == 'list':
            return AuditoriaListSerializer
        elif self.action == 'create':
            return AuditoriaCreateSerializer
        return AuditoriaDetailSerializer

    def perform_create(self, serializer):
        """Adiciona cliente automaticamente ao criar"""
        serializer.save(cliente=self.request.user.cliente)

    @action(detail=True, methods=['get'], url_path='buscar-ativo')
    def buscar_ativo(self, request, pk=None):
        """
        Busca ativo por código/etiqueta dentro da auditoria

        GET /api/auditorias/{id}/buscar-ativo/?codigo=AT-001
        """
        auditoria = self.get_object()
        serializer = BuscarAtivoSerializer(data=request.query_params)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        codigo = serializer.validated_data['codigo']

        try:
            item = auditoria.itens.select_related('ativo').get(
                ativo__etiqueta__iexact=codigo
            )
            return Response({
                'encontrado': True,
                'item': AuditoriaItemSerializer(item).data
            })
        except AuditoriaItem.DoesNotExist:
            return Response({
                'encontrado': False,
                'mensagem': f'Ativo com etiqueta "{codigo}" não encontrado nesta auditoria'
            }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], url_path='itens/(?P<item_id>[^/.]+)/verificar')
    def verificar_item(self, request, pk=None, item_id=None):
        """
        Verifica um item da auditoria

        POST /api/auditorias/{id}/itens/{item_id}/verificar/
        Body: {
            "estado_fisico": "bom",
            "localizacao_real": "Sala 101",
            "observacao": "Ativo em perfeito estado"
        }
        """
        auditoria = self.get_object()

        if auditoria.status != 'em_andamento':
            return Response({
                'erro': 'Auditoria não está em andamento'
            }, status=status.HTTP_400_BAD_REQUEST)

        item = get_object_or_404(AuditoriaItem, pk=item_id, auditoria=auditoria)

        serializer = VerificarItemSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Atualiza o item
        item.verificado = True
        item.data_verificacao = timezone.now()
        item.verificado_por = request.user
        item.estado_fisico = serializer.validated_data.get('estado_fisico', '')
        item.localizacao_real = serializer.validated_data.get('localizacao_real', '')
        item.observacao = serializer.validated_data.get('observacao', '')
        item.save()

        # Atualiza estatísticas da auditoria
        auditoria.atualizar_estatisticas()

        # Registra no histórico
        AuditoriaHistorico.objects.create(
            auditoria=auditoria,
            acao='Verificação',
            descricao=f'Ativo {item.ativo.etiqueta} verificado via API',
            usuario=request.user
        )

        return Response({
            'mensagem': 'Item verificado com sucesso',
            'item': AuditoriaItemSerializer(item).data,
            'progresso': auditoria.calcular_progresso(),
            'ativos_verificados': auditoria.ativos_verificados,
            'total_ativos': auditoria.total_ativos
        })

    @action(detail=True, methods=['post'], url_path='itens/(?P<item_id>[^/.]+)/desverificar')
    def desverificar_item(self, request, pk=None, item_id=None):
        """
        Remove verificação de um item

        POST /api/auditorias/{id}/itens/{item_id}/desverificar/
        """
        auditoria = self.get_object()

        if auditoria.status != 'em_andamento':
            return Response({
                'erro': 'Auditoria não está em andamento'
            }, status=status.HTTP_400_BAD_REQUEST)

        item = get_object_or_404(AuditoriaItem, pk=item_id, auditoria=auditoria)

        # Remove a verificação
        item.verificado = False
        item.data_verificacao = None
        item.verificado_por = None
        item.save()

        # Atualiza estatísticas
        auditoria.atualizar_estatisticas()

        # Registra no histórico
        AuditoriaHistorico.objects.create(
            auditoria=auditoria,
            acao='Desverificação',
            descricao=f'Verificação do ativo {item.ativo.etiqueta} removida via API',
            usuario=request.user
        )

        return Response({
            'mensagem': 'Verificação removida com sucesso',
            'progresso': auditoria.calcular_progresso()
        })

    @action(detail=True, methods=['post'])
    def finalizar(self, request, pk=None):
        """
        Finaliza a auditoria

        POST /api/auditorias/{id}/finalizar/
        Body: {
            "observacoes_finais": "Auditoria concluída com sucesso"
        }
        """
        auditoria = self.get_object()

        if auditoria.status != 'em_andamento':
            return Response({
                'erro': 'Auditoria não está em andamento'
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = FinalizarAuditoriaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Atualiza status da auditoria
            auditoria.status = 'finalizada'
            auditoria.data_finalizacao = timezone.now()

            observacoes_finais = serializer.validated_data.get('observacoes_finais')
            if observacoes_finais:
                if auditoria.observacoes:
                    auditoria.observacoes += f"\n\nObservações Finais: {observacoes_finais}"
                else:
                    auditoria.observacoes = f"Observações Finais: {observacoes_finais}"

            auditoria.save()

            # Atualiza campo de auditoria nos ativos verificados
            itens_verificados = auditoria.itens.filter(verificado=True).select_related('ativo')

            for item in itens_verificados:
                ativo = item.ativo

                # Atualiza campo auditoria no ativo
                texto_auditoria = f"Auditoria realizada em {auditoria.data_finalizacao.strftime('%d/%m/%Y %H:%M')} "
                texto_auditoria += f"por {request.user.get_full_name() or request.user.username}"

                if item.estado_fisico:
                    texto_auditoria += f" - Estado: {item.get_estado_fisico_display()}"

                if ativo.auditoria:
                    ativo.auditoria += f"\n{texto_auditoria}"
                else:
                    ativo.auditoria = texto_auditoria

                ativo.save()

                # Cria histórico no ativo
                AtivoHistorico.objects.create(
                    ativo=ativo,
                    campo_alterado='Auditoria',
                    valor_novo=texto_auditoria,
                    descricao=f'Ativo verificado na auditoria "{auditoria.titulo}"',
                    usuario=request.user
                )

            # Registra finalização no histórico
            AuditoriaHistorico.objects.create(
                auditoria=auditoria,
                acao='Finalização',
                descricao=f'Auditoria finalizada via API com {auditoria.ativos_verificados}/{auditoria.total_ativos} ativos verificados',
                usuario=request.user
            )

        return Response({
            'mensagem': 'Auditoria finalizada com sucesso',
            'auditoria': AuditoriaDetailSerializer(auditoria).data
        })

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        """
        Cancela a auditoria

        POST /api/auditorias/{id}/cancelar/
        """
        auditoria = self.get_object()

        if auditoria.status != 'em_andamento':
            return Response({
                'erro': 'Apenas auditorias em andamento podem ser canceladas'
            }, status=status.HTTP_400_BAD_REQUEST)

        auditoria.status = 'cancelada'
        auditoria.save()

        # Registra no histórico
        AuditoriaHistorico.objects.create(
            auditoria=auditoria,
            acao='Cancelamento',
            descricao='Auditoria cancelada via API',
            usuario=request.user
        )

        return Response({
            'mensagem': 'Auditoria cancelada com sucesso',
            'auditoria': AuditoriaDetailSerializer(auditoria).data
        })

    @action(detail=True, methods=['get'])
    def estatisticas(self, request, pk=None):
        """
        Retorna estatísticas detalhadas da auditoria

        GET /api/auditorias/{id}/estatisticas/
        """
        auditoria = self.get_object()
        itens = auditoria.itens.all()

        # Calcula tempo decorrido
        tempo_decorrido = ""
        if auditoria.data_finalizacao:
            delta = auditoria.data_finalizacao - auditoria.data_inicio
        else:
            delta = timezone.now() - auditoria.data_inicio

        dias = delta.days
        horas = delta.seconds // 3600
        minutos = (delta.seconds % 3600) // 60

        if dias > 0:
            tempo_decorrido = f"{dias} dias, {horas}h {minutos}min"
        elif horas > 0:
            tempo_decorrido = f"{horas}h {minutos}min"
        else:
            tempo_decorrido = f"{minutos} minutos"

        data = {
            'total_ativos': auditoria.total_ativos,
            'ativos_verificados': auditoria.ativos_verificados,
            'ativos_pendentes': auditoria.total_ativos - auditoria.ativos_verificados,
            'progresso': auditoria.calcular_progresso(),
            'por_estado': {
                'otimo': itens.filter(estado_fisico='otimo').count(),
                'bom': itens.filter(estado_fisico='bom').count(),
                'regular': itens.filter(estado_fisico='regular').count(),
                'ruim': itens.filter(estado_fisico='ruim').count(),
                'nao_informado': itens.filter(verificado=True, estado_fisico='').count(),
            },
            'tempo_decorrido': tempo_decorrido
        }

        serializer = EstatisticasAuditoriaSerializer(data)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def relatorio(self, request, pk=None):
        """
        Retorna dados completos para relatório

        GET /api/auditorias/{id}/relatorio/
        """
        auditoria = self.get_object()

        itens_verificados = auditoria.itens.filter(verificado=True).select_related('ativo', 'verificado_por')
        itens_pendentes = auditoria.itens.filter(verificado=False).select_related('ativo')

        return Response({
            'auditoria': AuditoriaDetailSerializer(auditoria).data,
            'itens_verificados': AuditoriaItemSerializer(itens_verificados, many=True).data,
            'itens_pendentes': AuditoriaItemSerializer(itens_pendentes, many=True).data,
            'estatisticas': self.estatisticas(request, pk).data
        })


class AuditoriaItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet apenas para leitura de itens da auditoria

    list: Lista todos os itens (com filtros)
    retrieve: Retorna detalhes de um item
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AuditoriaItemSerializer

    def get_queryset(self):
        """Retorna apenas itens de auditorias do cliente"""
        queryset = AuditoriaItem.objects.filter(
            auditoria__cliente=self.request.user.cliente
        ).select_related('ativo', 'auditoria', 'verificado_por')

        # Filtros
        auditoria_id = self.request.query_params.get('auditoria')
        verificado = self.request.query_params.get('verificado')
        estado_fisico = self.request.query_params.get('estado_fisico')

        if auditoria_id:
            queryset = queryset.filter(auditoria_id=auditoria_id)

        if verificado is not None:
            queryset = queryset.filter(verificado=(verificado.lower() == 'true'))

        if estado_fisico:
            queryset = queryset.filter(estado_fisico=estado_fisico)

        return queryset


class AuditoriaHistoricoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet apenas para leitura do histórico

    list: Lista histórico (com filtros)
    retrieve: Retorna detalhes de um registro
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AuditoriaHistoricoSerializer

    def get_queryset(self):
        """Retorna apenas histórico de auditorias do cliente"""
        queryset = AuditoriaHistorico.objects.filter(
            auditoria__cliente=self.request.user.cliente
        ).select_related('auditoria', 'usuario')

        # Filtros
        auditoria_id = self.request.query_params.get('auditoria')
        acao = self.request.query_params.get('acao')

        if auditoria_id:
            queryset = queryset.filter(auditoria_id=auditoria_id)

        if acao:
            queryset = queryset.filter(acao__icontains=acao)

        return queryset.order_by('-created_at')