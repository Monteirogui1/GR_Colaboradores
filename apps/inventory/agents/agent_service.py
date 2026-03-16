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
import ipaddress
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import av
import mss
import numpy as np

# ── Warnings de SSL ───────────────────────────────────────────────────────────
_SSL_VERIFY_ENV = os.environ.get("AGENT_SSL_VERIFY", "true").lower()
if _SSL_VERIFY_ENV == "false":
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
# Versão e intervalos
# ─────────────────────────────────────────────
VERSION                    = "3.2.0"
IPC_PORT                   = 7070      # local only (127.0.0.1) — Tray App
WEBRTC_PORT                = 7071      # rede interna — Django server
WEBRTC_ALLOWED_SUBNET      = os.environ.get("WEBRTC_ALLOWED_SUBNET", "192.168.0.0/16")
HEARTBEAT_INTERVAL         = 300
OFFLINE_CHECK_INTERVAL     = 60
UPDATE_CHECK_INTERVAL      = 3600
NOTIFICATION_POLL_INTERVAL = 120
JITTER_MAX                 = 60

# ─────────────────────────────────────────────
# Logging — funciona em .py e .exe (PyInstaller)
# ─────────────────────────────────────────────
def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = _get_base_dir()
LOG_DIR  = BASE_DIR / "logs"
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
        _ca_bundle  = os.environ.get("AGENT_SSL_CA_BUNDLE", "").strip()
        _ssl_verify = _ca_bundle if _ca_bundle else (
            os.environ.get("AGENT_SSL_VERIFY", "true").lower() != "false"
        )
        self.data = {
            "server_url":     os.environ.get("AGENT_SERVER_URL", "http://192.168.100.247:5002"),
            "token_hash":     os.environ.get("AGENT_TOKEN_HASH", ""),
            "machine_name":   socket.gethostname(),
            "version":        VERSION,
            "auto_update":    os.environ.get("AGENT_AUTO_UPDATE",   "true").lower() == "true",
            "notifications":  os.environ.get("AGENT_NOTIFICATIONS", "true").lower() == "true",
            "check_interval": int(os.environ.get("AGENT_CHECK_INTERVAL", HEARTBEAT_INTERVAL)),
            "ssl_verify":     _ssl_verify,
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
# Helpers
# ─────────────────────────────────────────────
def ssl_verify(config: AgentConfig):
    return config.get("ssl_verify", True)

def auth_headers(config: AgentConfig) -> dict:
    token_hash = config.get("token_hash", "")
    if token_hash:
        return {"Authorization": f"Bearer {token_hash}"}
    return {}

def make_session() -> requests.Session:
    s     = requests.Session()
    retry = Retry(total=3, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://",  adapter)
    s.mount("https://", adapter)
    return s

_session = make_session()


# ─────────────────────────────────────────────
# Estado compartilhado
# ─────────────────────────────────────────────
class AgentState:

    def __init__(self):
        self._lock        = threading.Lock()
        self._webrtc_lock = threading.Lock()
        self.online       = False
        self.last_checkin: datetime | None = None
        self.last_error:   str             = ""
        self.pending_notifications:   list[dict] = []
        self.shown_notification_ids:  set        = self._load_shown_ids()
        self.version          = VERSION
        self.webrtc_sessions: dict = {}

    # ── Notificações ──────────────────────────
    def add_notifications(self, notifs: list[dict]):
        with self._lock:
            existing_ids = {n["id"] for n in self.pending_notifications}
            for n in notifs:
                nid = str(n["id"])
                if n["id"] not in existing_ids and nid not in self.shown_notification_ids:
                    self.pending_notifications.append(n)

    def pop_notifications(self) -> list[dict]:
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

    # ── WebRTC sessions ───────────────────────
    def add_webrtc_session(self, session_id: str, pc, track):
        with self._webrtc_lock:
            self.webrtc_sessions[session_id] = {
                "pc": pc, "track": track, "started": datetime.now(),
            }
            logger.info(f"WebRTC: sessão {session_id[:8]}… registrada")

    def remove_webrtc_session(self, session_id: str):
        with self._webrtc_lock:
            sess = self.webrtc_sessions.pop(session_id, None)
            if sess:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(sess["pc"].close())
                    loop.close()
                except Exception:
                    pass
                logger.info(f"WebRTC: sessão {session_id[:8]}… encerrada")

    def list_webrtc_sessions(self) -> list[dict]:
        with self._webrtc_lock:
            now = datetime.now()
            return [
                {"id": sid[:8] + "…", "started": s["started"].isoformat(),
                 "elapsed": int((now - s["started"]).total_seconds())}
                for sid, s in self.webrtc_sessions.items()
            ]

    def cleanup_webrtc_sessions(self, max_age_seconds: int = 3600):
        with self._webrtc_lock:
            now     = datetime.now()
            expired = [sid for sid, s in self.webrtc_sessions.items()
                       if (now - s["started"]).total_seconds() > max_age_seconds]
        for sid in expired:
            logger.info(f"WebRTC: expirando sessão {sid[:8]}…")
            self.remove_webrtc_session(sid)

    # ── Snapshot ──────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            snap = {
                "version":               self.version,
                "machine":               socket.gethostname(),
                "online":                self.online,
                "last_checkin":          self.last_checkin.isoformat() if self.last_checkin else None,
                "last_error":            self.last_error,
                "pending_notifications": len(self.pending_notifications),
                "webrtc_sessions":       len(self.webrtc_sessions),
            }
            try:
                import ctypes
                user32 = ctypes.windll.user32
                snap["screen"] = {"width": user32.GetSystemMetrics(0),
                                  "height": user32.GetSystemMetrics(1)}
            except Exception:
                snap["screen"] = {"width": 1920, "height": 1080}
            return snap


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
    $os   = Get-CimInstance Win32_OperatingSystem
    $cs   = Get-CimInstance Win32_ComputerSystem
    $bios = Get-CimInstance Win32_BIOS
    $upt  = (Get-Date) - $os.LastBootUpTime
    $proc = Get-CimInstance Win32_Processor
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $net  = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object IPEnabled
    $gpu  = Get-CimInstance Win32_VideoController | Select-Object -First 1
    try {
        $tpm = Get-Tpm
        $tpmInfo = [pscustomobject]@{
            present=$tpm.TpmPresent; ready=$tpm.TpmReady; enabled=$tpm.TpmEnabled
            activated=$tpm.TpmActivated; spec_version=$tpm.SpecVersion
            manufacturer=$tpm.ManufacturerIdTxt; manufacturer_ver=$tpm.ManufacturerVersion
        }
    } catch {
        $tpmInfo = [pscustomobject]@{present=$false;ready=$false;enabled=$false;activated=$false;spec_version=$null;manufacturer=$null;manufacturer_ver=$null}
    }
    $ipAddress  = if ($primaryNet.IPAddress) { $primaryNet.IPAddress[0] } else { "127.0.0.1" }
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
    url     = config.get("server_url") + config.get("ep_checkin")
    payload = {
        "hostname": data["hostname"],
        "ip":       data.get("ip_address", ""),
        "hardware": data,
        "token":    config.get("token_hash"),
    }
    resp = _session.post(url, json=payload, headers=auth_headers(config),
                         verify=ssl_verify(config), timeout=10)
    return resp.status_code in (200, 201)


# ═════════════════════════════════════════════════════════════════════════════
# WebRTC — Captura de Tela + Input Remoto
# ═════════════════════════════════════════════════════════════════════════════

_webrtc_data_channels: dict = {}
_webrtc_dc_lock              = threading.Lock()
_file_buffers:         dict = {}
_file_buffers_lock           = threading.Lock()


class ScreenTrack:
    """Captura a tela principal com mss e entrega frames ao aiortc."""

    _aiortc_base = None

    @classmethod
    def _get_base(cls):
        if cls._aiortc_base is None:
            from aiortc.mediastreams import VideoStreamTrack
            cls._aiortc_base = VideoStreamTrack
        return cls._aiortc_base

    def __new__(cls, *args, **kwargs):
        base     = cls._get_base()
        DynTrack = type("DynScreenTrack", (base,), {
            "kind":     "video",
            "recv":     cls._recv_impl,
            "__init__": cls._init_impl,   # inicializa _id e demais atributos do pai
        })
        instance = object.__new__(DynTrack)
        return instance

    @staticmethod
    def _init_impl(self):
        """Chama o __init__ da VideoStreamTrack para inicializar _id e _timestamp."""
        from aiortc.mediastreams import VideoStreamTrack
        VideoStreamTrack.__init__(self)

    @staticmethod
    async def _recv_impl(self):
        if not hasattr(self, "_sct"):
            self._sct     = mss.mss()
            self._monitor = self._sct.monitors[1]
        pts, time_base  = await self.next_timestamp()
        img             = self._sct.grab(self._monitor)
        frame           = av.VideoFrame.from_ndarray(np.array(img), format="bgra")
        frame.pts       = pts
        frame.time_base = time_base
        return frame


def _handle_input_event(event: dict, session_id: str = ""):
    try:
        import ctypes, win32api, win32con
        user32 = ctypes.windll.user32
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        t      = event.get("t")

        def abs_xy(e):
            return (max(0, min(sw-1, int(e.get("x",0)*sw))),
                    max(0, min(sh-1, int(e.get("y",0)*sh))))

        if   t == "mm":
            win32api.SetCursorPos(abs_xy(event))
        elif t == "mc":
            x, y = abs_xy(event); win32api.SetCursorPos((x,y))
            b = event.get("b","left")
            if   b == "left":  win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x,y); win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,  x,y)
            elif b == "right": win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN,x,y); win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, x,y)
        elif t == "mdc":
            x, y = abs_xy(event); win32api.SetCursorPos((x,y))
            for _ in range(2): win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,x,y); win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,x,y)
        elif t == "md":
            x, y = abs_xy(event); win32api.SetCursorPos((x,y))
            if event.get("b")=="left": win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,x,y)
        elif t == "mu":
            x, y = abs_xy(event); win32api.SetCursorPos((x,y))
            if event.get("b")=="left": win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,x,y)
        elif t == "mb":
            if event.get("d"): win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEDOWN,0,0)
            else:              win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEUP,  0,0)
        elif t == "ms":
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0,0, int(event.get("d",0))*win32con.WHEEL_DELTA)
        elif t == "msh":
            win32api.mouse_event(win32con.MOUSEEVENTF_HWHEEL,0,0, int(event.get("d",0))*win32con.WHEEL_DELTA)
        elif t == "kt":
            import pyautogui
            char = event.get("k","")
            if char: pyautogui.typewrite(char, interval=0)
        elif t == "kp":
            import pyautogui
            key = event.get("k","")
            if key: pyautogui.press(key)
        elif t == "kc":
            import pyautogui
            mods = ["winleft" if m=="win" else m for m in event.get("mods",[])]
            key  = event.get("k","")
            if key: pyautogui.hotkey(*mods, key) if mods else pyautogui.press(key)
        elif t == "paste":
            import pyperclip, pyautogui
            text = event.get("text","")
            if text: pyperclip.copy(text); pyautogui.hotkey("ctrl","v")
        elif t == "clipboard_req":
            _send_clipboard_to_browser(session_id)

    except ImportError as e:
        logger.warning(f"WebRTC input: biblioteca ausente ({e})")
    except Exception as e:
        logger.error(f"WebRTC input error (t={event.get('t')}): {e}")


