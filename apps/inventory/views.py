import os
import re
import json
from datetime import datetime, timedelta
import logging
import hashlib
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

from .forms import MachineForm, NotificationForm, BlockedSiteForm, MachineGroupForm
from .models import Machine, BlockedSite, Notification, MachineGroup, AgentToken, AgentVersion

logger = logging.getLogger(__name__)


def parse_wmi_date(wmi_str):
    """Converte '/Date(1755216000000)/' para datetime UTC."""
    m = re.search(r'/Date\((\d+)\)/', wmi_str or '')
    if not m:
        return None
    ms = int(m.group(1))
    return datetime.datetime.utcfromtimestamp(ms / 1000).replace(
        tzinfo=datetime.timezone.utc
    )


@method_decorator(csrf_exempt, name='dispatch')
class MachineCheckinView(View):
    def post(self, request):
        try:


            raw = request.body.decode('utf-8')
            data = json.loads(raw)
            hostname = data['hostname']
            ip = data.get('ip', '')
            hw = data.get('hardware', {})

            token_hash = data.get("token")
            if not AgentToken.objects.filter(token_hash=token_hash, is_active=True).exists():
                return JsonResponse({'error': 'Token inválido'}, status=401)

            install_date = parse_wmi_date(hw.get('install_date'))
            last_boot = parse_wmi_date(hw.get('last_boot'))

            machine, _ = Machine.objects.update_or_create(
                hostname=hostname,
                defaults={
                    'ip_address': ip,
                    'is_online': True,
                    'last_seen': timezone.now(),

                    'loggedUser': hw.get('logged_user'),

                    'tpm': hw.get('tpm'),

                    'mac_address': hw.get('mac_address'),
                    'total_memory_slots': hw.get('total_memory_slots'),
                    'populated_memory_slots': hw.get('populated_memory_slots'),
                    'memory_modules': hw.get('memory_modules'),

                    'os_caption': hw.get('os_caption'),
                    'os_architecture': hw.get('os_architecture'),
                    'os_build': hw.get('os_build'),
                    'install_date': install_date,
                    'last_boot': last_boot,
                    'uptime_days': hw.get('uptime_days'),

                    'cpu': hw.get('cpu'),
                    'ram_gb': hw.get('ram_gb'),
                    'disk_space_gb': hw.get('disk_space_gb'),
                    'disk_free_gb': hw.get('disk_free_gb'),

                    'network_info': hw.get('network_adapters'),
                    'gpu_name': hw.get('gpu_name'),
                    'gpu_driver': hw.get('gpu_driver'),
                    'antivirus_name': hw.get('antivirus_name'),
                    'av_state': str(hw.get('av_state')),
                },
            )
            return JsonResponse({'status': 'ok', 'machine_id': machine.id})
        except Exception as e:
            logger.exception("Erro no check-in")
            return JsonResponse({'error': str(e)}, status=400)

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


class RunCommandView(LoginRequiredMixin, View):
    def post(self, request, machine_id):
        try:
            machine = Machine.objects.get(id=machine_id)
        except Machine.DoesNotExist:
            return JsonResponse({'error': 'Machine not found'}, status=404)

        cmd = request.POST.get('command', '').strip()
        if not cmd:
            return JsonResponse({'error': 'command required'}, status=400)

        # executa via WinRM
        import winrm  # se ainda precisar desse recurso

        try:
            session = winrm.Session(
                f"http://{machine.ip_address}:5985/wsman",
                auth=('admin', 'senha'),
                server_cert_validation='ignore',
            )
            result = session.run_ps(cmd)
            return JsonResponse(
                {
                    'stdout': result.std_out.decode('utf-8', 'ignore'),
                    'stderr': result.std_err.decode('utf-8', 'ignore'),
                    'status_code': result.status_code,
                }
            )
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class MachineNotificationView(View):
    """
    Endpoint que o agente consulta para puxar notificações pendentes.
    Ex.: GET /api/notifications/?host=MACHINE_NAME
    """
    def get(self, request):
        host = request.GET.get('host')
        if not host:
            return JsonResponse({'error': 'host parameter required'}, status=400)

        try:
            machine = Machine.objects.get(hostname=host)
        except Machine.DoesNotExist:
            return JsonResponse([], safe=False)

        qs = (
            Notification.objects.filter(sent_to_all=True)
            | Notification.objects.filter(machines=machine)
            | Notification.objects.filter(groups=machine.group)
        )
        qs = qs.distinct().order_by('-created_at')

        payload = [
            {'title': n.title, 'message': n.message} for n in qs
        ]
        return JsonResponse(payload, safe=False)


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
        if is_online:
            queryset = queryset.filter(is_online=(is_online == 'true'))

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
    success_url = reverse_lazy('inventario:notification_list')


