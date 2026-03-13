import os
import sys
import time
import json
import socket
import platform
import subprocess
import threading
import hashlib
import logging
import random
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# ── Warnings de SSL: só suprime se AGENT_SSL_VERIFY=false (dev explícito) ────
_SSL_VERIFY_ENV = os.environ.get("AGENT_SSL_VERIFY", "true").lower()
if _SSL_VERIFY_ENV == "false":
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
# Versão e intervalos
# ─────────────────────────────────────────────
VERSION = "3.0.1"
IPC_PORT = 7070
HEARTBEAT_INTERVAL = 300         # 5 min entre check-ins
OFFLINE_CHECK_INTERVAL = 60
UPDATE_CHECK_INTERVAL = 3600
NOTIFICATION_POLL_INTERVAL = 120
JITTER_MAX = 60                  # distribui carga: cada agente adiciona 0–60s

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
LOG_DIR = Path(os.path.dirname(__file__)) / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("AgentService")
logger.setLevel(logging.INFO)
_handler = RotatingFileHandler(
    LOG_DIR / "service.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_handler)
logger.addHandler(logging.StreamHandler(sys.stdout))


# ─────────────────────────────────────────────
# Configuração
# ─────────────────────────────────────────────
class AgentConfig:
    def __init__(self):
        # ssl_verify:
        #   True          → valida SSL normalmente (produção, padrão)
        #   False         → ignora SSL (dev: AGENT_SSL_VERIFY=false)
        #   "/path/ca.pem"→ CA bundle customizado para certs auto-assinados
        _ca_bundle = os.environ.get("AGENT_SSL_CA_BUNDLE", "").strip()
        _ssl_verify = _ca_bundle if _ca_bundle else (
            os.environ.get("AGENT_SSL_VERIFY", "true").lower() != "false"
        )

        self.data = {
            "server_url":     os.environ.get("AGENT_SERVER_URL", "http://192.168.1.54:5001"),
            "token_hash":     os.environ.get("AGENT_TOKEN_HASH", ""),
            "machine_name":   socket.gethostname(),
            "version":        VERSION,
            "auto_update":    os.environ.get("AGENT_AUTO_UPDATE", "true").lower() == "true",
            "notifications":  os.environ.get("AGENT_NOTIFICATIONS", "true").lower() == "true",
            "check_interval": int(os.environ.get("AGENT_CHECK_INTERVAL", HEARTBEAT_INTERVAL)),
            # SSL: True | False | "/caminho/ca.pem"
            "ssl_verify":     _ssl_verify,
            # endpoints Django
            "ep_validate":    "/api/inventario/agent/validate/",
            "ep_checkin":     "/api/inventario/checkin/",
            "ep_update":      "/api/inventario/agent/update/",
            "ep_health":      "/api/inventario/health/",
            "ep_notif":       "/api/notifications/",
        }

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


# ─────────────────────────────────────────────
# Helpers de SSL e autenticação
# ─────────────────────────────────────────────
def ssl_verify(config: AgentConfig):
    """
    Retorna o valor correto para verify= nas chamadas requests.
    True → valida normalmente | False → ignora | str → caminho CA bundle.
    """
    return config.get("ssl_verify", True)


def auth_headers(config: AgentConfig) -> dict:
    """
    Retorna o header Authorization com o token do agente.
    Todas as requisições ao servidor Django devem passar esse header.
    """
    token_hash = config.get("token_hash", "")
    if token_hash:
        return {"Authorization": f"Bearer {token_hash}"}
    return {}


# ─────────────────────────────────────────────
# HTTP Session com retry
# ─────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3, backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

_session = make_session()


# ─────────────────────────────────────────────
# Estado compartilhado (entre threads e IPC)
# ─────────────────────────────────────────────
class AgentState:
    """Thread-safe estado global do agente."""

    def __init__(self):
        self._lock = threading.Lock()
        self.online = False
        self.last_checkin: datetime | None = None
        self.last_error: str = ""
        self.pending_notifications: list[dict] = []
        self.shown_notification_ids: set = self._load_shown_ids()
        self.version = VERSION

    # ── notificações ──────────────────────────
    def add_notifications(self, notifs: list[dict]):
        with self._lock:
            existing_ids = {n["id"] for n in self.pending_notifications}
            for n in notifs:
                nid = str(n["id"])
                if n["id"] not in existing_ids and nid not in self.shown_notification_ids:
                    self.pending_notifications.append(n)

    def pop_notifications(self) -> list[dict]:
        """Tray consome as notificações pendentes."""
        with self._lock:
            notifs = list(self.pending_notifications)
            self.pending_notifications.clear()
            return notifs

    def mark_shown(self, notif_id):
        with self._lock:
            self.shown_notification_ids.add(str(notif_id))
            self._save_shown_ids()

    def _load_shown_ids(self) -> set:
        path = LOG_DIR / "shown_notifications.json"
        try:
            if path.exists():
                return set(json.loads(path.read_text()).get("ids", []))
        except Exception:
            pass
        return set()

    def _save_shown_ids(self):
        path = LOG_DIR / "shown_notifications.json"
        try:
            path.write_text(json.dumps({"ids": list(self.shown_notification_ids)}))
        except Exception:
            pass

    # ── snapshot para /status ─────────────────
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "version":               self.version,
                "machine":               socket.gethostname(),
                "online":                self.online,
                "last_checkin":          self.last_checkin.isoformat() if self.last_checkin else None,
                "last_error":            self.last_error,
                "pending_notifications": len(self.pending_notifications),
            }


