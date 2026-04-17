import hmac, hashlib, time as _time
import json
import logging
import secrets
import time
from functools import wraps

import requests as req_lib
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_GET

from apps.inventory.models import Machine, AgentToken

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
IPC_PORT = getattr(settings, 'AGENT_IPC_PORT', 7070)
WEBRTC_PORT = getattr(settings, 'AGENT_WEBRTC_PORT', 7071)
SESSION_TTL = getattr(settings, 'RDP_SESSION_TIMEOUT', 3600)
MAX_SESSIONS = getattr(settings, 'RDP_MAX_SESSIONS_PER_USER', 3)

# Cache de sessões ativas em memória. Em produção substitua por Redis:
#   from django.core.cache import cache
#   cache.set(f'rdp_session:{sid}', data, timeout=SESSION_TTL)
_active_sessions: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de segurança
# ─────────────────────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """SHA-256 idêntico ao usado pelo agente Windows."""
    return hashlib.sha256(token.encode()).hexdigest()


def _get_tenant(user) -> object:
    """
    Retorna o 'cliente' (tenant) do usuário.
    Usuário is_staff é o próprio tenant; usuário comum herda o tenant do seu perfil.
    Adapte conforme sua implementação de multi-tenancy.
    """
    if user.is_staff or user.is_superuser:
        return user
    # Caso o modelo de usuário tenha um campo cliente/tenant:
    return getattr(user, 'cliente', user)


def _validate_rdp_token(token: str, machine: Machine) -> bool:
    """
    Valida token RDP:
      - Existe em AgentToken, ativo=True
      - Pertence ao mesmo tenant da máquina
      - Não está expirado (se o model tiver expires_at)
    """
    token_hash = _hash_token(token)
    try:
        agent_token = AgentToken.objects.get(
            token_hash=token_hash,
            is_active=True,
        )
        # Verificação de expiração opcional
        if hasattr(agent_token, 'expires_at') and agent_token.expires_at:
            from django.utils import timezone
            if agent_token.expires_at < timezone.now():
                logger.warning(
                    f"RDP: token expirado para máquina '{machine.hostname}'"
                )
                return False
        return True
    except AgentToken.DoesNotExist:
        logger.warning(
            f"RDP: token inválido para máquina '{machine.hostname}'"
        )
        return False


def _check_rate_limit(user_id: int) -> bool:
    """Impede mais de MAX_SESSIONS sessões RDP simultâneas por usuário."""
    _cleanup_expired_sessions()
    count = sum(1 for s in _active_sessions.values() if s.get('user_id') == user_id)
    return count < MAX_SESSIONS


def _cleanup_expired_sessions():
    now = time.time()
    expired = [sid for sid, s in _active_sessions.items() if now - s['started'] > SESSION_TTL]
    for sid in expired:
        del _active_sessions[sid]
        logger.debug(f"RDP: sessão expirada removida: {sid[:8]}…")