def _send_clipboard_to_browser(session_id: str):
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return
        msg = json.dumps({"t": "clipboard", "text": text})
        with _webrtc_dc_lock:
            queue = _webrtc_data_channels.get(session_id)
        if queue:
            queue.put_nowait(msg)
    except Exception as e:
        logger.warning(f"Clipboard request failed: {e}")


def _handle_file_chunk(data: bytes):
    with _file_buffers_lock:
        for fid, buf in _file_buffers.items():
            if not buf.get("done"):
                buf["chunks"].append(data)
                buf["received"] = buf.get("received", 0) + len(data)
                return


def _handle_file_message(msg: dict, session_id: str):
    t = msg.get("t")

    if t == "file_start":
        fid = msg.get("id")
        if not fid:
            return
        with _file_buffers_lock:
            _file_buffers[fid] = {"meta": msg, "chunks": [], "received": 0, "done": False}
        logger.info(f"WebRTC file: recebendo '{msg.get('name')}' ({msg.get('size',0)} bytes)")

    elif t == "file_end":
        fid = msg.get("id")
        if not fid:
            return
        with _file_buffers_lock:
            buf = _file_buffers.get(fid)
            if not buf:
                return
            buf["done"] = True
            data        = b"".join(buf["chunks"])
            file_name   = buf["meta"].get("name", f"arquivo_{fid[:8]}")
            _file_buffers.pop(fid, None)
        try:
            desktop = Path(os.path.expanduser("~")) / "Desktop"
            desktop.mkdir(exist_ok=True)
            dest = desktop / _sanitize_filename(file_name)
            dest.write_bytes(data)
            logger.info(f"WebRTC file: '{file_name}' salvo em '{dest}'")
            ack = json.dumps({"t": "file_done", "id": fid})
        except Exception as e:
            logger.error(f"WebRTC file: erro ao salvar '{file_name}': {e}")
            ack = json.dumps({"t": "file_err",  "id": fid, "reason": str(e)})
        with _webrtc_dc_lock:
            queue = _webrtc_data_channels.get(session_id)
        if queue:
            try: queue.put_nowait(ack)
            except Exception: pass


