import concurrent.futures
import mimetypes
import os
import re
import json
import requests
from datetime import timedelta
import datetime
import logging
import hashlib
import datetime as dt
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
from django.views.generic import ListView, DetailView, UpdateView, CreateView, DeleteView, TemplateView
from django.urls import reverse_lazy
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from django.db.models import Q
from .forms import MachineForm, NotificationForm, BlockedSiteForm, MachineGroupForm, AgentTokenGenerateForm
from .models import (Machine, BlockedSite, Notification, MachineGroup, AgentToken, AgentVersion, AgentTokenUsage,
                     AgentDownloadLog, AgentUpdateReport)

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


def _sanitize_str(v) -> "str | None":
    """
    Remove null bytes (\\u0000) e retorna None se vazio/None.

    PostgreSQL text/varchar rejeita \\u0000 com:
      unsupported Unicode escape sequence / \\u0000 cannot be converted to text
    Origem: PowerShell serializa strings WMI com null bytes no final
            ex: tpm.manufacturer_ver = "11.6.10.1196\\u0000"
    """
    if v is None:
        return None
    cleaned = str(v).replace("\\u0000", "").replace("\\x00", "").strip()
    return cleaned if cleaned and cleaned.lower() != "none" else None


def _remove_null_chars(s: str) -> str:
    """
    Remove todos os caracteres nulos de uma string.
    Usa filter+ord porque replace('\\x00','') pode falhar dependendo
    de como o Python internalizou o caractere (\\u0000 vs \\x00).
    """
    return ''.join(c for c in s if ord(c) != 0)


def _sanitize_json(v):
    """
    Garante dict/list ou None para JSONField — remove null bytes (\\x00/\\u0000).
    PostgreSQL jsonb rejeita null bytes: DataError: unsupported Unicode escape sequence.
    Origem: PowerShell serializa strings WMI com null bytes no final
            ex: tpm.manufacturer_ver = '11.8.50.3399\\x00'
    Usa ord(c) != 0 porque replace('\\x00','') pode não capturar todos os casos.
    """
    if v is None:
        return None

    def _clean(obj):
        if isinstance(obj, str):
            cleaned = _remove_null_chars(obj)
            return cleaned if cleaned else None
        if isinstance(obj, dict):
            return {k: _clean(val) for k, val in obj.items()}
        if isinstance(obj, list):
            return [_clean(item) for item in obj]
        return obj

    if isinstance(v, (dict, list)):
        return _clean(v)
    if isinstance(v, str):
        try:
            import json as _json
            parsed = _json.loads(v)
            if isinstance(parsed, (dict, list)):
                return _clean(parsed)
        except Exception:
            pass
    return None


