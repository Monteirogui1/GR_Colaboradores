import os
import re
import json
import datetime
import logging
import hashlib

from django.views import View
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db import models as dj_models

from .models import Machine, BlockedSite, Notification

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

            install_date = parse_wmi_date(hw.get('install_date'))
            last_boot = parse_wmi_date(hw.get('last_boot'))

            machine, _ = Machine.objects.update_or_create(
                hostname=hostname,
                defaults={
                    'ip_address': ip,
                    'is_online': True,
                    'last_seen': timezone.now(),

                    'loggeduser': hw.get('logged_user'),

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
            'version': '2.2',
            'download_url': request.build_absolute_uri('/api/agent/download/'),
            'sha256': sha256,
        })