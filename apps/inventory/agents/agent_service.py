"""
agent_service.py — Serviço Windows (Session 0)
Arquitetura v3 — TI Manager

Threads:
  • ipc          → HTTPServer 127.0.0.1:7070  (comunicação local com agent_tray)
  • webrtc-http  → HTTPServer 0.0.0.0:7071    (RDP offer + /command remoto do Django)
  • health       → heartbeat ao servidor Django
  • checkin      → inventário de hardware periódico
  • notif        → polling de notificações do servidor
  • update       → auto-update (opcional)
  • webrtc-gc    → limpeza de sessões WebRTC expiradas

Modificações v3.1:
  • IPCHandler agora só aceita 127.0.0.1 (local) OU o IP do servidor Django
    configurado em AGENT_DJANGO_SERVER_IP (env var).
  • WebRTCHandler ganhou endpoint POST /command para execução remota
    de comandos PowerShell/CMD pelo Django (sem WinRM).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import platform
import random
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

import requests

# ──────────────────────────────────────────────────────────────────────────────
# Dependências opcionais (WebRTC)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────
VERSION       = "3.1.0"
AGENT_TYPE    = "service"
IPC_PORT      = 7070
WEBRTC_PORT   = 7071

# IPs permitidos no IPC: sempre 127.0.0.1 + IP do servidor Django
DJANGO_SERVER_IP = os.environ.get("AGENT_DJANGO_SERVER_IP", "192.168.100.247")

# Subnet permitida no WebRTC handler (já existia)
WEBRTC_ALLOWED_SUBNET = os.environ.get("WEBRTC_ALLOWED_SUBNET", "192.168.100.0/24")

# Timeout máximo de comando remoto (segundos)
MAX_CMD_TIMEOUT = 120

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("agent_service")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers de configuração
# ──────────────────────────────────────────────────────────────────────────────
AgentConfig = Dict[str, Any]


def load_config() -> AgentConfig:
    """Carrega configuração a partir de variáveis de ambiente."""
    return {
        "server_url":    os.environ.get("AGENT_SERVER_URL",    "http://192.168.100.247:5002"),
        "token_hash":    os.environ.get("AGENT_TOKEN_HASH",    ""),
        "machine_name":  os.environ.get("COMPUTERNAME",        platform.node()),
        "auto_update":   os.environ.get("AGENT_AUTO_UPDATE",   "true").lower() == "true",
        "notifications": os.environ.get("AGENT_NOTIFICATIONS", "true").lower() == "true",
        # Endpoints
        "ep_checkin":    "/api/inventario/checkin/",
        "ep_notif":      "/api/notifications/",
        "ep_health":     "/api/inventario/health/",
        "ep_update":     "/api/inventario/agent/update/",
    }


def auth_headers(config: AgentConfig) -> dict:
    return {
        "Authorization":  f"Bearer {config['token_hash']}",
        "X-Machine-Name": config["machine_name"],
        "Content-Type":   "application/json",
    }


def ssl_verify(config: AgentConfig) -> bool:
    return config["server_url"].startswith("https://")


# ──────────────────────────────────────────────────────────────────────────────
# Estado global
# ──────────────────────────────────────────────────────────────────────────────
class AgentState:
    def __init__(self):
        self._lock           = threading.Lock()
        self._notifications: List[dict] = []
        self._shown_ids: set = set()
        self._webrtc_sessions: Dict[str, Any] = {}

    # ── notificações ──────────────────────────────────────────────────────────
    def push_notification(self, n: dict):
        with self._lock:
            if n.get("id") not in self._shown_ids:
                self._notifications.append(n)

    def pop_notifications(self) -> List[dict]:
        with self._lock:
            items = list(self._notifications)
            self._notifications.clear()
            return items

    def mark_shown(self, nid):
        with self._lock:
            self._shown_ids.add(nid)

    # ── WebRTC ────────────────────────────────────────────────────────────────
    def add_webrtc_session(self, sid: str, pc, track):
        with self._lock:
            self._webrtc_sessions[sid] = {"pc": pc, "track": track, "ts": time.time()}

    def remove_webrtc_session(self, sid: str):
        with self._lock:
            self._webrtc_sessions.pop(sid, None)

    def list_webrtc_sessions(self) -> List[str]:
        with self._lock:
            return list(self._webrtc_sessions.keys())

    @property
    def webrtc_sessions(self):
        return self._webrtc_sessions

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "version":         VERSION,
                "agent_type":      AGENT_TYPE,
                "machine":         os.environ.get("COMPUTERNAME", platform.node()),
                "webrtc_sessions": len(self._webrtc_sessions),
                "pending_notifs":  len(self._notifications),
                "ts":              datetime.now().isoformat(),
            }


STATE = AgentState()
_session = requests.Session()
_webrtc_data_channels: Dict[str, Any] = {}
_webrtc_dc_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
# Utilitários
# ──────────────────────────────────────────────────────────────────────────────
def get_explorer_path() -> str:
    """Retorna a pasta aberta no Windows Explorer (Session 1+)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(New-Object -ComObject Shell.Application).Windows() | "
             "Select-Object -ExpandProperty LocationURL -First 1"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
        )
        raw = result.stdout.strip()
        if raw.startswith("file:///"):
            raw = raw[8:].replace("/", "\\")
        return raw or "downloads"
    except Exception:
        return "downloads"