def _sanitize_float(v) -> "float | None":
    """Converte para float ou None. PostgreSQL FloatField rejeita strings não-numéricas."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sanitize_int(v) -> "int | None":
    """Converte para int ou None. PostgreSQL IntegerField rejeita strings não-numéricas."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_wmi_date(wmi_date_str):
    """
    Converte data WMI/PowerShell para datetime timezone-aware (UTC).

    Formatos suportados:
      - /Date(1234567890000)/  — timestamp ms (ConvertTo-Json padrão)
      - ISO 8601               — PowerShell 5+ com -Depth alto
      - datetime Python        — passado diretamente
    """
    if not wmi_date_str:
        return None
    try:
        if isinstance(wmi_date_str, str) and wmi_date_str.startswith("/Date("):
            ms = int(wmi_date_str.replace("/Date(", "").replace(")/", ""))
            return datetime.datetime.fromtimestamp(
                ms / 1000, tz=datetime.timezone.utc
            )
        if isinstance(wmi_date_str, datetime.datetime):
            if wmi_date_str.tzinfo is None:
                return wmi_date_str.replace(tzinfo=datetime.timezone.utc)
            return wmi_date_str
        if isinstance(wmi_date_str, str):
            for fmt in (
                    "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S.%f%z",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    s = wmi_date_str.rstrip("Z") if fmt.endswith("Z") else wmi_date_str
                    f = fmt.rstrip("Z") if fmt.endswith("Z") else fmt
                    parsed = datetime.datetime.strptime(s, f)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                    return parsed
                except ValueError:
                    continue
    except Exception as e:
        logger.error(f"parse_wmi_date: {wmi_date_str!r} — {e}")
    return None


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

                    # Dados do usuário
                    'loggedUser': _sanitize_str(hw.get('logged_user')),

                    # JSONFields — PostgreSQL jsonb rejeita \\u0000 dentro de strings
                    'tpm':            _sanitize_json(hw.get('tpm')),
                    'memory_modules': _sanitize_json(hw.get('memory_modules')),
                    'network_info':   _sanitize_json(hw.get('network_adapters')),

                    # Hardware
                    'manufacturer':           _sanitize_str(hw.get('manufacturer')),
                    'model':                  _sanitize_str(hw.get('model')),
                    'serial_number':          _sanitize_str(hw.get('serial_number')),
                    'bios_version':           _sanitize_str(hw.get('bios_version')),
                    'mac_address':            _sanitize_str(hw.get('mac_address')),

                    # RAM slots — IntegerField, PostgreSQL rejeita string não-numérica
                    'total_memory_slots':     _sanitize_int(hw.get('total_memory_slots')),
                    'populated_memory_slots': _sanitize_int(hw.get('populated_memory_slots')),

                    # SO
                    'os_caption':     _sanitize_str(hw.get('os_caption')),
                    'os_architecture':_sanitize_str(hw.get('os_architecture')),
                    'os_build':       _sanitize_str(hw.get('os_build')),
                    'install_date':   install_date,
                    'last_boot':      last_boot,

                    # Métricas — FloatField, PostgreSQL rejeita string não-numérica
                    'uptime_days':  _sanitize_float(hw.get('uptime_days')),
                    'cpu':          _sanitize_str(hw.get('cpu')),
                    'ram_gb':       _sanitize_float(hw.get('ram_gb')),
                    'disk_space_gb':_sanitize_float(hw.get('disk_space_gb')),
                    'disk_free_gb': _sanitize_float(hw.get('disk_free_gb')),

                    # GPU
                    'gpu_name':   _sanitize_str(hw.get('gpu_name')),
                    'gpu_driver': _sanitize_str(hw.get('gpu_driver')),

                    # Segurança — av_state é int no PowerShell (productState)
                    # BUG ORIGINAL: str(None) = "None" → salva string "None" no banco
                    # CORREÇÃO: _sanitize_str retorna None quando valor é None
                    'antivirus_name': _sanitize_str(hw.get('antivirus_name')),
                    'av_state':       _sanitize_str(hw.get('av_state')),
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


class BulkRunCommandView(LoginRequiredMixin, TemplateView):
    """
    Executa um comando PowerShell ou CMD em múltiplas máquinas em paralelo.

    GET  /run/bulk/  → renderiza o formulário visual
    POST /run/bulk/  → executa o comando e retorna JSON com os resultados

    Auth: LoginRequiredMixin + is_staff.
    Reutiliza exatamente o mesmo endpoint 7071/command do agente — sem alterações.

    Args (POST, JSON):
        command     (str):       Comando a executar.
        cmd_type    (str):       ``powershell`` ou ``cmd``.
        timeout     (int):       Timeout por máquina em segundos (5–120).
        max_workers (int):       Paralelismo (1–30).
        machine_ids (list[int]): IDs de máquinas individuais.
        group_ids   (list[int]): IDs de grupos (expande para todas as máquinas).
        all_machines(bool):      Se true, seleciona todas as máquinas com IP.
    """

    template_name = "inventario/bulk_command.html"

    def handle_no_permission(self):
        return JsonResponse({"error": "Autenticação necessária."}, status=401)

    def get_context_data(self, **kwargs):
        """Popula contexto com grupos e máquinas para o formulário visual."""
        context = super().get_context_data(**kwargs)
        timeout = getattr(settings, 'MACHINE_OFFLINE_TIMEOUT', 15)
        limite = timezone.now() - timedelta(minutes=timeout)

        context["groups"] = MachineGroup.objects.prefetch_related("machine_set").all()

        context["machines"] = (
            Machine.objects
            .filter(ip_address__isnull=False, last_seen__gte=limite)
            .order_by("hostname")
        )

        return context

    # ------------------------------------------------------------------
    # POST — execução do comando (retorna JSON)
    # ------------------------------------------------------------------

    def post(self, request, *args, **kwargs):
        """Valida payload, resolve máquinas e executa em paralelo."""
        if not request.user.is_staff:
            return JsonResponse({"error": "Acesso negado. Requer is_staff."}, status=403)

        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Body deve ser JSON válido."}, status=400)

        command     = payload.get("command", "").strip()
        cmd_type    = payload.get("cmd_type", "powershell").strip().lower()
        timeout     = int(payload.get("timeout", 60))
        max_workers = int(payload.get("max_workers", 10))
        machine_ids = payload.get("machine_ids", [])
        group_ids   = payload.get("group_ids", [])
        all_machines = bool(payload.get("all_machines", False))

        # Validações básicas
        if not command:
            return JsonResponse({"error": "Comando não pode estar vazio."}, status=400)
        if cmd_type not in ("powershell", "cmd"):
            return JsonResponse({"error": "cmd_type inválido. Use 'powershell' ou 'cmd'."}, status=400)
        timeout     = max(5, min(timeout, 120))
        max_workers = max(1, min(max_workers, 30))

        machines = self._resolve_machines(machine_ids, group_ids, all_machines)
        if not machines:
            return JsonResponse({"error": "Nenhuma máquina encontrada com os critérios informados."}, status=404)

        logger.info(
            f"BulkCommand | user={request.user.username} type={cmd_type} "
            f"machines={len(machines)} workers={max_workers} cmd={command[:80]!r}"
        )

        import time as _time
        t0 = _time.monotonic()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._run_on_machine, m, command, cmd_type, timeout): m
                for m in machines
            }
            results = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    m = futures[future]
                    results.append({
                        "machine_id": m.id,
                        "hostname":   m.hostname,
                        "ip_address": m.ip_address,
                        "status":     "error",
                        "exit_code":  -1,
                        "stdout": "", "stderr": "",
                        "error": str(exc),
                        "elapsed_ms": 0,
                    })

        elapsed = round(_time.monotonic() - t0, 2)
        results.sort(key=lambda r: r["hostname"].lower())

        summary = {
            "total":           len(results),
            "success":         sum(1 for r in results if r["status"] == "ok"),
            "failed":          sum(1 for r in results if r["status"] == "error"),
            "offline":         sum(1 for r in results if r["status"] == "offline"),
            "skipped":         sum(1 for r in results if r["status"] == "skipped"),
            "elapsed_seconds": elapsed,
            "results":         results,
        }

        logger.info(
            f"BulkCommand | ok={summary['success']} error={summary['failed']} "
            f"offline={summary['offline']} elapsed={elapsed}s"
        )
        return JsonResponse(summary)

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _resolve_machines(self, machine_ids, group_ids, all_machines):
        """
        Converte seleção do payload em lista de Machine com IP.

        Args:
            machine_ids:  Lista de IDs de máquinas individuais.
            group_ids:    Lista de IDs de grupos.
            all_machines: Se True, seleciona todas as máquinas com IP.

        Returns:
            Lista de objetos Machine.
        """
        timeout = getattr(settings, 'MACHINE_OFFLINE_TIMEOUT', 15)
        limite = timezone.now() - timedelta(minutes=timeout)

        base_qs = Machine.objects.filter(
            ip_address__isnull=False, last_seen__gte=limite
        ).select_related("group")

        if all_machines:
            return list(base_qs)
        if group_ids:
            return list(base_qs.filter(group_id__in=group_ids))
        if machine_ids:
            return list(base_qs.filter(id__in=machine_ids))
        return []

    def _get_token_for_machine(self, machine):
        """
        Resolve token de autenticação para a máquina — mesma lógica do RunCommandView.

        Args:
            machine: Instância de Machine.

        Returns:
            AgentToken ativo ou None.
        """
        try:
            usage = (
                AgentTokenUsage.objects
                .filter(machine_name__iexact=machine.hostname)
                .select_related("agent_token")
                .order_by("-last_used_at")
                .first()
            )
            if usage and usage.agent_token.is_active and not usage.agent_token.is_expired():
                return usage.agent_token
        except Exception:
            pass
        return AgentToken.objects.filter(is_active=True).first()

    def _run_on_machine(self, machine, command, cmd_type, timeout):
        """
        Executa o comando em uma máquina via HTTP 7071/command — mesmo protocolo do RunCommandView.

        Args:
            machine:  Instância de Machine.
            command:  Comando a executar.
            cmd_type: ``powershell`` ou ``cmd``.
            timeout:  Timeout em segundos.

        Returns:
            Dicionário com status, exit_code, stdout, stderr, error e elapsed_ms.
        """
        import time as _time
        import requests as req

        base = {
            "machine_id": machine.id,
            "hostname":   machine.hostname,
            "ip_address": machine.ip_address,
        }
        token_obj = self._get_token_for_machine(machine)
        if not token_obj:
            return {**base, "status": "skipped", "exit_code": -1,
                    "stdout": "", "stderr": "",
                    "error": "Nenhum token ativo disponível", "elapsed_ms": 0}

        headers = {"Authorization": f"Bearer {token_obj.token_hash}"}
        t0 = _time.monotonic()

        try:
            resp = req.post(
                f"http://{machine.ip_address}:7071/command",
                json={"type": cmd_type, "script": command, "timeout": timeout},
                headers=headers,
                timeout=timeout + 5,
            )
            elapsed = int((_time.monotonic() - t0) * 1000)
            data    = resp.json()
            return {
                **base,
                "status":     "ok" if resp.status_code == 200 else "error",
                "exit_code":  data.get("exit_code", -1),
                "stdout":     data.get("stdout", ""),
                "stderr":     data.get("stderr", ""),
                "error":      data.get("error", ""),
                "elapsed_ms": elapsed,
            }
        except req.exceptions.ConnectionError:
            elapsed = int((_time.monotonic() - t0) * 1000)
            return {**base, "status": "offline", "exit_code": -1,
                    "stdout": "", "stderr": "",
                    "error": f"Agente inacessível ({machine.ip_address}:7071)",
                    "elapsed_ms": elapsed}
        except req.exceptions.Timeout:
            elapsed = int((_time.monotonic() - t0) * 1000)
            return {**base, "status": "error", "exit_code": -1,
                    "stdout": "", "stderr": "",
                    "error": f"Timeout após {timeout}s", "elapsed_ms": elapsed}
        except Exception as exc:
            elapsed = int((_time.monotonic() - t0) * 1000)
            return {**base, "status": "error", "exit_code": -1,
                    "stdout": "", "stderr": "", "error": str(exc),
                    "elapsed_ms": elapsed}


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
        loggedUser = self.request.GET.get('loggedUser')
        ip_address = self.request.GET.get('ip_address')
        group = self.request.GET.get('group')
        is_online = self.request.GET.get('is_online')

        if hostname:
            queryset = queryset.filter(hostname__icontains=hostname)
        if loggedUser:
            queryset = queryset.filter(loggedUser__icontains=loggedUser)
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

    Endpoint: POST /api/inventario/agent/update/
    Auth: Authorization: Bearer <token_hash>
    Headers extras: X-Machine-Name: <hostname>

    Body::

        {
            "current_version": "3.2.0",
            "machine_name":    "PC-NOME",
            "agent_type":      "service"  # ou "tray"
        }

    Retorno quando há atualização::

        {
            "update_available": true,
            "version":          "3.3.0",
            "agent_type":       "service",
            "download_url":     "https://…/api/inventario/agent/download/42/",
            "sha256":           "abc123…",
            "release_notes":    "…",
            "is_mandatory":     false
        }

    Ordenação semântica via ``AgentVersion.latest_active()`` —
    corrige o bug anterior onde ``-created_at`` podia retornar
    uma versão menor em cenários de hotfix/revert.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """Verifica atualização disponível para o agent_type informado."""
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        current_version = request.data.get("current_version", "0.0.0")
        agent_type = request.data.get("agent_type", "service").strip().lower()

        if agent_type not in ("service", "tray"):
            return Response(
                {"update_available": False, "error": "agent_type inválido. Use 'service' ou 'tray'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        latest = AgentVersion.latest_active(agent_type)

        if not latest:
            return Response({
                "update_available": False,
                "message": f"Nenhuma versão ativa disponível para agent_type={agent_type}",
            })

        current_tuple = AgentVersion.version_tuple(current_version)
        latest_tuple  = AgentVersion.version_tuple(latest.version)
        is_newer      = latest_tuple > current_tuple

        if is_newer or latest.is_mandatory:
            return Response({
                "update_available":  True,
                "version":           latest.version,
                "agent_type":        agent_type,
                "download_url":      request.build_absolute_uri(
                    f"/api/inventario/agent/download/{latest.pk}/"
                ),
                "sha256":            latest.sha256,
                "release_notes":     latest.release_notes,
                "is_mandatory":      latest.is_mandatory,
                # URLs para hot-update enquanto o agente está em execução:
                # 1) baixa o script PowerShell launcher
                # 2) executa o script e encerra — o script substitui o exe e reinicia
                "update_script_url": request.build_absolute_uri(
                    f"/api/inventario/agent/update-script/?type={agent_type}&version_id={latest.pk}"
                ),
                "report_url":        request.build_absolute_uri(
                    "/api/inventario/agent/update-report/"
                ),
            })

        return Response({
            "update_available": False,
            "current_version":  current_version,
            "latest_version":   latest.version,
            "agent_type":       agent_type,
        })


@method_decorator(csrf_exempt, name="dispatch")
class AgentDownloadAPIView(AgentTokenRequiredMixin, APIView):
    """
    Download autenticado do binário de uma versão do agente.

    Endpoint: GET /api/inventario/agent/download/<pk>/
    Auth: Authorization: Bearer <token_hash>
    Headers extras: X-Machine-Name: <hostname>

    Correções em relação à versão anterior:

    - ``Content-Type`` determinado pela extensão real do arquivo
      (``application/octet-stream`` para ``.exe``, ``text/x-python`` para ``.py``).
    - ``Content-Disposition`` usa o nome original do arquivo em vez de
      um nome fixo ``agent_<version>.py``.
    - Registra ``AgentDownloadLog`` após servir o arquivo, permitindo
      auditoria por máquina.
    - Usa ``FileResponse`` com ``as_attachment=True`` — fecha o handle
      automaticamente ao final do streaming.
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request, pk: int):
        """Serve o binário da versão solicitada e registra o download."""
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        version_obj = get_object_or_404(AgentVersion, pk=pk, is_active=True)

        if not version_obj.file_path:
            return Response(
                {"error": "Arquivo não encontrado para esta versão."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Detecta content-type pela extensão real do arquivo
        file_name = version_obj.file_path.name.split("/")[-1]
        content_type, _ = mimetypes.guess_type(file_name)
        if not content_type:
            content_type = "application/octet-stream"

        machine_name = (
            request.META.get("HTTP_X_MACHINE_NAME", "").strip()
            or request.data.get("machine_name", "unknown")
        )
        ip_address = (
            request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")
        )

        # Registra o log ANTES de servir — se o FileResponse falhar,
        # não há double-log porque a exceção interrompe o fluxo.
        AgentDownloadLog.objects.create(
            agent_version=version_obj,
            machine_name=machine_name or "unknown",
            ip_address=ip_address or None,
        )

        logger.info(
            f"Download | versão={version_obj.version} tipo={version_obj.agent_type} "
            f"máquina={machine_name} ip={ip_address}"
        )

        response = FileResponse(
            version_obj.file_path.open("rb"),
            content_type=content_type,
            as_attachment=True,
            filename=file_name,
        )
        return response


class AgentDownloadLogAPIView(APIView):
    """
    Lista logs de download de versões do agente.

    Endpoint: GET /api/inventario/agent/download-logs/
    Auth: Sessão Django (IsAuthenticated) — apenas administradores.

    Query params opcionais:

    - ``agent_type`` — filtra por ``service`` ou ``tray``
    - ``version_id`` — filtra por ID da versão
    - ``machine``    — filtra por nome de máquina (icontains)
    - ``limit``      — número máximo de resultados (padrão 100, máx 500)
    """

    def get(self, request):
        """Retorna logs de download com filtros opcionais."""
        if not request.user.is_authenticated:
            return Response({"error": "Autenticação necessária."}, status=status.HTTP_401_UNAUTHORIZED)

        qs = (
            AgentDownloadLog.objects
            .select_related("agent_version")
            .order_by("-downloaded_at")
        )

        agent_type = request.query_params.get("agent_type", "").strip().lower()
        if agent_type in ("service", "tray"):
            qs = qs.filter(agent_version__agent_type=agent_type)

        version_id = request.query_params.get("version_id", "").strip()
        if version_id.isdigit():
            qs = qs.filter(agent_version_id=int(version_id))

        machine = request.query_params.get("machine", "").strip()
        if machine:
            qs = qs.filter(machine_name__icontains=machine)

        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (ValueError, TypeError):
            limit = 100

        from .serializers import AgentDownloadLogSerializer
        serializer = AgentDownloadLogSerializer(qs[:limit], many=True)
        return Response({
            "count": qs.count(),
            "limit": limit,
            "results": serializer.data,
        })


@method_decorator(csrf_exempt, name='dispatch')
class AgentUpdateScriptAPIView(AgentTokenRequiredMixin, APIView):
    """
    Gera e retorna script PowerShell de hot-update para o agente.

    Endpoint: GET /api/inventario/agent/update-script/
    Auth: Authorization: Bearer <token_hash>

    Query params:
        type       — ``service`` ou ``tray``
        version_id — PK da AgentVersion alvo (deve estar ativa)

    Fluxo de hot-update:
        1. Agente detecta update disponível via /agent/update/
        2. Agente baixa novo .exe para ``<install_dir>\\<agent>_new.exe``
        3. Agente requisita este script passando type + version_id
        4. Agente salva o script em disco como ``gr_updater.ps1``
        5. Agente executa: ``powershell -WindowStyle Hidden -File gr_updater.ps1
               -NewExe <path_new> -CurrentExe <path_current>``
        6. Agente encerra imediatamente
        7. Script (processo independente) substitui o exe e reinicia o serviço/tray
        8. Script reporta resultado para /agent/update-report/
    """

    authentication_classes = []
    permission_classes = []

    _SERVICE_SCRIPT = """\
# GR Agent Hot-Updater — service
# Gerado automaticamente pelo GR-Colaboradores em {generated_at}
# Versao destino: {version}

param(
    [Parameter(Mandatory=$true)][string]$NewExe,
    [Parameter(Mandatory=$true)][string]$CurrentExe,
    [string]$ServiceName = "GRAgentService",
    [string]$ReportUrl   = "{report_url}",
    [string]$Token       = "{token_hash}"
)

$FromVersion = "{from_version}"
$ToVersion   = "{version}"

function Send-Report([string]$StatusVal, [string]$Msg) {{
    try {{
        $body = @{{
            status       = $StatusVal
            agent_type   = "service"
            machine_name = $env:COMPUTERNAME
            from_version = $FromVersion
            to_version_id = {version_id}
            message      = $Msg
        }} | ConvertTo-Json -Compress
        Invoke-WebRequest -Uri $ReportUrl -Method POST -Body $body `
            -ContentType "application/json" `
            -Headers @{{ Authorization = "Bearer $Token" }} `
            -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop | Out-Null
    }} catch {{}}
}}

try {{
    Send-Report "downloading" "Launcher iniciado, aguardando parada do servico"
    Start-Sleep -Seconds 3

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne "Stopped") {{
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        Start-Sleep -Seconds 3
    }}

    Copy-Item -Path $NewExe -Destination $CurrentExe -Force -ErrorAction Stop

    Start-Service -Name $ServiceName -ErrorAction Stop

    Send-Report "applied" "Servico atualizado para v$ToVersion e reiniciado"
}} catch {{
    $errMsg = $_.Exception.Message
    Send-Report "failed" $errMsg
    # Tenta reiniciar com a versao anterior se o novo exe falhou
    try {{
        Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
    }} catch {{}}
}} finally {{
    Remove-Item -Path $NewExe -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}}
"""

    _TRAY_SCRIPT = """\
# GR Agent Hot-Updater — tray
# Gerado automaticamente pelo GR-Colaboradores em {generated_at}
# Versao destino: {version}

param(
    [Parameter(Mandatory=$true)][string]$NewExe,
    [Parameter(Mandatory=$true)][string]$CurrentExe,
    [string]$ReportUrl = "{report_url}",
    [string]$Token     = "{token_hash}"
)

$FromVersion = "{from_version}"
$ToVersion   = "{version}"

function Send-Report([string]$StatusVal, [string]$Msg) {{
    try {{
        $body = @{{
            status        = $StatusVal
            agent_type    = "tray"
            machine_name  = $env:COMPUTERNAME
            from_version  = $FromVersion
            to_version_id = {version_id}
            message       = $Msg
        }} | ConvertTo-Json -Compress
        Invoke-WebRequest -Uri $ReportUrl -Method POST -Body $body `
            -ContentType "application/json" `
            -Headers @{{ Authorization = "Bearer $Token" }} `
            -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop | Out-Null
    }} catch {{}}
}}

try {{
    Send-Report "downloading" "Launcher iniciado, encerrando processo tray"
    Start-Sleep -Seconds 3

    # Encerra qualquer processo usando o exe atual
    Get-Process -ErrorAction SilentlyContinue | `
        Where-Object {{ $_.Path -and ($_.Path -ieq $CurrentExe) }} | `
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    Copy-Item -Path $NewExe -Destination $CurrentExe -Force -ErrorAction Stop

    # Reinicia a bandeja como processo oculto do usuario atual
    Start-Process -FilePath $CurrentExe -WindowStyle Hidden

    Send-Report "applied" "Tray atualizado para v$ToVersion e reiniciado"
}} catch {{
    $errMsg = $_.Exception.Message
    Send-Report "failed" $errMsg
    # Tenta reiniciar com a versao anterior
    try {{
        if (Test-Path $CurrentExe) {{
            Start-Process -FilePath $CurrentExe -WindowStyle Hidden -ErrorAction SilentlyContinue
        }}
    }} catch {{}}
}} finally {{
    Remove-Item -Path $NewExe -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}}
"""

    def get(self, request):
        """Gera o script PowerShell parametrizado para hot-update."""
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        agent_type = request.query_params.get("type", "").strip().lower()
        version_id = request.query_params.get("version_id", "").strip()

        if agent_type not in ("service", "tray"):
            return Response(
                {"error": "Parâmetro 'type' inválido. Use 'service' ou 'tray'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not version_id.isdigit():
            return Response(
                {"error": "Parâmetro 'version_id' inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        version_obj = AgentVersion.objects.filter(
            pk=int(version_id), agent_type=agent_type, is_active=True
        ).first()
        if not version_obj:
            return Response(
                {"error": "Versão não encontrada ou inativa."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Descobre a versão corrente da máquina a partir do último download log
        machine_name = self._get_machine_name(request)
        last_log = (
            AgentDownloadLog.objects
            .filter(machine_name=machine_name, agent_version__agent_type=agent_type)
            .order_by("-downloaded_at")
            .select_related("agent_version")
            .first()
        )
        from_version = last_log.agent_version.version if last_log else "desconhecida"

        report_url  = request.build_absolute_uri("/api/inventario/agent/update-report/")
        token_hash  = agent_token.token_hash
        generated_at = timezone.now().strftime("%d/%m/%Y %H:%M")

        template = self._SERVICE_SCRIPT if agent_type == "service" else self._TRAY_SCRIPT
        script = template.format(
            version      = version_obj.version,
            version_id   = version_obj.pk,
            from_version = from_version,
            report_url   = report_url,
            token_hash   = token_hash,
            generated_at = generated_at,
        )

        response = HttpResponse(script, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="gr_updater_{agent_type}.ps1"'
        return response


@method_decorator(csrf_exempt, name='dispatch')
class AgentUpdateReportAPIView(AgentTokenRequiredMixin, APIView):
    """
    Recebe relatório de resultado de atualização enviado pelo script launcher.

    Endpoint: POST /api/inventario/agent/update-report/
    Auth: Authorization: Bearer <token_hash>

    Body::

        {
            "status":        "applied",        # downloading | ready | applied | failed | rolled_back
            "agent_type":    "service",
            "machine_name":  "PC-NOME",        # opcional, usa X-Machine-Name se ausente
            "from_version":  "3.1.0",
            "to_version_id": 42,               # PK da AgentVersion destino
            "message":       "..."             # detalhes / mensagem de erro
        }
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """Registra o resultado do hot-update."""
        agent_token, error_response = self._authenticate(request)
        if error_response:
            return error_response

        status_val   = request.data.get("status", "").strip()
        agent_type   = request.data.get("agent_type", "").strip().lower()
        machine_name = (request.data.get("machine_name") or self._get_machine_name(request) or "").strip()
        from_version = request.data.get("from_version", "").strip()
        to_version_id = request.data.get("to_version_id")
        message      = request.data.get("message", "").strip()

        valid_statuses = [s[0] for s in AgentUpdateReport.STATUS_CHOICES]
        if status_val not in valid_statuses:
            return Response(
                {"error": f"Status inválido. Valores aceitos: {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        version_obj = None
        if to_version_id:
            version_obj = AgentVersion.objects.filter(pk=to_version_id).first()

        AgentUpdateReport.objects.create(
            machine_name = machine_name,
            agent_type   = agent_type,
            from_version = from_version,
            to_version   = version_obj,
            status       = status_val,
            message      = message,
        )

        logger.info(
            "UpdateReport | máquina=%s tipo=%s %s→%s status=%s",
            machine_name, agent_type, from_version,
            version_obj.version if version_obj else "?", status_val,
        )

        return Response({"ok": True, "message": "Relatório registrado."})


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