STATE = AgentState()


# ─────────────────────────────────────────────
# PowerShell Collector
# ─────────────────────────────────────────────
PS_SCRIPT = r"""
$ErrorActionPreference = "SilentlyContinue"
function Get-SystemInfo {
    $loggedUser = ((Get-CimInstance Win32_ComputerSystem).UserName -split '\\')[-1]
    $primaryNet = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled } | Select-Object -First 1
    $macAddress = $primaryNet.MACAddress
    $arrays = Get-CimInstance Win32_PhysicalMemoryArray
    $totalSlots = ($arrays | Measure-Object -Property MemoryDevices -Sum).Sum
    $modules = Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
        [pscustomobject]@{
            bank_label=$_.BankLabel; device_locator=$_.DeviceLocator
            capacity_gb=[math]::Round($_.Capacity/1GB,2); speed_mhz=$_.Speed
            manufacturer=$_.Manufacturer; part_number=$_.PartNumber; serial_number=$_.SerialNumber
        }
    }
    $avList = Get-CimInstance -Namespace "root\SecurityCenter2" -ClassName AntiVirusProduct -EA SilentlyContinue
    $av = $avList | Where-Object { $_.displayName -notmatch "Defender" } | Select-Object -First 1
    if (-not $av) { $av = $avList | Select-Object -First 1 }
    $os=$_= Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $bios = Get-CimInstance Win32_BIOS
    $upt = (Get-Date) - $os.LastBootUpTime
    $proc = Get-CimInstance Win32_Processor
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $net = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object IPEnabled
    $gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1
    try {
        $tpm = Get-Tpm
        $tpmInfo = [pscustomobject]@{
            present=$tpm.TpmPresent; ready=$tpm.TpmReady; enabled=$tpm.TpmEnabled
            activated=$tpm.TpmActivated; spec_version=$tpm.SpecVersion
            manufacturer=$tpm.ManufacturerIdTxt; manufacturer_ver=$tpm.ManufacturerVersion
        }
    } catch { $tpmInfo = [pscustomobject]@{present=$false;ready=$false;enabled=$false;activated=$false;spec_version=$null;manufacturer=$null;manufacturer_ver=$null} }
    $ipAddress = if ($primaryNet.IPAddress) { $primaryNet.IPAddress[0] } else { "127.0.0.1" }
    $diskUsedGb = [math]::Round(($disk.Size - $disk.FreeSpace)/1GB, 2)
    $result = [pscustomobject]@{
        hostname=$env:COMPUTERNAME; ip_address=$ipAddress; logged_user=$loggedUser
        manufacturer=$cs.Manufacturer; model=$cs.Model; serial_number=$bios.SerialNumber
        bios_version=$bios.SMBIOSBIOSVersion; bios_release=$bios.ReleaseDate
        os_caption=$os.Caption; os_architecture=$os.OSArchitecture; os_build=$os.BuildNumber
        install_date=$os.InstallDate; last_boot=$os.LastBootUpTime
        uptime_days=[math]::Round($upt.TotalDays,2)
        cpu=$proc.Name; ram_gb=[math]::Round(($cs.TotalPhysicalMemory/1GB),2)
        disk_space_gb=[math]::Round($disk.Size/1GB,2); disk_free_gb=[math]::Round($disk.FreeSpace/1GB,2)
        disk_used_gb=$diskUsedGb; mac_address=$macAddress
        total_memory_slots=$totalSlots; populated_memory_slots=$modules.Count
        memory_modules=@($modules)
        network_adapters=@($net | ForEach-Object {
            [pscustomobject]@{
                name=$_.Description; mac=$_.MACAddress
                ip=($_.IPAddress -join ","); gateway=($_.DefaultIPGateway -join ",")
                dns=($_.DNSServerSearchOrder -join ","); dhcp=$_.DHCPEnabled
            }
        })
        gpu_name=$gpu.Name; gpu_driver=$gpu.DriverVersion
        antivirus_name=$av.displayName
        av_state=if ($av.productState) { $av.productState.ToString() } else { $null }
        tpm=$tpmInfo
    }
    return $result | ConvertTo-Json -Depth 10 -Compress
}
Get-SystemInfo
"""


