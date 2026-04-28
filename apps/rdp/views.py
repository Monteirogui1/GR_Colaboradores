import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import time
from functools import wraps

import requests as req_lib
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View

from apps.inventory.models import AgentTokenUsage, Machine
from apps.rdp.models import RDPMachinePolicy, RDPSessionAudit, RDPSessionToken

logger = logging.getLogger(__name__)

IPC_PORT = getattr(settings, "AGENT_IPC_PORT", 7070)
WEBRTC_PORT = getattr(settings, "AGENT_WEBRTC_PORT", 7071)
SESSION_TTL = getattr(settings, "RDP_SESSION_TIMEOUT", 3600)
MAX_SESSIONS = getattr(settings, "RDP_MAX_SESSIONS_PER_USER", 3)
SESSION_TOKEN_TTL = getattr(settings, "RDP_SESSION_TOKEN_TTL", 120)
SIGNAL_WAIT_TIMEOUT = getattr(settings, "RDP_SIGNAL_WAIT_TIMEOUT", 12)
ENABLE_REVERSE_SIGNAL = getattr(settings, "RDP_ENABLE_REVERSE_SIGNAL", True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _active_session_key(session_id: str) -> str:
    return f"rdp:session:{session_id}"


def _active_user_index_key(user_id: int) -> str:
    return f"rdp:user:{user_id}:sessions"


def _signal_offer_key(machine_name: str) -> str:
    return f"rdp:signal:offer:{machine_name}"


def _signal_answer_key(request_id: str) -> str:
    return f"rdp:signal:answer:{request_id}"


def _agent_best_ip_key(machine_name: str, purpose: str) -> str:
    return f"inventory:agent:best-ip:{purpose}:{machine_name.lower()}"


def _remember_best_ip(machine: Machine, purpose: str, ip: str) -> None:
    if ip:
        cache.set(_agent_best_ip_key(machine.hostname, purpose), ip, timeout=3600)


def _get_best_ip(machine: Machine, purpose: str) -> str:
    return cache.get(_agent_best_ip_key(machine.hostname, purpose), "") or ""


def _get_client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _extract_ipv4_values(value) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple, set)) else re.split(r"[,;\s]+", str(value))
    ips = []
    for raw in raw_values:
        candidate = str(raw).strip().strip("[]")
        if not candidate:
            continue
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if ip.version != 4:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            continue
        ips.append(str(ip))
    return ips


def _machine_ip_candidates(machine: Machine) -> list[str]:
    candidates = []

    def add(value):
        for ip in _extract_ipv4_values(value):
            if ip not in candidates:
                candidates.append(ip)

    add(getattr(machine, "ip_address", ""))
    network_info = getattr(machine, "network_info", None)
    if isinstance(network_info, list):
        for adapter in network_info:
            if isinstance(adapter, dict):
                add(adapter.get("ip"))
                add(adapter.get("ip_address"))
                add(adapter.get("ips"))
    elif isinstance(network_info, dict):
        add(network_info.get("ip"))
        add(network_info.get("ip_address"))
        add(network_info.get("ips"))
        adapters = network_info.get("adapters")
        if isinstance(adapters, list):
            for adapter in adapters:
                if isinstance(adapter, dict):
                    add(adapter.get("ip"))
                    add(adapter.get("ip_address"))
                    add(adapter.get("ips"))
    return candidates


def _ordered_ip_candidates(machine: Machine, purpose: str) -> list[str]:
    candidates = _machine_ip_candidates(machine)
    best_ip = _get_best_ip(machine, purpose)
    if best_ip and best_ip in candidates:
        candidates.remove(best_ip)
        candidates.insert(0, best_ip)
    return candidates