class NotificationDeleteView(LoginRequiredMixin, DeleteView):
    model = Notification
    success_url = reverse_lazy('inventario:notification_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()
        self.object.delete()
        return JsonResponse({'status': 'success', 'redirect': success_url})


# ============================================================================
# VIEWS PARA GERENCIAMENTO DE TOKENS
# ============================================================================

class AgentTokenListView(LoginRequiredMixin, ListView):
    """Lista todos os tokens gerados"""
    model = AgentToken
    template_name = 'inventario/agent_token_list.html'
    context_object_name = 'tokens'
    paginate_by = 50

    def get_queryset(self):
        """Retorna tokens do cliente logado"""
        queryset = super().get_queryset()
        # Se tiver filtro por cliente, adicione aqui
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Estatísticas
        all_tokens = AgentToken.objects.all()
        context['total_tokens'] = all_tokens.count()
        context['active_tokens'] = all_tokens.filter(is_active=True).count()
        context['used_tokens'] = all_tokens.filter(used_at__isnull=False).count()
        context['expired_tokens'] = all_tokens.filter(
            expires_at__lt=timezone.now()
        ).count()

        return context


class AgentTokenCreateView(LoginRequiredMixin, CreateView):
    """Gera novos tokens de instalação"""
    model = AgentToken
    template_name = 'inventario/agent_token_create.html'
    fields = []
    success_url = reverse_lazy('inventario:token_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['default_days'] = 7
        context['max_quantity'] = 50
        return context

    def post(self, request, *args, **kwargs):
        try:
            # Quantidade de tokens
            quantity = int(request.POST.get('quantity', 1))
            if quantity < 1 or quantity > 50:
                raise ValueError("Quantidade deve ser entre 1 e 50")

            # Validade em dias
            days = request.POST.get('days', '7')

            # Verifica se é validade infinita
            if days == 'infinite':
                # Define data muito distante (100 anos no futuro)
                expires_at = timezone.now() + timedelta(days=36500)
                validity_text = "sem expiração"
            else:
                days = int(days)
                if days < 1 or days > 365:
                    raise ValueError("Validade deve ser entre 1 e 365 dias ou infinita")
                expires_at = timezone.now() + timedelta(days=days)
                validity_text = f"{days} dias"

            generated_tokens = []

            for _ in range(quantity):
                # Gera token único
                while True:
                    token = AgentToken.generate_token()
                    token_hash = AgentToken.hash_token(token)

                    if not AgentToken.objects.filter(token=token).exists():
                        break

                # Cria registro
                agent_token = AgentToken.objects.create(
                    token=token,
                    token_hash=token_hash,
                    created_by=request.user,
                    expires_at=expires_at
                )

                generated_tokens.append(agent_token)

            if quantity == 1:
                messages.success(
                    request,
                    f"✅ Token gerado: <strong>{generated_tokens[0].token}</strong>",
                    extra_tags='safe'
                )
            else:
                messages.success(
                    request,
                    f"✅ {quantity} tokens gerados com sucesso!"
                )

            return redirect(self.success_url)

        except ValueError as e:
            messages.error(request, f"❌ Erro: {str(e)}")
            return redirect('inventario:token_create')
        except Exception as e:
            messages.error(request, f"❌ Erro ao gerar token: {str(e)}")
            return redirect('inventario:token_create')


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
    """API para validar token de instalação do agente"""
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            data = request.data
            token = data.get('token', '').strip()
            machine_name = data.get('machine_name', '')

            if not token:
                return Response(
                    {'valid': False, 'message': 'Token não fornecido'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Busca token
            try:
                agent_token = AgentToken.objects.get(token_hash=token, is_active=True)
            except AgentToken.DoesNotExist:
                return Response(
                    {'valid': False, 'message': 'Token inválido'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Verifica expiração
            if agent_token.is_expired():
                return Response(
                    {'valid': False, 'message': 'Token expirado'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Marca como usado se ainda não foi
            if not agent_token.used_at:
                agent_token.mark_as_used(machine_name)

            return Response({
                'valid': True,
                'message': 'Token válido',
                'expires_at': agent_token.expires_at.isoformat()
            })

        except Exception as e:
            return Response(
                {'valid': False, 'message': f'Erro: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class AgentCheckUpdateAPIView(APIView):
    """API para verificar atualizações disponíveis"""
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            data = request.data
            current_version = data.get('current_version', '0.0.0')
            machine_name = data.get('machine_name', '')

            # Busca versão mais recente ativa
            latest_version = AgentVersion.objects.filter(
                is_active=True
            ).order_by('-created_at').first()

            if not latest_version:
                return Response({
                    'update_available': False,
                    'message': 'Nenhuma versão disponível'
                })

            # Compara versões (simplificado)
            def version_tuple(v):
                try:
                    return tuple(map(int, v.split('.')))
                except:
                    return (0, 0, 0)

            current = version_tuple(current_version)
            latest = version_tuple(latest_version.version)

            if latest > current or latest_version.is_mandatory:
                return Response({
                    'update_available': True,
                    'version': latest_version.version,
                    'download_url': request.build_absolute_uri(
                        f'/api/inventario/agent/download/{latest_version.pk}/'
                    ),
                    'release_notes': latest_version.release_notes,
                    'is_mandatory': latest_version.is_mandatory
                })

            return Response({
                'update_available': False,
                'current_version': current_version,
                'latest_version': latest_version.version
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class AgentDownloadAPIView(APIView):
    """API para download da versão do agente"""
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk):
        try:
            version = get_object_or_404(AgentVersion, pk=pk, is_active=True)

            if not version.file_path:
                return Response(
                    {'error': 'Arquivo não encontrado'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Retorna arquivo
            response = FileResponse(
                version.file_path.open('rb'),
                content_type='text/x-python'
            )
            response['Content-Disposition'] = f'attachment; filename="agent_{version.version}.py"'

            return response

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_exempt, name='dispatch')
class AgentHealthCheckAPIView(APIView):
    """API de health check do servidor"""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat()
        })