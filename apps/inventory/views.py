import os
import re
import json
import requests
from datetime import timedelta
import datetime
import logging
import hashlib

from django.conf import settings
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db import models as dj_models
from django.views.generic import ListView, DetailView, UpdateView, CreateView, DeleteView
from django.urls import reverse_lazy
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from django.db.models import Q
from .forms import MachineForm, NotificationForm, BlockedSiteForm, MachineGroupForm, AgentTokenGenerateForm
from .models import Machine, BlockedSite, Notification, MachineGroup, AgentToken, AgentVersion, AgentTokenUsage

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER DE AUTENTICAÇÃO POR TOKEN DE AGENTE
# ============================================================================
AGENT_IPC_PORT = 7070

def _get_agent_token(request):
    """
    Extrai e valida o token de agente a partir do header Authorization.
    Header esperado: Authorization: Bearer <token_hash>
    Retorna o objeto AgentToken se válido, ou None.
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None

    token_hash = auth_header[7:].strip()
    if not token_hash:
        return None

    try:
        agent_token = AgentToken.objects.get(token_hash=token_hash, is_active=True)
        if agent_token.is_expired():
            return None
        return agent_token
    except AgentToken.DoesNotExist:
        return None


class AgentTokenRequiredMixin:
    """
    Mixin para APIView: bloqueia requisições sem token de agente válido.

    Como um token pode ser usado por múltiplas máquinas, o hostname vem
    no header X-Machine-Name (enviado pelo agent_service em todo checkin).

    Se o header não estiver presente, tenta buscar via AgentTokenUsage
    (última máquina conhecida para este token — fallback para tokens legados).
    """

    def _authenticate(self, request):
        """Retorna (agent_token, None) ou (None, response_de_erro)."""
        agent_token = _get_agent_token(request)
        if agent_token is None:
            error_payload = {
                'error': 'Token de agente inválido, expirado ou ausente.',
                'detail': 'Inclua o header: Authorization: Bearer <token_hash>'
            }
            if isinstance(self, APIView):
                return None, Response(error_payload, status=status.HTTP_401_UNAUTHORIZED)
            return None, JsonResponse(error_payload, status=401)
        return agent_token, None

    def _get_machine_name(self, request, agent_token) -> str:
        """
        Resolve o hostname da máquina que está fazendo a requisição.

        Ordem de prioridade:
        1. Header X-Machine-Name   (enviado pelo agent_service)
        2. Param ?machine_name=    (fallback via query string)
        3. AgentTokenUsage mais recente para este token (último registro)
        """
        # 1. Header preferencial
        name = request.META.get('HTTP_X_MACHINE_NAME', '').strip()
        if name:
            return name

        # 2. Query string
        name = request.GET.get('machine_name', '').strip()
        if name:
            return name

        # 3. Último uso registrado
        usage = (AgentTokenUsage.objects
                 .filter(agent_token=agent_token)
                 .order_by('-last_used_at')
                 .first())
        return usage.machine_name if usage else ''

    def _get_machine(self, request, agent_token):
        """
        Resolve o objeto Machine a partir do hostname.
        Retorna (machine, None) ou (None, response_de_erro).
        """
        machine_name = self._get_machine_name(request, agent_token)
        if not machine_name:
            error = {'ok': False, 'error': 'Hostname da máquina não identificado. '
                                           'Verifique o header X-Machine-Name.'}
            if isinstance(self, APIView):
                return None, Response(error, status=400)
            return None, JsonResponse(error, status=400)

        try:
            machine = Machine.objects.get(hostname__iexact=machine_name)
            # Atualiza/registra o uso deste token nesta máquina
            AgentTokenUsage.objects.update_or_create(
                agent_token=agent_token,
                machine_name=machine.hostname,
            )
            return machine, None
        except Machine.DoesNotExist:
            error = {'ok': False, 'error': f'Máquina "{machine_name}" não registrada.'}
            if isinstance(self, APIView):
                return None, Response(error, status=404)
            return None, JsonResponse(error, status=404)


def sanitize_hw(value, max_length=None):
    if value is None:
        return None
    if isinstance(value, dict):
        raw = json.dumps(value, ensure_ascii=False)
        raw = raw.replace('\x00', '')  # byte nulo real
        value = json.loads(raw)
        return value
    if isinstance(value, list):
        raw = json.dumps(value, ensure_ascii=False)
        raw = raw.replace('\x00', '')
        return json.loads(raw)
    if isinstance(value, str):
        value = value.replace('\x00', '')
        if max_length:
            value = value[:max_length]
    return value

def deep_clean(obj):
    """Remove null bytes de qualquer estrutura de dados recursivamente."""
    if isinstance(obj, str):
        return obj.replace('\x00', '').replace('\u0000', '')
    if isinstance(obj, dict):
        return {deep_clean(k): deep_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_clean(i) for i in obj]
    return obj

def parse_wmi_date(wmi_date_str):
    """
    Converte formato de data WMI/JSON do PowerShell/Python
    Formato recebido: "/Date(1234567890000)/" (timestamp em milissegundos)
    """
    if not wmi_date_str:
        return None

    try:
        # Remove /Date( e )/
        if isinstance(wmi_date_str, str) and wmi_date_str.startswith('/Date('):
            ms = int(wmi_date_str.replace('/Date(', '').replace(')/', ''))
            # Converte de milissegundos para datetime
            return datetime.datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=datetime.timezone.utc)

        # Se já for datetime, retorna
        if isinstance(wmi_date_str, datetime.datetime):
            return wmi_date_str

        return None
    except (ValueError, AttributeError) as e:
        logger.error(f"Erro ao parsear data WMI: {wmi_date_str} - {e}")
        return None


def mark_as_used(self, machine_name):
    """Marca token como usado"""
    self.used_at = timezone.now()
    self.machine_name = machine_name
    self.save(update_fields=['used_at', 'machine_name'])


@method_decorator(csrf_exempt, name='dispatch')
class MachineCheckinView(View):
    def post(self, request):
        try:
            raw = request.body.decode('utf-8')
            data = json.loads(raw)
            data = deep_clean(data)
            hostname = data['hostname']
            ip = data.get('ip', '')
            hw = data.get('hardware', {})

            token_hash = data.get("token")
            try:
                agent_token = AgentToken.objects.get(token_hash=token_hash, is_active=True)
            except AgentToken.DoesNotExist:
                return JsonResponse({'error': 'Token inválido'}, status=401)

            if agent_token.is_expired():
                return JsonResponse({'error': 'Token expirado'}, status=401)

            # Registra/atualiza uso do token nesta máquina (multi-máquina)
            AgentTokenUsage.objects.update_or_create(
                agent_token=agent_token,
                machine_name=hostname,
            )

            install_date = parse_wmi_date(hw.get('install_date'))
            last_boot = parse_wmi_date(hw.get('last_boot'))

            machine, _ = Machine.objects.update_or_create(
                hostname=hostname,
                defaults={
                    'ip_address': ip,
                    'is_online': True,
                    'last_seen': timezone.now(),
                    'loggedUser': hw.get('logged_user'),
                    'tpm': sanitize_hw(hw.get('tpm')),
                    'manufacturer': sanitize_hw(hw.get('manufacturer'), max_length=100),
                    'model': sanitize_hw(hw.get('model'), max_length=100),
                    'serial_number': sanitize_hw(hw.get('serial_number'), max_length=100),
                    'bios_version': sanitize_hw(hw.get('bios_version'), max_length=100),
                    'mac_address': sanitize_hw(hw.get('mac_address'), max_length=100),
                    'total_memory_slots': hw.get('total_memory_slots'),
                    'populated_memory_slots': hw.get('populated_memory_slots'),
                    'memory_modules': sanitize_hw(hw.get('memory_modules')),
                    'os_caption': sanitize_hw(hw.get('os_caption'), max_length=100),
                    'os_architecture': sanitize_hw(hw.get('os_architecture'), max_length=50),
                    'os_build': hw.get('os_build'),
                    'install_date': sanitize_hw(install_date, max_length=30),
                    'last_boot': sanitize_hw(last_boot, max_length=30),
                    'uptime_days': hw.get('uptime_days'),
                    'cpu': sanitize_hw(hw.get('cpu'), max_length=100),
                    'ram_gb': hw.get('ram_gb'),
                    'disk_space_gb': hw.get('disk_space_gb'),
                    'disk_free_gb': hw.get('disk_free_gb'),
                    'network_info': sanitize_hw(hw.get('network_adapters')),
                    'gpu_name': sanitize_hw(hw.get('gpu_name'), max_length=100),
                    'gpu_driver': sanitize_hw(hw.get('gpu_driver'), max_length=100),
                    'antivirus_name': sanitize_hw(hw.get('antivirus_name'), max_length=100),
                    'av_state': sanitize_hw(str(hw.get('av_state')), max_length=50),
                },
            )
            return JsonResponse({'status': 'ok', 'machine_id': machine.id})
        except Exception as e:
            logger.error(f"Checkin error: {e}")
            return JsonResponse({'error': str(e)}, status=500)

    def get(self, request):
        host = request.GET.get('host')
        if not host:
            return JsonResponse({'error': 'host parameter required'}, status=400)

        sites = (
            BlockedSite.objects.filter(
                dj_models.Q(machine__hostname=host)
                | dj_models.Q(group__machine__hostname=host)
            )
            .values_list('url', flat=True)
            .distinct()
        )
        return JsonResponse(list(sites), safe=False)


@method_decorator(csrf_exempt, name='dispatch')
class RunCommandView(LoginRequiredMixin, View):

    def handle_no_permission(self):
        # Retorna JSON em vez de redirect para login
        return JsonResponse({'error': 'Autenticação necessária'}, status=401)

    def post(self, request, machine_id):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Acesso negado'}, status=403)

        try:
            machine = Machine.objects.get(id=machine_id)
        except Machine.DoesNotExist:
            return JsonResponse({'error': 'Máquina não encontrada'}, status=404)

        if not machine.ip_address:
            return JsonResponse({'error': 'Máquina sem IP cadastrado'}, status=400)

        cmd      = request.POST.get('command', '').strip()
        cmd_type = request.POST.get('type', 'powershell').strip()

        if not cmd:
            return JsonResponse({'error': 'Comando obrigatório'}, status=400)

        # Busca token ativo para autenticar na chamada ao agente
        token_obj = None
        try:
            usage = (AgentTokenUsage.objects
                     .filter(machine_name__iexact=machine.hostname)
                     .select_related('agent_token')
                     .order_by('-last_used_at')
                     .first())
            if usage and usage.agent_token.is_active and not usage.agent_token.is_expired():
                token_obj = usage.agent_token
        except Exception:
            pass

        # Fallback: qualquer token ativo
        if token_obj is None:
            token_obj = AgentToken.objects.filter(is_active=True).first()

        if not token_obj:
            return JsonResponse(
                {'error': 'Nenhum token ativo disponível para autenticar no agente'},
                status=500
            )

        headers = {'Authorization': f'Bearer {token_obj.token_hash}'}

        try:
            import requests as req
            resp = req.post(
                f"http://{machine.ip_address}:7071/command",
                json={
                    'type':    cmd_type,
                    'script':  cmd,
                    'timeout': 60,
                },
                headers=headers,
                timeout=65,
            )
            data = resp.json()
            return JsonResponse({
                'stdout':    data.get('stdout', ''),
                'stderr':    data.get('stderr', ''),
                'exit_code': data.get('exit_code', -1),
                'error':     data.get('error', ''),
            })
        except req.exceptions.ConnectionError:
            return JsonResponse(
                {'error': f'Agente offline ou inacessível ({machine.ip_address}:7071)'},
                status=503
            )
        except req.exceptions.Timeout:
            return JsonResponse(
                {'error': 'Timeout — agente não respondeu em 65s'},
                status=504
            )
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class MachineNotificationView(AgentTokenRequiredMixin, View):
    """
    API REST para o agente Python buscar e gerenciar notificações.
    PROTEGIDA — GET e POST exigem Authorization: Bearer <token_hash>

    GET  /api/notifications/?machine_name=HOSTNAME&status=pending
    POST /api/notifications/   body: {"notification_id": 123}
    """

    def get(self, request):
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        try:
            machine_name = request.GET.get('machine_name')
            status_filter = request.GET.get('status', 'pending')
            limit = int(request.GET.get('limit', 20))

            if not machine_name:
                return JsonResponse({
                    'success': False,
                    'error': 'Parâmetro machine_name é obrigatório',
                    'notifications': []
                }, status=400)

            try:
                machine = Machine.objects.get(Q(hostname__iexact=machine_name))
            except Machine.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'Máquina {machine_name} não encontrada',
                    'machine_name': machine_name,
                    'notifications': []
                }, status=200)

            notifications_query = Notification.objects.filter(machine=machine)

            if status_filter == 'pending':
                notifications_query = notifications_query.filter(is_read=False)
            elif status_filter == 'read':
                notifications_query = notifications_query.filter(is_read=True)

            notifications = notifications_query.order_by('is_read', '-created_at')[:limit]

            notifications_data = [{
                'id': notif.id,
                'title': notif.title,
                'message': notif.message,
                'type': getattr(notif, 'type', 'info'),
                'priority': getattr(notif, 'priority', 'normal'),
                'status': getattr(notif, 'status', 'pending'),
                'is_read': notif.is_read,
                'created_at': notif.created_at.isoformat(),
            } for notif in notifications]

            return JsonResponse({
                'success': True,
                'machine_name': machine.hostname,
                'machine_id': machine.id,
                'total': len(notifications_data),
                'notifications': notifications_data
            })

        except ValueError as e:
            return JsonResponse({'success': False, 'error': f'Parâmetro inválido: {str(e)}', 'notifications': []}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Erro interno: {str(e)}', 'notifications': []}, status=500)

    def post(self, request):
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        try:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'JSON inválido no body'}, status=400)

            notification_id = data.get('notification_id')
            if not notification_id:
                return JsonResponse({'success': False, 'error': 'Campo notification_id é obrigatório'}, status=400)

            try:
                notification = Notification.objects.get(id=notification_id)
            except Notification.DoesNotExist:
                return JsonResponse({'success': False, 'error': f'Notificação {notification_id} não encontrada'}, status=404)

            notification.is_read = True
            if hasattr(notification, 'status'):
                notification.status = 'read'
            if hasattr(notification, 'read_at'):
                notification.read_at = timezone.now()
            notification.save()

            return JsonResponse({
                'success': True,
                'notification_id': notification.id,
                'is_read': notification.is_read,
                'message': 'Notificação marcada como lida'
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Erro ao processar: {str(e)}'}, status=500)


class AgentDownloadView(View):
    def get(self, request):
        agent_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'agents', 'agent.ps1'
        ))

        if not os.path.exists(agent_path):
            return JsonResponse({'error': 'Agent file not found'}, status=404)

        with open(agent_path, 'rb') as f:
            resp = HttpResponse(f.read(), content_type='text/plain')
            resp['Content-Disposition'] = 'attachment; filename="agent.ps1"'
            return resp


class AgentVersionView(View):
    def get(self, request):
        agent_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'agents', 'agent.ps1'
        ))

        if not os.path.exists(agent_path):
            return JsonResponse({'error': 'Agent file not found'}, status=404)

        with open(agent_path, 'rb') as f:
            content = f.read()
            sha256 = hashlib.sha256(content).hexdigest()

        return JsonResponse({
            'version': '2.4',
            'download_url': request.build_absolute_uri('/api/agent/download/'),
            'sha256': sha256,
        })


# ==================== VIEWS PARA INTERFACE WEB ====================

class MachineListView(LoginRequiredMixin, ListView):
    model = Machine
    template_name = 'inventario/machine_list.html'
    context_object_name = 'machines'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtros
        hostname = self.request.GET.get('hostname')
        ip_address = self.request.GET.get('ip_address')
        group = self.request.GET.get('group')
        is_online = self.request.GET.get('is_online')

        if hostname:
            queryset = queryset.filter(hostname__icontains=hostname)
        if ip_address:
            queryset = queryset.filter(ip_address__icontains=ip_address)
        if group:
            queryset = queryset.filter(group_id=group)
        if is_online in ('true', 'false'):
            timeout = getattr(settings, 'MACHINE_OFFLINE_TIMEOUT', 15)
            threshold = timezone.now() - timedelta(minutes=timeout)
            if is_online == 'true':
                queryset = queryset.filter(last_seen__gte=threshold)
            else:
                queryset = queryset.filter(
                    Q(last_seen__lt=threshold) | Q(last_seen__isnull=True)
                )

        return queryset.order_by('-last_seen')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['grupos'] = MachineGroup.objects.all()
        return context


class MachineDetailView(LoginRequiredMixin, DetailView):
    model = Machine
    template_name = 'inventario/machine_detail.html'
    context_object_name = 'machine'


class MachineCreateView(LoginRequiredMixin, CreateView):
    model = Machine
    form_class = MachineForm
    template_name = 'inventario/machine_edit.html'
    success_url = reverse_lazy('inventario:machine_list')


class MachineUpdateView(LoginRequiredMixin, UpdateView):
    model = Machine
    form_class = MachineForm
    template_name = 'inventario/machine_edit.html'
    success_url = reverse_lazy('inventario:machine_list')


class MachineDeleteView(LoginRequiredMixin, DeleteView):
    model = Machine
    success_url = reverse_lazy('inventario:machine_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ==================== MACHINE GROUP VIEWS ====================

class MachineGroupListView(LoginRequiredMixin, ListView):
    model = MachineGroup
    template_name = 'inventario/group_list.html'
    context_object_name = 'groups'


class MachineGroupCreateView(LoginRequiredMixin, CreateView):
    model = MachineGroup
    form_class = MachineGroupForm
    template_name = 'inventario/group_form.html'
    success_url = reverse_lazy('inventario:group_list')


class MachineGroupUpdateView(LoginRequiredMixin, UpdateView):
    model = MachineGroup
    form_class = MachineGroupForm
    template_name = 'inventario/group_form.html'
    success_url = reverse_lazy('inventario:group_list')


class MachineGroupDeleteView(LoginRequiredMixin, DeleteView):
    model = MachineGroup
    success_url = reverse_lazy('inventario:group_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ==================== BLOCKED SITE VIEWS ====================

class BlockedSiteListView(LoginRequiredMixin, ListView):
    model = BlockedSite
    template_name = 'inventario/blockedsite_list.html'
    context_object_name = 'sites'


class BlockedSiteCreateView(LoginRequiredMixin, CreateView):
    model = BlockedSite
    form_class = BlockedSiteForm
    template_name = 'inventario/blockedsite_form.html'
    success_url = reverse_lazy('inventario:blockedsite_list')


class BlockedSiteUpdateView(LoginRequiredMixin, UpdateView):
    model = BlockedSite
    form_class = BlockedSiteForm
    template_name = 'inventario/blockedsite_form.html'
    success_url = reverse_lazy('inventario:blockedsite_list')


class BlockedSiteDeleteView(LoginRequiredMixin, DeleteView):
    model = BlockedSite
    success_url = reverse_lazy('inventario:blockedsite_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ==================== NOTIFICATION VIEWS ====================

class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'inventario/notification_list.html'
    context_object_name = 'notifications'
    ordering = ['-created_at']


class NotificationDetailView(LoginRequiredMixin, DetailView):
    model = Notification
    template_name = 'inventario/notification_detail.html'
    context_object_name = 'notification'


class NotificationCreateView(LoginRequiredMixin, CreateView):
    model = Notification
    form_class = NotificationForm
    template_name = 'inventario/notification_form.html'
    success_url = reverse_lazy('inventario:notifications_list')


class NotificationDeleteView(LoginRequiredMixin, DeleteView):
    model = Notification
    success_url = reverse_lazy('inventario:notifications_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ============================================================================
# VIEWS PARA GERENCIAMENTO DE TOKENS
# ============================================================================

class AgentTokenListView(LoginRequiredMixin, ListView):
    model = AgentToken
    template_name = 'inventario/agent_token_list.html'
    context_object_name = 'tokens'
    paginate_by = 50

    def get_queryset(self):
        # prefetch usages para evitar N+1 queries na tabela
        return (AgentToken.objects
                .prefetch_related('usages')
                .order_by('-created_at'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        all_tokens = AgentToken.objects.all()
        now = timezone.now()

        context['total_tokens'] = all_tokens.count()
        context['active_tokens'] = all_tokens.filter(is_active=True).count()
        context['expired_tokens'] = all_tokens.filter(expires_at__lt=now).count()

        # "Em uso" = tokens que têm pelo menos uma máquina registrada
        context['used_tokens'] = (AgentTokenUsage.objects
                                  .values('agent_token')
                                  .distinct()
                                  .count())

        # Total de máquinas distintas registradas via token
        context['total_machines'] = AgentTokenUsage.objects.count()

        return context


class AgentTokenCreateView(LoginRequiredMixin, CreateView):
    """Gera novos tokens de instalação via AgentTokenGenerateForm."""
    model = AgentToken
    template_name = 'inventario/agent_token_create.html'
    fields = []  # campos controlados pelo form customizado
    success_url = reverse_lazy('inventario:token_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = AgentTokenGenerateForm(self.request.POST or None)
        context['default_days'] = 7
        context['max_quantity'] = 50
        return context

    def post(self, request, *args, **kwargs):
        form = AgentTokenGenerateForm(request.POST)

        if not form.is_valid():
            # Reexibe o template com erros
            return render(request, self.template_name, {
                'form': form,
                'default_days': 7,
                'max_quantity': 50,
            })

        quantity = form.cleaned_data['quantity']
        days_val = form.cleaned_data['days']

        try:
            if days_val == 'infinite':
                expires_at = timezone.now() + timedelta(days=36500)
                validity_text = 'sem expiração'
            else:
                days = int(days_val)
                expires_at = timezone.now() + timedelta(days=days)
                validity_text = f'{days} dias'

            generated = []
            for _ in range(quantity):
                # Garante unicidade
                for _ in range(10):
                    token = AgentToken.generate_token()
                    token_hash = AgentToken.hash_token(token)
                    if not AgentToken.objects.filter(token=token).exists():
                        break

                agent_token = AgentToken.objects.create(
                    token=token,
                    token_hash=token_hash,
                    created_by=request.user,
                    expires_at=expires_at,
                )
                generated.append(agent_token)

            if quantity == 1:
                messages.success(
                    request,
                    f'✅ Token gerado: <strong>{generated[0].token}</strong> '
                    f'— validade: {validity_text}',
                    extra_tags='safe',
                )
            else:
                messages.success(
                    request,
                    f'✅ {quantity} tokens gerados com sucesso! Validade: {validity_text}.',
                )

            return redirect(self.success_url)

        except Exception as e:
            messages.error(request, f'❌ Erro ao gerar token: {e}')
            return render(request, self.template_name, {
                'form': form,
                'default_days': 7,
                'max_quantity': 50,
            })


class AgentTokenDeactivateView(LoginRequiredMixin, View):
    """Desativa um token"""

    def post(self, request, pk):
        token = get_object_or_404(AgentToken, pk=pk)
        token.is_active = False
        token.save()

        messages.success(request, f"✅ Token {token.token} desativado.")
        return redirect('inventario:token_list')


class AgentTokenDeleteView(LoginRequiredMixin, View):
    """Remove um token"""

    def post(self, request, pk):
        token = get_object_or_404(AgentToken, pk=pk)
        token_str = token.token
        token.delete()

        messages.success(request, f"✅ Token {token_str} removido.")
        return redirect('inventario:token_list')


# ============================================================================
# VIEWS PARA GERENCIAMENTO DE VERSÕES
# ============================================================================

class AgentVersionListView(LoginRequiredMixin, ListView):
    """Lista versões do agente"""
    model = AgentVersion
    template_name = 'inventario/agent_version_list.html'
    context_object_name = 'versions'
    paginate_by = 50

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        all_versions = AgentVersion.objects.all()
        context['total_versions'] = all_versions.count()
        context['active_versions'] = all_versions.filter(is_active=True).count()

        return context


class AgentVersionCreateView(LoginRequiredMixin, CreateView):
    """Cria nova versão do agente"""
    model = AgentVersion
    template_name = 'inventario/agent_version_create.html'
    fields = ['version', 'file_path', 'release_notes', 'is_mandatory']
    success_url = reverse_lazy('inventario:version_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(
            self.request,
            f"✅ Versão {form.instance.version} criada com sucesso!"
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "❌ Erro ao criar versão. Verifique os campos.")
        return super().form_invalid(form)


class AgentVersionToggleView(LoginRequiredMixin, View):
    """Ativa/desativa versão"""

    def post(self, request, pk):
        version = get_object_or_404(AgentVersion, pk=pk)
        version.is_active = not version.is_active
        version.save()

        status_text = "ativada" if version.is_active else "desativada"
        messages.success(request, f"✅ Versão {version.version} {status_text}.")

        return redirect('inventario:version_list')


# ============================================================================
# API VIEWS (REST) - SEM AUTENTICAÇÃO PARA O AGENTE
# ============================================================================

@method_decorator(csrf_exempt, name='dispatch')
class AgentValidateTokenAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            data = request.data
            token = data.get('token', '').strip()
            machine_name = data.get('machine_name', '')

            if not token:
                return Response({'valid': False, 'message': 'Token não fornecido'}, status=400)

            try:
                agent_token = AgentToken.objects.get(token_hash=token, is_active=True)
            except AgentToken.DoesNotExist:
                return Response({'valid': False, 'message': 'Token inválido'}, status=401)

            if agent_token.is_expired():
                return Response({'valid': False, 'message': 'Token expirado'}, status=401)

            # Registra uso (multi-máquina — não usa mark_as_used que salva em campo único)
            if machine_name:
                AgentTokenUsage.objects.update_or_create(
                    agent_token=agent_token,
                    machine_name=machine_name,
                )

            return Response({
                'valid': True,
                'message': 'Token válido',
                'expires_at': agent_token.expires_at.isoformat()
            })

        except Exception as e:
            return Response({'valid': False, 'message': f'Erro: {str(e)}'}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class AgentCheckUpdateAPIView(AgentTokenRequiredMixin, APIView):
    """
    Verifica se há atualização disponível para o agente.

    POST /api/inventario/agent/update/
    Headers: Authorization: Bearer <token_hash>
    Body: {
        "current_version": "3.2.0",
        "machine_name":    "PC-NOME",
        "agent_type":      "service"   # ou "tray"
    }
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        try:
            data = request.data
            current_version = data.get("current_version", "0.0.0")
            agent_type = data.get("agent_type", "service").strip().lower()

            # Valida agent_type
            if agent_type not in ("service", "tray"):
                return Response(
                    {"update_available": False, "error": "agent_type inválido"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Busca a versão mais recente ativa para este tipo
            latest = (
                AgentVersion.objects
                .filter(is_active=True, agent_type=agent_type)
                .order_by("-created_at")
                .first()
            )

            if not latest:
                return Response({
                    "update_available": False,
                    "message": f"Nenhuma versão ativa disponível para agent_type={agent_type}",
                })

            def version_tuple(v):
                try:
                    return tuple(map(int, str(v).split(".")))
                except Exception:
                    return (0, 0, 0)

            is_newer = version_tuple(latest.version) > version_tuple(current_version)

            if is_newer or latest.is_mandatory:
                return Response({
                    "update_available": True,
                    "version": latest.version,
                    "agent_type": agent_type,
                    "download_url": request.build_absolute_uri(
                        f"/api/inventario/agent/download/{latest.pk}/"
                    ),
                    "sha256": latest.sha256,  # ← NOVO: hash para verificação
                    "release_notes": latest.release_notes,
                    "is_mandatory": latest.is_mandatory,
                })

            return Response({
                "update_available": False,
                "current_version": current_version,
                "latest_version": latest.version,
                "agent_type": agent_type,
            })

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@method_decorator(csrf_exempt, name='dispatch')
class AgentDownloadAPIView(AgentTokenRequiredMixin, APIView):
    """
    API para download da versão do agente.
    PROTEGIDA — exige Authorization: Bearer <token_hash>
    Antes estava completamente aberta (authentication_classes=[], permission_classes=[]).
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk):
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        try:
            version = get_object_or_404(AgentVersion, pk=pk, is_active=True)

            if not version.file_path:
                return Response({'error': 'Arquivo não encontrado'}, status=status.HTTP_404_NOT_FOUND)

            response = FileResponse(
                version.file_path.open('rb'),
                content_type='text/x-python'
            )
            response['Content-Disposition'] = f'attachment; filename="agent_{version.version}.py"'
            return response

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class AgentHealthCheckAPIView(APIView):
    """
    API de health check do servidor.
    PÚBLICA — não retorna dados sensíveis, usada apenas para checar conectividade.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({'status': 'healthy', 'timestamp': timezone.now().isoformat()})

class BulkNotificationCreateView(LoginRequiredMixin, View):
    """Envia a mesma notificação para múltiplas máquinas ou grupos"""
    template_name = 'inventario/notification_bulk_form.html'

    def get(self, request):
        from .forms import BulkNotificationForm
        form = BulkNotificationForm()
        groups = MachineGroup.objects.all()
        return render(request, self.template_name, {'form': form, 'groups': groups})

    def post(self, request):
        from .forms import BulkNotificationForm
        form = BulkNotificationForm(request.POST)
        groups = MachineGroup.objects.all()

        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'groups': groups})

        machines = form.cleaned_data['machines']
        title = form.cleaned_data['title']
        message = form.cleaned_data['message']
        notif_type = form.cleaned_data['type']
        priority = form.cleaned_data['priority']
        expires_at = form.cleaned_data.get('expires_at')

        # Adiciona máquinas dos grupos selecionados
        group_ids = request.POST.getlist('groups')
        if group_ids:
            group_machines = Machine.objects.filter(group_id__in=group_ids)
            machines = (machines | group_machines).distinct()

        created = 0
        for machine in machines:
            Notification.objects.create(
                machine=machine,
                title=title,
                message=message,
                type=notif_type,
                priority=priority,
                expires_at=expires_at,
            )
            created += 1

        messages.success(request, f'Notificação enviada para {created} máquina(s) com sucesso!')
        return redirect(reverse_lazy('inventario:notifications_list'))


@method_decorator(csrf_exempt, name='dispatch')
class AgentMachineInfoAPIView(AgentTokenRequiredMixin, APIView):
    """
    GET /api/inventario/agent/machine/
    Authorization: Bearer <token_hash>
    X-Machine-Name: DESKTOP-ABC123
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        agent_token, err = self._authenticate(request)
        if err:
            return err

        machine, err = self._get_machine(request, agent_token)
        if err:
            return err

        ativos = []
        try:
            from apps.ativos.models import Ativo
            for a in Ativo.objects.filter(computador=machine).select_related('categoria'):
                ativos.append({
                    'nome': a.nome,
                    'etiqueta': a.etiqueta or '',
                    'categoria': a.categoria.nome if a.categoria else '',
                })
        except Exception:
            pass

        checkin = machine.last_seen.strftime('%d/%m/%Y %H:%M') if machine.last_seen else '—'

        return Response({
            'ok': True,
            'hostname': machine.hostname,
            'online': machine.is_online,
            'ip': machine.ip_address or '—',
            'logged_user': machine.loggedUser or '—',
            'last_checkin': checkin,
            'ativos': ativos,
        })