def _sanitize_filename(name: str) -> str:
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or "arquivo_recebido"


def _handle_webrtc_offer(body: dict) -> dict:
    import asyncio
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription, RTCRtpSender
    except ImportError:
        logger.error("aiortc não instalado")
        raise RuntimeError("aiortc não instalado no agente")

    sdp_str  = body.get("sdp", "")
    sdp_type = body.get("type", "offer")
    if not sdp_str or sdp_type != "offer":
        raise ValueError("SDP offer ausente ou tipo inválido")

    session_id = hashlib.md5(sdp_str[:64].encode()).hexdigest()[:16]

    async def negotiate() -> dict:
        pc = RTCPeerConnection()

        # Criar e inicializar o track corretamente
        # __init__ da VideoStreamTrack precisa ser chamado para criar _id
        track = ScreenTrack()
        track.__init__()

        # Usar addTransceiver com direction="sendonly" e forçar H264
        # Isso resolve "None is not in list" causado pelo mismatch
        # entre recvonly (browser) e sendrecv (padrão aiortc)
        try:
            caps   = RTCRtpSender.getCapabilities("video")
            h264   = [c for c in caps.codecs if "h264" in c.mimeType.lower()]
            transceiver = pc.addTransceiver(track, direction="sendonly")
            if h264:
                transceiver.setCodecPreferences(h264)
                logger.info(f"WebRTC: H264 configurado ({len(h264)} perfis)")
            else:
                logger.warning("WebRTC: H264 indisponível, usando codecs padrão")
        except Exception as e:
            # Fallback: addTrack simples
            logger.warning(f"WebRTC: addTransceiver falhou ({e}), usando addTrack")
            try:
                pc.addTrack(track)
            except Exception as e2:
                logger.error(f"WebRTC: addTrack também falhou: {e2}")
                raise

        send_queue: asyncio.Queue = asyncio.Queue()
        with _webrtc_dc_lock:
            _webrtc_data_channels[session_id] = send_queue

        @pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"WebRTC: canal '{channel.label}' aberto ({session_id[:8]}…)")

            @channel.on("message")
            def on_message(message):
                if channel.label == "input":
                    if isinstance(message, str):
                        try:
                            threading.Thread(target=_handle_input_event,
                                             args=(json.loads(message), session_id),
                                             daemon=True).start()
                        except Exception:
                            pass
                elif channel.label == "files":
                    if isinstance(message, bytes):
                        _handle_file_chunk(message)
                    elif isinstance(message, str):
                        try:
                            threading.Thread(target=_handle_file_message,
                                             args=(json.loads(message), session_id),
                                             daemon=True).start()
                        except Exception:
                            pass

            async def drain_queue():
                while True:
                    try:
                        msg = await asyncio.wait_for(send_queue.get(), timeout=30)
                        if channel.readyState == "open":
                            channel.send(msg)
                    except asyncio.TimeoutError:
                        if channel.readyState == "open":
                            channel.send(json.dumps({"t": "ping", "ts": time.time()}))
                    except Exception:
                        break
            asyncio.ensure_future(drain_queue())

        @pc.on("connectionstatechange")
        async def on_state():
            state = pc.connectionState
            logger.info(f"WebRTC: {session_id[:8]}… → {state}")
            if state in ("failed", "closed", "disconnected"):
                STATE.remove_webrtc_session(session_id)
                with _webrtc_dc_lock:
                    _webrtc_data_channels.pop(session_id, None)

        offer  = RTCSessionDescription(sdp=sdp_str, type=sdp_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        STATE.add_webrtc_session(session_id, pc, track)
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(negotiate())
        threading.Thread(target=loop.run_forever, daemon=True,
                         name=f"webrtc-loop-{session_id[:8]}").start()
    except Exception as e:
        loop.close()
        raise e

    logger.info(f"WebRTC: SDP answer gerado para sessão {session_id[:8]}…")
    return result


# ─────────────────────────────────────────────
# IPC HTTP Server — 127.0.0.1:7070 (Tray App)
# ─────────────────────────────────────────────
class IPCHandler(BaseHTTPRequestHandler):
    """Escuta apenas em 127.0.0.1 — comunicação local com o Tray App."""

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

    def do_GET(self):
        if   self.path == "/status":           self._send_json(200, STATE.snapshot())
        elif self.path == "/notifications":    self._send_json(200, {"notifications": STATE.pop_notifications()})
        elif self.path == "/ping":             self._send_json(200, {"pong": True})
        elif self.path == "/webrtc/sessions":  self._send_json(200, {"sessions": STATE.list_webrtc_sessions()})
        else:                                  self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/notifications/ack":
            body     = self._read_json()
            notif_id = body.get("id")
            if notif_id:
                STATE.mark_shown(notif_id)
                threading.Thread(target=self._mark_django_read, args=(notif_id,), daemon=True).start()
            self._send_json(200, {"ok": True})

        elif self.path == "/command":
            self._send_json(200, self._run_command(self._read_json()))

        elif self.path == "/sync":
            threading.Thread(target=_force_sync, args=(self.config,), daemon=True).start()
            self._send_json(200, {"ok": True, "message": "sync triggered"})

        elif self.path == "/webrtc/close":
            body       = self._read_json()
            session_id = body.get("session_id", "")
            if session_id:
                STATE.remove_webrtc_session(session_id)
                with _webrtc_dc_lock: _webrtc_data_channels.pop(session_id, None)
                self._send_json(200, {"ok": True})
            else:
                self._send_json(400, {"error": "session_id obrigatório"})

        else:
            self._send_json(404, {"error": "not found"})

    def _mark_django_read(self, notif_id):
        try:
            url = self.config.get("server_url") + self.config.get("ep_notif")
            _session.post(url, json={"notification_id": notif_id},
                          headers=auth_headers(self.config),
                          verify=ssl_verify(self.config), timeout=5)
        except Exception as e:
            logger.warning(f"Falha ao marcar notif {notif_id}: {e}")

    def _run_command(self, body: dict) -> dict:
        cmd_type = body.get("type", "powershell").lower()
        script   = body.get("script", "")
        timeout  = min(int(body.get("timeout", 30)), 120)
        if not script.strip():
            return {"error": "script vazio", "stdout": "", "stderr": "", "exit_code": -1}
        try:
            cmd  = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
                    if cmd_type == "powershell" else ["cmd", "/c", script])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                  creationflags=subprocess.CREATE_NO_WINDOW if platform.system()=="Windows" else 0)
            return {"stdout": proc.stdout, "stderr": proc.stderr,
                    "exit_code": proc.returncode, "executed_at": datetime.now().isoformat()}
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "stdout": "", "stderr": "", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "stdout": "", "stderr": "", "exit_code": -1}