def _agent_get(machine: Machine, path: str, headers: dict | None = None, timeout: int = 4):
    last_error = None
    connect_timeout = float(getattr(settings, "AGENT_DIRECT_CONNECT_TIMEOUT", 1.0))
    for ip in _ordered_ip_candidates(machine, "rdp"):
        try:
            resp = req_lib.get(f"http://{ip}:{WEBRTC_PORT}{path}", headers=headers or {}, timeout=(connect_timeout, timeout))
            _remember_best_ip(machine, "rdp", ip)
            return resp
        except (req_lib.exceptions.ConnectionError, req_lib.exceptions.Timeout) as exc:
            last_error = exc
            continue
    raise req_lib.exceptions.ConnectionError("Agente inacessível nos IPs candidatos") from last_error


def _audit(event_type: str, request, machine: Machine, session_token=None, session_id: str = "", reason: str = "", mode: str = "auto"):
    try:
        RDPSessionAudit.objects.create(
            event_type=event_type,
            user=request.user,
            machine=machine,
            session_token=session_token,
            session_id=session_id,
            reason=(reason or "")[:255],
            connection_mode=mode or RDPMachinePolicy.MODE_AUTO,
            client_ip=_get_client_ip(request),
        )
    except Exception as exc:
        logger.warning("RDP audit falhou: %s", exc)


def _is_origin_allowed(request) -> bool:
    allowed_origins = getattr(settings, "RDP_ALLOWED_ORIGINS", [])
    if not allowed_origins:
        return True
    origin = request.META.get("HTTP_ORIGIN", "")
    return not origin or origin in allowed_origins


def _resolve_machine_policy(machine: Machine) -> RDPMachinePolicy:
    policy = getattr(machine, "rdp_policy", None)
    if policy:
        return policy
    return RDPMachinePolicy(
        machine=machine,
        connection_mode=_sanitize_mode(getattr(settings, "RDP_DEFAULT_CONNECTION_MODE", RDPMachinePolicy.MODE_AUTO)),
        default_quality=_sanitize_quality(getattr(settings, "RDP_DEFAULT_QUALITY", RDPMachinePolicy.QUALITY_AUTO)),
        allow_elevated_input=True,
        require_justification=bool(getattr(settings, "RDP_REQUIRE_JUSTIFICATION", True)),
        silent_access_only=bool(getattr(settings, "RDP_SILENT_ACCESS_ONLY", True)),
    )


def _sanitize_mode(mode: str) -> str:
    val = (mode or "").strip().lower()
    if val in {RDPMachinePolicy.MODE_AUTO, RDPMachinePolicy.MODE_P2P_ONLY, RDPMachinePolicy.MODE_RELAY_ONLY}:
        return val
    return RDPMachinePolicy.MODE_AUTO


def _sanitize_quality(quality: str) -> str:
    val = (quality or "").strip().lower()
    if val in {"auto", "high", "medium", "low"}:
        return val
    return "auto"


def _get_online_agent_token(machine: Machine):
    usage = (
        AgentTokenUsage.objects.filter(
            machine_name=machine.hostname,
            agent_token__is_active=True,
            agent_token__expires_at__gt=timezone.now(),
        )
        .select_related("agent_token")
        .order_by("-last_used_at")
        .first()
    )
    return usage.agent_token if usage else None


def _validate_agent_signal_auth(request, machine_name: str):
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return None
    token_hash = auth[7:].strip()
    if len(token_hash) != 64:
        return None
    usage = (
        AgentTokenUsage.objects.filter(
            machine_name=machine_name,
            agent_token__token_hash=token_hash,
            agent_token__is_active=True,
            agent_token__expires_at__gt=timezone.now(),
        )
        .select_related("agent_token")
        .first()
    )
    return usage.agent_token if usage else None