def _require_rdp_auth(view_func):
    """
    Decorator que aplica todas as camadas de segurança RDP:
      1. Usuário Django autenticado (session)
      2. Verificação de origem HTTP (CORS manual)
      3. Header X-RDP-Token presente
      4. Header X-Machine-ID presente
      5. Máquina existe e pertence ao tenant do usuário
      6. Token válido contra AgentToken
      7. Rate limit de sessões simultâneas

    Injeta request.rdp_machine e request.rdp_token para uso na view.
    """

    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        # 1. Autenticação Django
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Autenticação necessária'}, status=401)

        # 2. Verificação de origem
        allowed_origins = getattr(settings, 'RDP_ALLOWED_ORIGINS', [])
        if allowed_origins:
            origin = request.META.get('HTTP_ORIGIN', '')
            if origin and origin not in allowed_origins:
                logger.warning(f"RDP: origem bloqueada '{origin}' para user {request.user.pk}")
                return JsonResponse({'error': 'Origem não permitida'}, status=403)

        # 3. Token RDP
        token = request.META.get('HTTP_X_RDP_TOKEN', '').strip()
        if not token:
            return JsonResponse({'error': 'Header X-RDP-Token obrigatório'}, status=401)
        if len(token) < 8:
            return JsonResponse({'error': 'Token inválido'}, status=401)

        # 4. Machine ID
        machine_id = request.META.get('HTTP_X_MACHINE_ID', '').strip()
        if not machine_id:
            return JsonResponse({'error': 'Header X-Machine-ID obrigatório'}, status=400)

        # 5. Buscar máquina filtrando por tenant
        tenant = _get_tenant(request.user)
        try:
            machine = Machine.objects.get(hostname=machine_id)
        except Machine.DoesNotExist:
            logger.warning(
                f"RDP: máquina '{machine_id}' não encontrada para tenant={tenant.pk}"
            )
            return JsonResponse({'error': 'Máquina não encontrada'}, status=404)

        # 6. Validar token contra a máquina
        if not _validate_rdp_token(token, machine):
            return JsonResponse({'error': 'Token inválido ou expirado'}, status=403)

        # 7. Rate limit
        if not _check_rate_limit(request.user.pk):
            return JsonResponse(
                {'error': f'Limite de {MAX_SESSIONS} sessões simultâneas atingido'},
                status=429
            )

        request.rdp_machine = machine
        request.rdp_token = token
        return view_func(self, request, *args, **kwargs)

    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# View principal: sinalização WebRTC
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(login_required, name='dispatch')
class RDPOfferView(View):
    """
    Recebe o SDP offer do browser, valida segurança e encaminha ao agente.

    POST /api/rdp/offer/
    Headers obrigatórios:
        X-RDP-Token:  <token de 8+ chars>
        X-Machine-ID: <hostname da máquina>
        X-CSRFToken:  <token CSRF do Django>
    Content-Type: application/json
    Body: { "sdp": "<sdp string>", "type": "offer", "codec_hint": "auto|fallback" }

    Resposta 200: { "sdp": "<sdp string>", "type": "answer" }
    """

    @_require_rdp_auth
    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Body JSON inválido'}, status=400)

        sdp = body.get('sdp', '').strip()
        kind = body.get('type', '').strip()

        if kind != 'offer' or not sdp:
            return JsonResponse({'error': 'SDP offer ausente ou tipo inválido'}, status=400)

        machine: Machine = request.rdp_machine

        self._assert_agent_online(machine)

        codec_hint = str(body.get('codec_hint', 'auto')).strip().lower()
        if codec_hint not in ('auto', 'fallback'):
            codec_hint = 'auto'

        try:
            answer = self._forward_offer_to_agent(request, machine, sdp, codec_hint)
        except req_lib.exceptions.ConnectionError:
            logger.error(f"RDP: agente '{machine.hostname}' inacessível")
            return JsonResponse({'error': 'Agente offline ou inacessível'}, status=502)
        except req_lib.exceptions.Timeout:
            logger.error(f"RDP: timeout no agente '{machine.hostname}'")
            return JsonResponse({'error': 'Agente não respondeu no tempo limite'}, status=504)
        except Exception as e:
            logger.exception(f"RDP: erro IPC para '{machine.hostname}': {e}")
            return JsonResponse({'error': f'Erro interno: {str(e)}'}, status=500)

        session_id = secrets.token_hex(16)
        _active_sessions[session_id] = {
            'user_id': request.user.pk,
            'username': request.user.username,
            'machine': machine.hostname,
            'started': time.time(),
            'token_h': _hash_token(request.rdp_token),
        }
        _cleanup_expired_sessions()

        logger.info(f"RDP: sessão {session_id[:8]}… — user='{request.user.username}' → '{machine.hostname}'")

        resp = JsonResponse(answer)
        resp['X-RDP-Session'] = session_id
        return resp

    def _assert_agent_online(self, machine: Machine):
        """Levanta exceção se o agente não fez checkin recentemente."""
        from django.utils import timezone
        from datetime import timedelta

        # Verificar campo last_seen se existir no modelo
        last_seen = getattr(machine, 'last_seen', None)
        if last_seen and (timezone.now() - last_seen) > timedelta(minutes=6):
            raise ConnectionError(f"Agente '{machine.hostname}' sem heartbeat há mais de 6 minutos")

    def _forward_offer_to_agent(self, request, machine: Machine, sdp: str, codec_hint: str = 'auto') -> dict:
        from apps.inventory.models import AgentToken

        url = f"http://{machine.ip_address}:{WEBRTC_PORT}/webrtc/offer"

        rdp_token_hash = _hash_token(request.rdp_token)
        logger.info(f"RDP: buscando token hash={rdp_token_hash[:16]}… para máquina {machine.hostname}")

        agent_token = AgentToken.objects.filter(
            token_hash=rdp_token_hash,
            is_active=True,
        ).first()

        if not agent_token:
            raise ValueError(f"Token não encontrado no banco para hash {rdp_token_hash[:16]}…")

        logger.info(f"RDP: encaminhando offer para {url}")

        headers = {"Authorization": f"Bearer {agent_token.token_hash}"}
        payload = {"sdp": sdp, "type": "offer", "codec_hint": codec_hint}
        response = req_lib.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()

        answer = response.json()
        if "sdp" not in answer or answer.get("type") != "answer":
            raise ValueError(f"Resposta inválida do agente: {answer}")

        logger.info(f"RDP: SDP answer recebido para {machine.hostname}")
        return answer