def collect_hardware(config: AgentConfig) -> dict:
    """Coleta informações de hardware via PowerShell / WMI."""
    if platform.system() != "Windows":
        return {"hostname": platform.node(), "os_version": platform.version()}

    ps_script = r"""
$out = @{}
$out.hostname   = $env:COMPUTERNAME
$out.os_version = (Get-WmiObject Win32_OperatingSystem).Caption
$out.cpu        = (Get-WmiObject Win32_Processor | Select -First 1).Name
$cs             = Get-WmiObject Win32_ComputerSystem
$out.ram_gb     = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
$out.model      = "$($cs.Manufacturer) $($cs.Model)".Trim()
$disk           = Get-WmiObject Win32_LogicalDisk -Filter "DriveType=3" | Select -First 1
$out.disk_total_gb = if ($disk) { [math]::Round($disk.Size / 1GB, 2) } else { 0 }
$out.disk_free_gb  = if ($disk) { [math]::Round($disk.FreeSpace / 1GB, 2) } else { 0 }
$out.mac_address   = (Get-WmiObject Win32_NetworkAdapterConfiguration | Where {$_.IPEnabled} | Select -First 1).MACAddress
$out.ip_address    = (Get-WmiObject Win32_NetworkAdapterConfiguration | Where {$_.IPEnabled} | Select -First 1).IPAddress[0]
$out.logged_user   = try { (Get-WmiObject Win32_ComputerSystem).UserName } catch { "" }
$out | ConvertTo-Json
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return json.loads(result.stdout)
    except Exception as e:
        logger.warning(f"collect_hardware falhou: {e}")
        return {"hostname": platform.node()}


# ──────────────────────────────────────────────────────────────────────────────
# Execução de comando (usado por IPC e WebRTC handlers)
# ──────────────────────────────────────────────────────────────────────────────
def run_command(body: dict) -> dict:
    """
    Executa um comando PowerShell ou CMD localmente (Session 0).
    Funciona sem agent_tray — não exibe UI, apenas captura stdout/stderr.

    Body esperado:
        type    : "powershell" | "cmd"  (default: powershell)
        script  : string com o comando
        timeout : int em segundos (max 120)
    """
    cmd_type = body.get("type", "powershell").lower()
    script   = body.get("script", "").strip()
    timeout  = min(int(body.get("timeout", 30)), MAX_CMD_TIMEOUT)

    if not script:
        return {"error": "script vazio", "stdout": "", "stderr": "", "exit_code": -1}

    try:
        if cmd_type == "powershell":
            cmd = [
                "powershell", "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", script,
            ]
        else:
            cmd = ["cmd", "/c", script]

        flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        proc  = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        return {
            "stdout":      proc.stdout,
            "stderr":      proc.stderr,
            "exit_code":   proc.returncode,
            "executed_at": datetime.now().isoformat(),
            "cmd_type":    cmd_type,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"timeout após {timeout}s", "stdout": "", "stderr": "", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "stdout": "", "stderr": "", "exit_code": -1}


# ──────────────────────────────────────────────────────────────────────────────
# IPC HTTP Server — 127.0.0.1:7070
# Comunicação local entre agent_service ↔ agent_tray
# + aceita chamadas do servidor Django (DJANGO_SERVER_IP)
# ──────────────────────────────────────────────────────────────────────────────
class IPCHandler(BaseHTTPRequestHandler):

    config: AgentConfig = None

    def log_message(self, fmt, *args):
        logger.debug(f"IPC {fmt % args}")

    def _send_json(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _is_allowed_origin(self) -> bool:
        """
        Permite apenas:
          • 127.0.0.1 → agent_tray local
          • DJANGO_SERVER_IP → servidor Django
        """
        client_ip = self.client_address[0]
        allowed = {"127.0.0.1", DJANGO_SERVER_IP}
        if client_ip not in allowed:
            logger.warning(f"IPC: origem bloqueada {client_ip}")
            return False
        return True

    def do_GET(self):
        if not self._is_allowed_origin():
            self._send_json(403, {"error": "Origem não permitida"})
            return

        if   self.path == "/status":          self._send_json(200, STATE.snapshot())
        elif self.path == "/notifications":   self._send_json(200, {"notifications": STATE.pop_notifications()})
        elif self.path == "/ping":            self._send_json(200, {"pong": True})
        elif self.path == "/webrtc/sessions": self._send_json(200, {"sessions": STATE.list_webrtc_sessions()})
        elif self.path == "/explorer/path":   self._send_json(200, {"path": get_explorer_path()})
        else:                                 self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._is_allowed_origin():
            self._send_json(403, {"error": "Origem não permitida"})
            return

        body = self._read_json()

        if self.path == "/notifications/ack":
            notif_id = body.get("id")
            if notif_id:
                STATE.mark_shown(notif_id)
                threading.Thread(
                    target=self._mark_django_read, args=(notif_id,), daemon=True
                ).start()
            self._send_json(200, {"ok": True})

        elif self.path == "/command":
            # Execução remota — funciona em Session 0 sem agent_tray
            self._send_json(200, run_command(body))

        elif self.path == "/sync":
            threading.Thread(
                target=_force_sync, args=(self.config,), daemon=True
            ).start()
            self._send_json(200, {"ok": True, "message": "sync triggered"})

        elif self.path == "/webrtc/close":
            session_id = body.get("session_id", "")
            if session_id:
                STATE.remove_webrtc_session(session_id)
                with _webrtc_dc_lock:
                    _webrtc_data_channels.pop(session_id, None)
                self._send_json(200, {"ok": True})
            else:
                self._send_json(400, {"error": "session_id obrigatório"})

        else:
            self._send_json(404, {"error": "not found"})

    def _mark_django_read(self, notif_id):
        try:
            url = self.config.get("server_url") + self.config.get("ep_notif")
            _session.post(
                url,
                json={"notification_id": notif_id},
                headers=auth_headers(self.config),
                verify=ssl_verify(self.config),
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"Falha ao marcar notif {notif_id}: {e}")


def start_ipc_server(config: AgentConfig):
    IPCHandler.config = config
    # IPC ainda escuta apenas no loopback — o Django usa o WebRTC handler (7071)
    # Se quiser chamar via IPC direto, descomente a linha abaixo e comente a seguinte:
    # server = HTTPServer(("0.0.0.0", IPC_PORT), IPCHandler)
    server = HTTPServer(("127.0.0.1", IPC_PORT), IPCHandler)
    logger.info(f"IPC server listening on 127.0.0.1:{IPC_PORT}")
    server.serve_forever()


# ──────────────────────────────────────────────────────────────────────────────
# WebRTC HTTP Server — 0.0.0.0:7071
# Acessível pela rede local → Django chama aqui para /command e /webrtc/offer
# ──────────────────────────────────────────────────────────────────────────────
class WebRTCHandler(BaseHTTPRequestHandler):

    config: AgentConfig = None

    def log_message(self, fmt, *args):
        logger.debug(f"WebRTC-HTTP {fmt % args}")

    def _send_json(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _check_subnet(self) -> bool:
        """Verifica se o IP do cliente está na subnet permitida."""
        try:
            client_ip = self.client_address[0]
            network   = ipaddress.ip_network(WEBRTC_ALLOWED_SUBNET, strict=False)
            return ipaddress.ip_address(client_ip) in network
        except Exception:
            return False

    def _check_auth(self) -> bool:
        """Verifica Bearer token no header Authorization."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return auth[7:].strip() == self.config.get("token_hash", "")

    def _guard(self) -> bool:
        if not self._check_subnet():
            self._send_json(403, {"error": "Origem não permitida"})
            return False
        if not self._check_auth():
            self._send_json(401, {"error": "Token inválido"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        if self.path == "/health":
            self._send_json(200, {
                "ok":              True,
                "version":         VERSION,
                "webrtc_sessions": len(STATE.webrtc_sessions),
                "ts":              datetime.now().isoformat(),
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._guard():
            return

        body = self._read_json()

        # ── /command — execução remota pelo Django (substitui WinRM) ──────────
        if self.path == "/command":
            """
            Body: { "type": "powershell"|"cmd", "script": "...", "timeout": 30 }
            Roda em Session 0 — sem UI, captura stdout/stderr.
            Não precisa do agent_tray.
            """
            logger.info(
                f"CMD remoto de {self.client_address[0]}: "
                f"[{body.get('type','ps')}] {body.get('script','')[:80]}"
            )
            result = run_command(body)
            self._send_json(200, result)

        # ── /webrtc/offer — negociação WebRTC para Remote Desktop ─────────────
        elif self.path == "/webrtc/offer":
            body_str = json.dumps(body)
            try:
                resp = _session.post(
                    "http://127.0.0.1:7071/webrtc/offer",
                    json=body,
                    timeout=15,
                )
                resp.raise_for_status()
                self._send_json(200, resp.json())
            except requests.exceptions.ConnectionError:
                self._send_json(503, {"error": "WebRTC local offline"})
            except requests.exceptions.Timeout:
                self._send_json(504, {"error": "WebRTC local não respondeu"})
            except Exception as e:
                self._send_json(500, {"error": f"Erro interno: {e}"})

        # ── /webrtc/close ─────────────────────────────────────────────────────
        elif self.path == "/webrtc/close":
            session_id = body.get("session_id", "")
            if session_id:
                try:
                    _session.post(
                        "http://127.0.0.1:7071/webrtc/close",
                        json=body, timeout=5,
                    )
                except Exception:
                    pass
                self._send_json(200, {"ok": True})
            else:
                self._send_json(400, {"error": "session_id obrigatório"})

        else:
            self._send_json(404, {"error": "not found"})


def start_webrtc_server(config: AgentConfig):
    WebRTCHandler.config = config
    server = HTTPServer(("0.0.0.0", WEBRTC_PORT), WebRTCHandler)
    logger.info(f"WebRTC-HTTP server listening on 0.0.0.0:{WEBRTC_PORT}")
    server.serve_forever()


# ──────────────────────────────────────────────────────────────────────────────
# Loops de background
# ──────────────────────────────────────────────────────────────────────────────
def _force_sync(config: AgentConfig):
    """Dispara um checkin imediato."""
    try:
        hw   = collect_hardware(config)
        url  = config["server_url"] + config["ep_checkin"]
        _session.post(
            url, json=hw,
            headers=auth_headers(config),
            verify=ssl_verify(config),
            timeout=15,
        )
        logger.info("Sync forçado concluído")
    except Exception as e:
        logger.warning(f"Sync forçado falhou: {e}")


def checkin_loop(config: AgentConfig):
    """Envia inventário de hardware periodicamente."""
    base_interval = 300  # 5 minutos
    while True:
        try:
            hw  = collect_hardware(config)
            url = config["server_url"] + config["ep_checkin"]
            r   = _session.post(
                url, json=hw,
                headers=auth_headers(config),
                verify=ssl_verify(config),
                timeout=20,
            )
            logger.info(f"Checkin: {r.status_code}")
        except Exception as e:
            logger.warning(f"Checkin falhou: {e}")

        # Jitter ±30s para evitar thundering herd
        time.sleep(base_interval + random.randint(-30, 30))


def health_loop(config: AgentConfig):
    """Heartbeat leve a cada 60s."""
    while True:
        try:
            url = config["server_url"] + config["ep_health"]
            _session.get(
                url,
                headers=auth_headers(config),
                verify=ssl_verify(config),
                timeout=10,
            )
        except Exception:
            pass
        time.sleep(60)


def notification_loop(config: AgentConfig):
    """Polling de notificações do servidor Django."""
    if not config.get("notifications"):
        return
    while True:
        try:
            url = config["server_url"] + config["ep_notif"]
            r   = _session.get(
                url,
                headers=auth_headers(config),
                verify=ssl_verify(config),
                timeout=10,
            )
            if r.status_code == 200:
                for notif in r.json().get("notifications", []):
                    STATE.push_notification(notif)
        except Exception as e:
            logger.debug(f"Notif poll falhou: {e}")
        time.sleep(30)


def update_loop(config: AgentConfig):
    """Verifica e aplica auto-update do agente."""
    if not config.get("auto_update"):
        return
    while True:
        try:
            url = config["server_url"] + config["ep_update"]
            r   = _session.post(
                url,
                json={"current_version": VERSION, "agent_type": AGENT_TYPE,
                      "machine_name": config["machine_name"]},
                headers=auth_headers(config),
                verify=ssl_verify(config),
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("update_available"):
                    _apply_update(config, data)
        except Exception as e:
            logger.debug(f"Update check falhou: {e}")
        time.sleep(3600 + random.randint(-300, 300))  # ~1h com jitter


def _apply_update(config: AgentConfig, data: dict):
    """Baixa e aplica update do agente via serviço Windows."""
    import hashlib, shutil, tempfile
    try:
        logger.info(f"Update disponível: {data['version']} — baixando…")
        dl_url  = data["download_url"]
        sha256  = data.get("sha256", "")
        r       = _session.get(
            dl_url,
            headers=auth_headers(config),
            verify=ssl_verify(config),
            timeout=60, stream=True,
        )
        r.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".exe")
        for chunk in r.iter_content(65536):
            tmp.write(chunk)
        tmp.close()

        if sha256:
            h = hashlib.sha256(open(tmp.name, "rb").read()).hexdigest()
            if h.lower() != sha256.lower():
                os.unlink(tmp.name)
                logger.error("Update: hash SHA-256 inválido — abortando")
                return

        exe = sys.executable
        shutil.copy2(tmp.name, exe + ".new")
        os.unlink(tmp.name)

        # NSSM reiniciará o serviço após o processo terminar
        subprocess.Popen(
            ["cmd", "/c", f'timeout /t 2 & move /y "{exe}.new" "{exe}"'],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
        logger.info("Update aplicado — reiniciando…")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Update falhou: {e}")


def webrtc_cleanup_loop():
    """Remove sessões WebRTC inativas há mais de 1h."""
    while True:
        time.sleep(300)
        now = time.time()
        with _webrtc_dc_lock:
            dead = [
                sid for sid, s in STATE.webrtc_sessions.items()
                if now - s.get("ts", now) > 3600
            ]
        for sid in dead:
            STATE.remove_webrtc_session(sid)
            with _webrtc_dc_lock:
                _webrtc_data_channels.pop(sid, None)
        if dead:
            logger.info(f"WebRTC GC: removidas {len(dead)} sessões expiradas")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
def main():
    config = load_config()

    if not config.get("token_hash"):
        logger.error("AGENT_TOKEN_HASH não configurado — encerrando.")
        sys.exit(1)

    logger.info(f"=== AgentService v{VERSION} iniciando ===")
    logger.info(f"Máquina   : {config['machine_name']}")
    logger.info(f"Servidor  : {config['server_url']}")
    logger.info(f"IPC       : 127.0.0.1:{IPC_PORT}  (local + {DJANGO_SERVER_IP})")
    logger.info(f"WebRTC    : 0.0.0.0:{WEBRTC_PORT}  subnet={WEBRTC_ALLOWED_SUBNET}")
    logger.info(f"Token hash: {config['token_hash'][:16]}…")

    threads = [
        threading.Thread(target=start_ipc_server,    args=(config,), daemon=True, name="ipc"),
        threading.Thread(target=start_webrtc_server, args=(config,), daemon=True, name="webrtc-http"),
        threading.Thread(target=health_loop,         args=(config,), daemon=True, name="health"),
        threading.Thread(target=checkin_loop,        args=(config,), daemon=True, name="checkin"),
        threading.Thread(target=notification_loop,   args=(config,), daemon=True, name="notif"),
        threading.Thread(target=webrtc_cleanup_loop, daemon=True,               name="webrtc-gc"),
    ]
    if config.get("auto_update"):
        threads.append(
            threading.Thread(target=update_loop, args=(config,), daemon=True, name="update")
        )

    for t in threads:
        t.start()
        logger.info(f"Thread '{t.name}' iniciada")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Serviço encerrado pelo usuário")


if __name__ == "__main__":
    main()