def _validate_session_token(token: str, machine: Machine, user) -> RDPSessionToken | None:
    token_hash = _sha256(token)
    obj = (
        RDPSessionToken.objects.select_related("agent_token", "machine", "created_by")
        .filter(
            token_hash=token_hash,
            machine=machine,
            created_by=user,
            is_active=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if not obj:
        return None
    if not hmac.compare_digest(obj.token_hash, token_hash):
        return None
    return obj


def _list_user_session_ids(user_id: int) -> list[str]:
    ids = cache.get(_active_user_index_key(user_id), [])
    valid = []
    for sid in ids:
        if cache.get(_active_session_key(sid)):
            valid.append(sid)
    cache.set(_active_user_index_key(user_id), valid, timeout=SESSION_TTL)
    return valid


def _check_rate_limit(user_id: int) -> bool:
    return len(_list_user_session_ids(user_id)) < MAX_SESSIONS


def _register_session(user, machine: Machine, session_token: RDPSessionToken) -> str:
    session_id = secrets.token_hex(16)
    now = int(time.time())
    cache.set(
        _active_session_key(session_id),
        {
            "user_id": user.pk,
            "username": user.username,
            "machine": machine.hostname,
            "started": now,
            "session_token_id": session_token.pk,
            "mode": session_token.requested_mode,
            "quality": session_token.requested_quality,
            "reason": session_token.reason,
        },
        timeout=SESSION_TTL,
    )
    user_sessions = _list_user_session_ids(user.pk)
    user_sessions.append(session_id)
    cache.set(_active_user_index_key(user.pk), user_sessions, timeout=SESSION_TTL)
    return session_id


def _close_session(user_id: int, machine: str, session_id: str | None = None) -> list[dict]:
    closed = []
    for sid in _list_user_session_ids(user_id):
        if session_id and sid != session_id:
            continue
        data = cache.get(_active_session_key(sid)) or {}
        if data.get("machine") != machine:
            continue
        closed.append(data | {"id": sid})
        cache.delete(_active_session_key(sid))
    _list_user_session_ids(user_id)
    return closed


def _require_rdp_auth(view_func):
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Autenticação necessária"}, status=401)
        if not _is_origin_allowed(request):
            logger.warning("RDP origem bloqueada para user=%s", request.user.pk)
            return JsonResponse({"error": "Origem não permitida"}, status=403)

        token = request.META.get("HTTP_X_RDP_TOKEN", "").strip()
        machine_id = request.META.get("HTTP_X_MACHINE_ID", "").strip()
        if len(token) < 16:
            return JsonResponse({"error": "Header X-RDP-Token inválido"}, status=401)
        if not machine_id:
            return JsonResponse({"error": "Header X-Machine-ID obrigatório"}, status=400)

        machine = Machine.objects.filter(hostname=machine_id).first()
        if not machine:
            return JsonResponse({"error": "Máquina não encontrada"}, status=404)

        session_token = _validate_session_token(token, machine, request.user)
        if not session_token:
            return JsonResponse({"error": "Token de sessão inválido ou expirado"}, status=403)

        if not _check_rate_limit(request.user.pk):
            return JsonResponse(
                {"error": f"Limite de {MAX_SESSIONS} sessões simultâneas atingido"},
                status=429,
            )

        request.rdp_machine = machine
        request.rdp_policy = _resolve_machine_policy(machine)
        request.rdp_session_token = session_token
        return view_func(self, request, *args, **kwargs)

    return wrapper


@method_decorator(login_required, name="dispatch")
class RDPPolicyView(View):
    def get(self, request):
        machine_id = request.GET.get("machine", "").strip()
        if not machine_id:
            return JsonResponse({"error": "Parâmetro machine obrigatório"}, status=400)
        machine = Machine.objects.filter(hostname=machine_id).first()
        if not machine:
            return JsonResponse({"error": "Máquina não encontrada"}, status=404)
        policy = _resolve_machine_policy(machine)
        return JsonResponse(
            {
                "machine": machine.hostname,
                "connection_mode": policy.connection_mode,
                "default_quality": policy.default_quality,
                "allow_elevated_input": policy.allow_elevated_input,
                "require_justification": policy.require_justification,
                "silent_access_only": policy.silent_access_only,
            }
        )


@method_decorator(login_required, name="dispatch")
class RDPSessionTokenView(View):
    def post(self, request):
        if not request.user.is_staff:
            return JsonResponse({"error": "Acesso negado"}, status=403)

        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            body = {}

        machine_hostname = str(body.get("machine", "")).strip() or request.GET.get("machine", "").strip()
        reason = str(body.get("reason", "")).strip()
        mode = _sanitize_mode(str(body.get("connection_mode", "")).strip())
        quality = _sanitize_quality(str(body.get("quality", "")).strip())

        if not machine_hostname:
            return JsonResponse({"error": "Parâmetro machine obrigatório"}, status=400)

        machine = Machine.objects.filter(hostname=machine_hostname).first()
        if not machine:
            return JsonResponse({"error": "Máquina não encontrada"}, status=404)

        policy = _resolve_machine_policy(machine)
        if policy.require_justification and not reason:
            return JsonResponse({"error": "Justificativa obrigatória para acesso remoto"}, status=400)
        if mode == RDPMachinePolicy.MODE_AUTO:
            mode = policy.connection_mode
        if quality == "auto":
            quality = policy.default_quality

        agent_token = _get_online_agent_token(machine)
        if not agent_token:
            return JsonResponse({"error": "Máquina sem token de agente ativo"}, status=409)

        token, session_token = RDPSessionToken.issue(
            machine=machine,
            agent_token=agent_token,
            user=request.user,
            ttl_seconds=SESSION_TOKEN_TTL,
            reason=reason,
            requested_mode=mode,
            requested_quality=quality,
        )
        _audit(
            RDPSessionAudit.EVENT_TOKEN_ISSUED,
            request,
            machine,
            session_token=session_token,
            reason=reason,
            mode=mode,
        )
        return JsonResponse(
            {
                "token": token,
                "machine": machine.hostname,
                "expires_in": SESSION_TOKEN_TTL,
                "connection_mode": mode,
                "quality": quality,
                "silent_access_only": policy.silent_access_only,
            }
        )

    def get(self, request):
        return JsonResponse({"error": "Método não permitido"}, status=405)


@method_decorator(login_required, name="dispatch")
class RDPOfferView(View):
    @_require_rdp_auth
    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Body JSON inválido"}, status=400)

        sdp = str(body.get("sdp", "")).strip()
        kind = str(body.get("type", "")).strip()
        if kind != "offer" or not sdp:
            return JsonResponse({"error": "SDP offer ausente ou tipo inválido"}, status=400)

        machine: Machine = request.rdp_machine
        self._assert_agent_online(machine)

        codec_hint = str(body.get("codec_hint", request.rdp_session_token.requested_quality)).strip().lower()
        if codec_hint not in ("auto", "fallback"):
            codec_hint = "auto"

        try:
            answer = self._forward_offer_to_agent(request.rdp_session_token, machine, sdp, codec_hint)
        except req_lib.exceptions.ConnectionError:
            return JsonResponse({"error": "Agente offline ou inacessível"}, status=502)
        except req_lib.exceptions.Timeout:
            return JsonResponse({"error": "Agente não respondeu no tempo limite"}, status=504)
        except Exception as exc:
            logger.exception("RDP erro ao encaminhar offer: %s", exc)
            return JsonResponse({"error": f"Erro interno: {str(exc)}"}, status=500)

        session_id = _register_session(request.user, machine, request.rdp_session_token)
        if request.rdp_session_token.used_at is None:
            request.rdp_session_token.used_at = timezone.now()
            request.rdp_session_token.save(update_fields=["used_at"])
        _audit(
            RDPSessionAudit.EVENT_SESSION_STARTED,
            request,
            machine,
            session_token=request.rdp_session_token,
            session_id=session_id,
            reason=request.rdp_session_token.reason,
            mode=request.rdp_session_token.requested_mode,
        )

        resp = JsonResponse(answer)
        resp["X-RDP-Session"] = session_id
        return resp

    def _assert_agent_online(self, machine: Machine):
        last_seen = getattr(machine, "last_seen", None)
        if last_seen and (timezone.now() - last_seen).total_seconds() > 360:
            raise ConnectionError(f"Agente '{machine.hostname}' sem heartbeat recente")

    def _forward_offer_to_agent(
        self,
        session_token: RDPSessionToken,
        machine: Machine,
        sdp: str,
        codec_hint: str = "auto",
    ) -> dict:
        has_best_direct_ip = bool(_get_best_ip(machine, "rdp"))
        if ENABLE_REVERSE_SIGNAL and not has_best_direct_ip:
            answer = self._forward_offer_via_reverse_signal(session_token, machine, sdp, codec_hint)
            if answer is not None:
                return answer

        token_hash = session_token.agent_token.token_hash
        headers = {
            "Authorization": f"Bearer {token_hash}",
            "X-RDP-Connection-Mode": session_token.requested_mode,
            "X-RDP-Requested-Quality": session_token.requested_quality,
        }
        payload = {
            "sdp": sdp,
            "type": "offer",
            "codec_hint": codec_hint,
            "connection_mode": session_token.requested_mode,
            "quality": session_token.requested_quality,
        }
        last_error = None
        connect_timeout = float(getattr(settings, "AGENT_DIRECT_CONNECT_TIMEOUT", 1.0))
        for ip in _ordered_ip_candidates(machine, "rdp"):
            try:
                response = req_lib.post(
                    f"http://{ip}:{WEBRTC_PORT}/webrtc/offer",
                    json=payload,
                    headers=headers,
                    timeout=(connect_timeout, 15),
                )
                response.raise_for_status()
                answer = response.json()
                if "sdp" not in answer or answer.get("type") != "answer":
                    raise ValueError("Resposta inválida do agente")
                _remember_best_ip(machine, "rdp", ip)
                return answer
            except (req_lib.exceptions.ConnectionError, req_lib.exceptions.Timeout) as exc:
                last_error = exc
                continue
        if ENABLE_REVERSE_SIGNAL and has_best_direct_ip:
            answer = self._forward_offer_via_reverse_signal(session_token, machine, sdp, codec_hint)
            if answer is not None:
                return answer
        raise req_lib.exceptions.ConnectionError("Agente inacessível nos IPs candidatos") from last_error

    def _forward_offer_via_reverse_signal(
        self,
        session_token: RDPSessionToken,
        machine: Machine,
        sdp: str,
        codec_hint: str,
    ) -> dict | None:
        offer_key = _signal_offer_key(machine.hostname)
        if cache.get(offer_key):
            return None

        request_id = secrets.token_hex(12)
        payload = {
            "request_id": request_id,
            "machine": machine.hostname,
            "sdp": sdp,
            "type": "offer",
            "codec_hint": codec_hint,
            "connection_mode": session_token.requested_mode,
            "quality": session_token.requested_quality,
            "created_at": int(time.time()),
        }
        cache.set(offer_key, payload, timeout=SIGNAL_WAIT_TIMEOUT + 5)
        answer_key = _signal_answer_key(request_id)
        started = time.time()
        try:
            while time.time() - started < SIGNAL_WAIT_TIMEOUT:
                answer = cache.get(answer_key)
                if answer:
                    cache.delete(answer_key)
                    if "sdp" not in answer or answer.get("type") != "answer":
                        raise ValueError("Resposta inválida do agente (signal)")
                    return answer
                time.sleep(0.2)
        finally:
            cache.delete(offer_key)
        return None


@method_decorator(login_required, name="dispatch")
class RDPInfoView(View):
    def get(self, request):
        machine_id = request.GET.get("machine", "").strip()
        token = request.META.get("HTTP_X_RDP_TOKEN", "").strip()
        action = request.GET.get("action", "").strip()

        if not machine_id:
            return JsonResponse({"error": "Parâmetro machine obrigatório"}, status=400)
        machine = Machine.objects.filter(hostname=machine_id).first()
        if not machine:
            return JsonResponse({"error": "Máquina não encontrada"}, status=404)
        if not _validate_session_token(token, machine, request.user):
            return JsonResponse({"error": "Token de sessão inválido"}, status=403)

        agent_token = _get_online_agent_token(machine)
        agent_headers = {"Authorization": f"Bearer {agent_token.token_hash}"} if agent_token else {}

        if action == "explorer_path":
            try:
                resp = _agent_get(machine, "/explorer/path", headers=agent_headers, timeout=4)
                if resp.ok:
                    data = resp.json()
                    return JsonResponse({"path": data.get("path", "downloads")})
                return JsonResponse({"path": "downloads", "error": f"Agent HTTP {resp.status_code}"})
            except Exception as exc:
                return JsonResponse({"path": "downloads", "error": str(exc)})

        try:
            resp = _agent_get(machine, "/status", headers=agent_headers, timeout=3)
            data = resp.json() if resp.ok else {}
            screen = data.get("screen", {})
            return JsonResponse(
                {
                    "w": screen.get("width", 1920),
                    "h": screen.get("height", 1080),
                    "hostname": machine.hostname,
                    "os": getattr(machine, "os_version", "-"),
                    "allow_elevated_input": data.get("allow_elevated_input", True),
                }
            )
        except Exception:
            return JsonResponse(
                {
                    "w": 1920,
                    "h": 1080,
                    "hostname": machine.hostname,
                    "os": getattr(machine, "os_version", "-"),
                    "allow_elevated_input": True,
                }
            )


@method_decorator(login_required, name="dispatch")
class RDPCloseView(View):
    def post(self, request):
        machine_id = request.META.get("HTTP_X_MACHINE_ID", "").strip()
        token = request.META.get("HTTP_X_RDP_TOKEN", "").strip()
        session_id = request.META.get("HTTP_X_RDP_SESSION", "").strip()
        if not machine_id:
            return JsonResponse({"error": "Header X-Machine-ID obrigatório"}, status=400)

        machine = Machine.objects.filter(hostname=machine_id).first()
        if not machine:
            return JsonResponse({"error": "Máquina não encontrada"}, status=404)
        st = _validate_session_token(token, machine, request.user)
        if not st:
            return JsonResponse({"error": "Token de sessão inválido"}, status=403)

        closed = _close_session(request.user.pk, machine.hostname, session_id or None)
        for closed_item in closed:
            _audit(
                RDPSessionAudit.EVENT_SESSION_CLOSED,
                request,
                machine,
                session_token=st,
                session_id=closed_item.get("id", ""),
                reason=closed_item.get("reason", ""),
                mode=closed_item.get("mode", RDPMachinePolicy.MODE_AUTO),
            )
        return JsonResponse({"ok": True, "closed": len(closed)})


@method_decorator(login_required, name="dispatch")
class RDPSessionsView(View):
    def get(self, request):
        now = int(time.time())
        sessions = []
        for sid in _list_user_session_ids(request.user.pk):
            data = cache.get(_active_session_key(sid))
            if not data:
                continue
            sessions.append(
                {
                    "id": sid[:8] + "…",
                    "machine": data.get("machine", "-"),
                    "started": int(data.get("started", now)),
                    "elapsed": max(0, now - int(data.get("started", now))),
                    "mode": data.get("mode", RDPMachinePolicy.MODE_AUTO),
                    "quality": data.get("quality", RDPMachinePolicy.QUALITY_AUTO),
                }
            )
        return JsonResponse({"sessions": sessions, "max": MAX_SESSIONS})


class RDPConfigView(View):
    def get(self, request):
        machine_id = request.GET.get("machine", "").strip()
        agent_machine = request.META.get("HTTP_X_MACHINE_NAME", "").strip()
        is_agent = bool(agent_machine and _validate_agent_signal_auth(request, agent_machine))
        if not request.user.is_authenticated and not is_agent:
            return JsonResponse({"error": "Autenticação necessária"}, status=401)

        cfg = getattr(settings, "RDP_TURN_CONFIG", {})
        host = cfg.get("host", "")
        port = cfg.get("port", 3478)

        mode = _sanitize_mode(request.GET.get("mode", RDPMachinePolicy.MODE_AUTO))
        if not machine_id and is_agent:
            machine_id = agent_machine
        if machine_id:
            machine = Machine.objects.filter(hostname=machine_id).first()
            if machine:
                policy = _resolve_machine_policy(machine)
                if mode == RDPMachinePolicy.MODE_AUTO:
                    mode = policy.connection_mode

        ttl = int(time.time()) + 3600
        turn_identity = request.user.pk if request.user.is_authenticated else f"agent-{agent_machine}"
        turn_user = f"{ttl}:{turn_identity}"
        secret = cfg.get("credential", "")
        turn_pass = hmac.new(secret.encode(), turn_user.encode(), hashlib.sha1).digest()
        turn_pass_b64 = base64.b64encode(turn_pass).decode()

        tls_port = cfg.get("port_tls", 5349)
        tcp443_port = cfg.get("port_tcp443", 443)
        stun_server = {"urls": f"stun:{host}:{port}"}
        turn_servers = [
            {"urls": f"turn:{host}:{port}", "username": turn_user, "credential": turn_pass_b64},
            {
                "urls": f"turn:{host}:{port}?transport=tcp",
                "username": turn_user,
                "credential": turn_pass_b64,
            },
            {"urls": f"turns:{host}:{tls_port}", "username": turn_user, "credential": turn_pass_b64},
            {
                "urls": f"turns:{host}:{tls_port}?transport=tcp",
                "username": turn_user,
                "credential": turn_pass_b64,
            },
            {
                "urls": f"turns:{host}:{tcp443_port}?transport=tcp",
                "username": turn_user,
                "credential": turn_pass_b64,
            },
        ]

        if mode == RDPMachinePolicy.MODE_P2P_ONLY:
            ice_servers = [stun_server]
        elif mode == RDPMachinePolicy.MODE_RELAY_ONLY:
            ice_servers = turn_servers
        else:
            ice_servers = [stun_server] + turn_servers

        resp = JsonResponse({"ice_servers": ice_servers, "mode": mode})
        resp["Cache-Control"] = "no-store"
        return resp


@method_decorator(csrf_exempt, name="dispatch")
class RDPAgentSignalPullView(View):
    def post(self, request):
        machine_name = request.META.get("HTTP_X_MACHINE_NAME", "").strip()
        if not machine_name:
            return JsonResponse({"error": "X-Machine-Name obrigatório"}, status=400)
        if not _validate_agent_signal_auth(request, machine_name):
            return JsonResponse({"error": "Não autorizado"}, status=401)

        offer_key = _signal_offer_key(machine_name)
        offer = cache.get(offer_key)
        if not offer:
            return JsonResponse({"ok": True, "has_offer": False})

        cache.delete(offer_key)
        return JsonResponse({"ok": True, "has_offer": True, "offer": offer})


@method_decorator(csrf_exempt, name="dispatch")
class RDPAgentSignalAnswerView(View):
    def post(self, request):
        machine_name = request.META.get("HTTP_X_MACHINE_NAME", "").strip()
        if not machine_name:
            return JsonResponse({"error": "X-Machine-Name obrigatório"}, status=400)
        if not _validate_agent_signal_auth(request, machine_name):
            return JsonResponse({"error": "Não autorizado"}, status=401)

        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Body inválido"}, status=400)

        request_id = str(body.get("request_id", "")).strip()
        answer = body.get("answer")
        if not request_id or not isinstance(answer, dict):
            return JsonResponse({"error": "request_id/answer obrigatórios"}, status=400)
        cache.set(_signal_answer_key(request_id), answer, timeout=SIGNAL_WAIT_TIMEOUT + 5)
        return JsonResponse({"ok": True})