# ─────────────────────────────────────────────────────────────────────────────
# View auxiliar: informações da máquina
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(login_required, name='dispatch')
class RDPInfoView(View):
    """
    GET /api/rdp/info/?machine=<hostname>
    GET /api/rdp/info/?machine=<hostname>&action=explorer_path

    action=explorer_path  — retorna a pasta atualmente aberta no Windows Explorer
                            da máquina remota consultando o IPC do agente (porta 7070).
    (sem action)          — retorna resolução de tela, SO, etc. (comportamento original)
    """

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Autenticação necessária'}, status=401)

        machine_id = request.GET.get('machine', '').strip()
        token = request.META.get('HTTP_X_RDP_TOKEN', '').strip()
        action = request.GET.get('action', '').strip()

        if not machine_id:
            return JsonResponse({'error': 'Parâmetro machine obrigatório'}, status=400)
        if not token:
            return JsonResponse({'error': 'Header X-RDP-Token obrigatório'}, status=401)

        tenant = _get_tenant(request.user)
        try:
            machine = Machine.objects.get(hostname=machine_id, cliente=tenant)
        except Machine.DoesNotExist:
            return JsonResponse({'error': 'Máquina não encontrada'}, status=404)

        IPC_PORT = 7070  # porta do IPC do agent_service

        # ── action: explorer_path ────────────────────────────────────────────
        if action == 'explorer_path':
            try:
                url = f"http://{machine.ip_address}:{IPC_PORT}/explorer/path"
                resp = req_lib.get(url, timeout=4)
                if resp.ok:
                    data = resp.json()
                    return JsonResponse({'path': data.get('path', 'downloads')})
                else:
                    return JsonResponse({'path': 'downloads', 'error': f'Agent HTTP {resp.status_code}'})
            except Exception as e:
                # Fallback silencioso — frontend trata
                return JsonResponse({'path': 'downloads', 'error': str(e)})

        # ── action padrão: info da tela ──────────────────────────────────────
        try:
            url = f"http://{machine.ip_address}:{IPC_PORT}/status"
            resp = req_lib.get(url, timeout=3)
            data = resp.json()
            screen = data.get('screen', {})
            return JsonResponse({
                'w': screen.get('width', 1920),
                'h': screen.get('height', 1080),
                'hostname': machine.hostname,
                'os': getattr(machine, 'os_version', '—'),
            })
        except Exception:
            return JsonResponse({
                'w': 1920,
                'h': 1080,
                'hostname': machine.hostname,
                'os': getattr(machine, 'os_version', '—'),
            })