def start_ipc_server(config: AgentConfig):
    IPCHandler.config = config
    server = HTTPServer(("127.0.0.1", IPC_PORT), IPCHandler)
    logger.info(f"IPC server listening on 127.0.0.1:{IPC_PORT}")
    server.serve_forever()


# ─────────────────────────────────────────────
# WebRTC HTTP Server — 0.0.0.0:7071 (Django)
# ─────────────────────────────────────────────
class WebRTCHandler(BaseHTTPRequestHandler):
    """
    Escuta na rede interna para receber SDP offer do Django.
    Camadas de segurança:
      1. Subnet check  — só aceita IPs de WEBRTC_ALLOWED_SUBNET
      2. Bearer token  — mesmo hash SHA-256 do agente
    """

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
        try:
            client_ip = self.client_address[0]
            network   = ipaddress.ip_network(WEBRTC_ALLOWED_SUBNET, strict=False)
            return ipaddress.ip_address(client_ip) in network
        except Exception:
            return False

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return auth[7:].strip() == self.config.get("token_hash", "")

    def _guard(self) -> bool:
        if not self._check_subnet():
            logger.warning(f"WebRTC: subnet bloqueada {self.client_address[0]}")
            self._send_json(403, {"error": "Origem não permitida"})
            return False
        if not self._check_auth():
            logger.warning(f"WebRTC: token inválido de {self.client_address[0]}")
            self._send_json(401, {"error": "Token inválido"})
            return False
        return True

    def do_GET(self):
        if not self._guard(): return
        if self.path == "/health":
            self._send_json(200, {"ok": True, "version": VERSION,
                                  "webrtc_sessions": len(STATE.webrtc_sessions)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._guard(): return

        if self.path == "/webrtc/offer":
            body = self._read_json()
            try:
                # Delegar ao Tray App (Session do usuário) — mss funciona lá
                resp = _session.post(
                    "http://127.0.0.1:7071/webrtc/offer",
                    json=body,
                    timeout=15,
                )
                resp.raise_for_status()
                self._send_json(200, resp.json())
            except requests.exceptions.ConnectionError:
                logger.error("WebRTC: Tray App não está rodando na porta 7071")
                self._send_json(503, {"error": "Tray App offline — abra o agent_tray.exe"})
            except requests.exceptions.Timeout:
                logger.error("WebRTC: Tray App não respondeu no tempo limite")
                self._send_json(504, {"error": "Tray App não respondeu"})
            except Exception as e:
                logger.exception(f"WebRTC: erro ao delegar ao Tray App: {e}")
                self._send_json(500, {"error": f"Erro interno: {e}"})

        elif self.path == "/webrtc/close":
            body       = self._read_json()
            session_id = body.get("session_id", "")
            if session_id:
                try:
                    _session.post("http://127.0.0.1:7071/webrtc/close",
                                  json=body, timeout=5)
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
    logger.info(f"WebRTC server listening on 0.0.0.0:{WEBRTC_PORT} (subnet: {WEBRTC_ALLOWED_SUBNET})")
    server.serve_forever()


# ─────────────────────────────────────────────
# Loops de trabalho
# ─────────────────────────────────────────────
def _force_sync(config: AgentConfig):
    try:
        data = collect_hardware()
        ok   = send_checkin(config, data)
        STATE.online       = True
        STATE.last_checkin = datetime.now()
        STATE.last_error   = "" if ok else "HTTP error on checkin"
        logger.info("Check-in concluído" if ok else "Falha no check-in")
    except Exception as e:
        STATE.last_error = str(e)
        logger.error(f"Erro no check-in: {e}")


def checkin_loop(config: AgentConfig):
    jitter = random.randint(0, JITTER_MAX)
    logger.info(f"Checkin loop aguardando {jitter}s de jitter inicial...")
    time.sleep(jitter)
    while True:
        try:
            data = collect_hardware()
            ok   = send_checkin(config, data)
            STATE.online       = True
            STATE.last_checkin = datetime.now()
            STATE.last_error   = "" if ok else "HTTP error on checkin"
            logger.info(f"Check-in {'OK' if ok else 'FALHOU'}")
        except Exception as e:
            STATE.online     = False
            STATE.last_error = str(e)
            logger.error(f"Erro no check-in: {e}")
        time.sleep(config.get("check_interval") + random.randint(0, JITTER_MAX))


def notification_loop(config: AgentConfig):
    time.sleep(30)
    while True:
        try:
            url  = (config.get("server_url") + config.get("ep_notif")
                    + f"?machine_name={config.get('machine_name')}&status=pending&limit=20")
            resp = _session.get(url, headers=auth_headers(config),
                                verify=ssl_verify(config), timeout=10)
            if resp.status_code == 200:
                data   = resp.json()
                notifs = data.get("notifications", []) if data.get("success") else []
                if notifs:
                    STATE.add_notifications(notifs)
                    logger.info(f"{len(notifs)} notificações recebidas")
        except Exception as e:
            logger.warning(f"Erro ao buscar notificações: {e}")
        time.sleep(NOTIFICATION_POLL_INTERVAL + random.randint(0, 30))


def health_loop(config: AgentConfig):
    while True:
        try:
            url  = config.get("server_url") + config.get("ep_health")
            resp = _session.get(url, verify=ssl_verify(config), timeout=5)
            STATE.online = resp.status_code == 200
        except Exception:
            STATE.online = False
        time.sleep(OFFLINE_CHECK_INTERVAL)


def update_loop(config: AgentConfig):
    time.sleep(60)
    while True:
        try:
            url  = config.get("server_url") + config.get("ep_update")
            resp = _session.post(url,
                                 json={"current_version": VERSION,
                                       "machine_name": config.get("machine_name")},
                                 headers=auth_headers(config),
                                 verify=ssl_verify(config), timeout=10)
            if resp.status_code == 200:
                info = resp.json()
                if info.get("update_available"):
                    _apply_update(config, info)
        except Exception as e:
            logger.warning(f"Erro na verificação de updates: {e}")
        time.sleep(UPDATE_CHECK_INTERVAL)


def webrtc_cleanup_loop():
    while True:
        time.sleep(600)
        STATE.cleanup_webrtc_sessions(max_age_seconds=3600)


def _apply_update(config: AgentConfig, info: dict):
    if not info.get("download_url"):
        return
    try:
        logger.info(f"Aplicando update {info.get('version')}...")
        resp = _session.get(info["download_url"], headers=auth_headers(config),
                            verify=ssl_verify(config), timeout=60)
        if resp.status_code == 200:
            current = Path(os.path.abspath(__file__))
            current.with_suffix(".py.bak").write_bytes(current.read_bytes())
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
    logger.info(f"IPC    : 127.0.0.1:{IPC_PORT}  (Tray App — local only)")
    logger.info(f"WebRTC : 0.0.0.0:{WEBRTC_PORT}   (Django — subnet {WEBRTC_ALLOWED_SUBNET})")

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
        logger.info("Serviço encerrado")


if __name__ == "__main__":
    main()