def collect_hardware() -> dict:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error: {result.stderr[:200]}")
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("PowerShell returned empty output")
    return json.loads(output)


def send_checkin(config: AgentConfig, data: dict) -> bool:
    """Envia dados de hardware ao Django. Token vai no body (compatibilidade) e no header."""
    url = config.get("server_url") + config.get("ep_checkin")
    payload = {
        "hostname": data["hostname"],
        "ip":       data.get("ip_address", ""),
        "hardware": data,
        "token":    config.get("token_hash"),   # mantido no body para MachineCheckinView
    }
    resp = _session.post(
        url,
        json=payload,
        headers=auth_headers(config),
        verify=ssl_verify(config),
        timeout=10,
    )
    return resp.status_code in (200, 201)


# ─────────────────────────────────────────────
# IPC HTTP Server (localhost only)
# ─────────────────────────────────────────────
class IPCHandler(BaseHTTPRequestHandler):
    """
    Servidor HTTP local para comunicação entre o Serviço e o Tray App.
    Escuta APENAS em 127.0.0.1 — nunca exposto na rede.
    Não exige token: o tráfego é estritamente local.
    """

    config: AgentConfig = None   # injetado antes de iniciar o servidor

    def log_message(self, fmt, *args):
        logger.debug(f"IPC {fmt % args}")

    def _send_json(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── GET ───────────────────────────────────
    def do_GET(self):
        if self.path == "/status":
            self._send_json(200, STATE.snapshot())

        elif self.path == "/notifications":
            notifs = STATE.pop_notifications()
            self._send_json(200, {"notifications": notifs})

        elif self.path == "/ping":
            self._send_json(200, {"pong": True})

        else:
            self._send_json(404, {"error": "not found"})

    # ── POST ──────────────────────────────────
    def do_POST(self):
        if self.path == "/notifications/ack":
            body = self._read_json()
            notif_id = body.get("id")
            if notif_id:
                STATE.mark_shown(notif_id)
                threading.Thread(
                    target=self._mark_django_read,
                    args=(notif_id,),
                    daemon=True,
                ).start()
            self._send_json(200, {"ok": True})

        elif self.path == "/command":
            body = self._read_json()
            result = self._run_command(body)
            self._send_json(200, result)

        elif self.path == "/sync":
            threading.Thread(
                target=_force_sync, args=(self.config,), daemon=True
            ).start()
            self._send_json(200, {"ok": True, "message": "sync triggered"})

        else:
            self._send_json(404, {"error": "not found"})

    def _mark_django_read(self, notif_id):
        """Propaga ACK para o servidor Django com autenticação."""
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
            logger.warning(f"Falha ao marcar notif {notif_id} no Django: {e}")

    def _run_command(self, body: dict) -> dict:
        """Executa script PowerShell ou CMD na máquina local."""
        cmd_type = body.get("type", "powershell").lower()
        script   = body.get("script", "")
        timeout  = min(int(body.get("timeout", 30)), 120)

        if not script.strip():
            return {"error": "script vazio", "stdout": "", "stderr": "", "exit_code": -1}

        try:
            if cmd_type == "powershell":
                cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
            else:
                cmd = ["cmd", "/c", script]

            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
            )
            return {
                "stdout":      proc.stdout,
                "stderr":      proc.stderr,
                "exit_code":   proc.returncode,
                "executed_at": datetime.now().isoformat(),
            }
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "stdout": "", "stderr": "", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "stdout": "", "stderr": "", "exit_code": -1}


def start_ipc_server(config: AgentConfig):
    """Sobe o servidor IPC em thread dedicada."""
    IPCHandler.config = config
    server = HTTPServer(("127.0.0.1", IPC_PORT), IPCHandler)
    logger.info(f"IPC server listening on 127.0.0.1:{IPC_PORT}")
    server.serve_forever()


# ─────────────────────────────────────────────
# Loops de trabalho
# ─────────────────────────────────────────────
def _force_sync(config: AgentConfig):
    try:
        data = collect_hardware()
        ok = send_checkin(config, data)
        STATE.online = True
        STATE.last_checkin = datetime.now()
        STATE.last_error = "" if ok else "HTTP error on checkin"
        logger.info("Check-in concluído" if ok else "Falha no check-in")
    except Exception as e:
        STATE.last_error = str(e)
        logger.error(f"Erro no check-in: {e}")