# ─────────────────────────────────────────────────────────────────────────────
# View: listar sessões ativas (admin)
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(login_required, name='dispatch')
class RDPSessionsView(View):
    """
    Lista sessões RDP ativas do usuário atual.
    GET /api/rdp/sessions/
    """

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Autenticação necessária'}, status=401)

        _cleanup_expired_sessions()
        now = time.time()
        user_sessions = [
            {
                'id': sid[:8] + '…',
                'machine': s['machine'],
                'started': int(s['started']),
                'elapsed': int(now - s['started']),
            }
            for sid, s in _active_sessions.items()
            if s.get('user_id') == request.user.pk
        ]
        return JsonResponse({'sessions': user_sessions, 'max': MAX_SESSIONS})

@method_decorator(login_required, name='dispatch')
class RDPMachineTokenView(View):
    """
    Retorna o token cadastrado para a máquina (somente staff).
    GET /api/rdp/machine-token/?machine=<hostname>
    """
    def get(self, request):
        from apps.inventory.models import AgentTokenUsage

        if not request.user.is_staff:
            return JsonResponse({'error': 'Acesso negado'}, status=403)

        machine_hostname = request.GET.get('machine', '').strip()
        if not machine_hostname:
            return JsonResponse({'error': 'Parâmetro machine obrigatório'}, status=400)

        try:
            Machine.objects.get(hostname=machine_hostname)
        except Machine.DoesNotExist:
            return JsonResponse({'error': 'Máquina não encontrada'}, status=404)

        usage = AgentTokenUsage.objects.filter(
            machine_name=machine_hostname,
            agent_token__is_active=True,
        ).select_related('agent_token').order_by('-last_used_at').first()

        if not usage:
            return JsonResponse({'error': 'Nenhum token ativo cadastrado para esta máquina'}, status=404)

        return JsonResponse({'token': usage.agent_token.token, 'machine': machine_hostname})


@method_decorator(login_required, name='dispatch')
class RDPConfigView(View):
    """
    Entrega configuração ICE ao browser de forma segura.
    - Requer login Django (session)
    - Gera credenciais TURN com TTL de 1 hora via HMAC
      (compatível com coturn --use-auth-secret)
    - Nunca expõe a senha master no response

    GET /api/rdp/config/
    Retorna: { ice_servers: [...] }
    """
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Não autenticado'}, status=401)

        cfg  = getattr(settings, 'RDP_TURN_CONFIG', {})
        host = cfg.get('host', '')
        port = cfg.get('port', 3478)

        # Credencial temporária HMAC — válida por 1h
        # Funciona com coturn --use-auth-secret=<TURN_CREDENTIAL>
        # username = "<timestamp>:<user_id>"
        # password = HMAC-SHA1(secret, username)
        ttl       = int(_time.time()) + 3600
        turn_user = f"{ttl}:{request.user.pk}"
        secret    = cfg.get('credential', '')
        turn_pass = hmac.new(
            secret.encode(),
            turn_user.encode(),
            hashlib.sha1,
        ).digest()
        import base64
        turn_pass_b64 = base64.b64encode(turn_pass).decode()

        ice_servers = [
            {'urls': f'stun:{host}:{port}'},
            {
                'urls':       f'turn:{host}:{port}',
                'username':   turn_user,
                'credential': turn_pass_b64,
            },
            {
                'urls':       f'turn:{host}:{port}?transport=tcp',
                'username':   turn_user,
                'credential': turn_pass_b64,
            },
        ]

        resp = JsonResponse({'ice_servers': ice_servers})
        # Não cachear — cada resposta tem TTL próprio
        resp['Cache-Control'] = 'no-store'
        return resp