def checkin_loop(config: AgentConfig):
    """Coleta e envia hardware com jitter para distribuir carga no servidor."""
    jitter = random.randint(0, JITTER_MAX)
    logger.info(f"Checkin loop aguardando {jitter}s de jitter inicial...")
    time.sleep(jitter)

    while True:
        try:
            data = collect_hardware()
            ok = send_checkin(config, data)
            STATE.online = True
            STATE.last_checkin = datetime.now()
            STATE.last_error = "" if ok else "HTTP error on checkin"
            logger.info(f"Check-in {'OK' if ok else 'FALHOU'}")
        except Exception as e:
            STATE.online = False
            STATE.last_error = str(e)
            logger.error(f"Erro no check-in: {e}")

        interval = config.get("check_interval") + random.randint(0, JITTER_MAX)
        time.sleep(interval)


def notification_loop(config: AgentConfig):
    """Polling de notificações do Django com Authorization header."""
    time.sleep(30)
    while True:
        try:
            url = (
                config.get("server_url")
                + config.get("ep_notif")
                + f"?machine_name={config.get('machine_name')}&status=pending&limit=20"
            )
            resp = _session.get(
                url,
                headers=auth_headers(config),
                verify=ssl_verify(config),
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    notifs = data.get("notifications", [])
                    if notifs:
                        STATE.add_notifications(notifs)
                        logger.info(f"{len(notifs)} notificações recebidas")
        except Exception as e:
            logger.warning(f"Erro ao buscar notificações: {e}")

        time.sleep(NOTIFICATION_POLL_INTERVAL + random.randint(0, 30))


def health_loop(config: AgentConfig):
    """Verifica conectividade — endpoint /health/ é público, sem Authorization."""
    while True:
        try:
            url = config.get("server_url") + config.get("ep_health")
            resp = _session.get(
                url,
                verify=ssl_verify(config),
                timeout=5,
            )
            STATE.online = resp.status_code == 200
        except Exception:
            STATE.online = False
        time.sleep(OFFLINE_CHECK_INTERVAL)


def update_loop(config: AgentConfig):
    """Verifica e aplica atualizações do agente com Authorization header."""
    time.sleep(60)
    while True:
        try:
            url = config.get("server_url") + config.get("ep_update")
            resp = _session.post(
                url,
                json={
                    "current_version": VERSION,
                    "machine_name":    config.get("machine_name"),
                },
                headers=auth_headers(config),
                verify=ssl_verify(config),
                timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()
                if info.get("update_available"):
                    _apply_update(config, info)
        except Exception as e:
            logger.warning(f"Erro na verificação de updates: {e}")
        time.sleep(UPDATE_CHECK_INTERVAL)


def _apply_update(config: AgentConfig, info: dict):
    """Baixa e aplica novo executável do agente."""
    if not info.get("download_url"):
        return
    try:
        logger.info(f"Aplicando update {info.get('version')}...")
        resp = _session.get(
            info["download_url"],
            headers=auth_headers(config),
            verify=ssl_verify(config),
            timeout=60,
        )
        if resp.status_code == 200:
            current = Path(os.path.abspath(__file__))
            backup  = current.with_suffix(".py.bak")
            backup.write_bytes(current.read_bytes())
            current.write_bytes(resp.content)
            logger.info("Update aplicado. Reiniciando...")
            time.sleep(2)
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        logger.error(f"Falha no update: {e}")


# ─────────────────────────────────────────────
# Ponto de entrada
# ─────────────────────────────────────────────
def main():
    token = None
    for arg in sys.argv[1:]:
        if arg.startswith("--token="):
            token = arg.split("=", 1)[1]

    config = AgentConfig()

    if token:
        config.set("token_hash", hashlib.sha256(token.encode()).hexdigest())

    if not config.get("token_hash"):
        logger.error("Token não configurado. Encerrando.")
        sys.exit(1)

    logger.info(f"=== AgentService v{VERSION} iniciando ===")
    logger.info(f"Máquina: {config.get('machine_name')} | Servidor: {config.get('server_url')}")
    logger.info(f"SSL verify: {config.get('ssl_verify')} | Heartbeat: {config.get('check_interval')}s + jitter")
    logger.info(f"IPC: 127.0.0.1:{IPC_PORT}")

    threads = [
        threading.Thread(target=start_ipc_server, args=(config,), daemon=True, name="ipc"),
        threading.Thread(target=health_loop,       args=(config,), daemon=True, name="health"),
        threading.Thread(target=checkin_loop,      args=(config,), daemon=True, name="checkin"),
        threading.Thread(target=notification_loop, args=(config,), daemon=True, name="notif"),
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
        logger.info("Serviço encerrado")


if __name__ == "__main__":
    main()