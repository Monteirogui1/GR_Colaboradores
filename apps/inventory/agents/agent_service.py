import ctypes
from uuid import UUID
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
import re
from datetime import datetime
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

_SSL_VERIFY_ENV = os.environ.get("AGENT_SSL_VERIFY", "true").lower()
if _SSL_VERIFY_ENV == "false":
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

VERSION                    = "3.2.0"
AGENT_TYPE                 = "service"
IPC_PORT                   = 7070
WEBRTC_PORT                = 7071
WEBRTC_ALLOWED_SUBNET      = os.environ.get("WEBRTC_ALLOWED_SUBNET", "192.168.0.0/16")
HEARTBEAT_INTERVAL         = 300
OFFLINE_CHECK_INTERVAL     = 60
UPDATE_CHECK_INTERVAL      = 3600
NOTIFICATION_POLL_INTERVAL = 120
JITTER_MAX                 = 60

FOLDERID_Desktop    = UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
FOLDERID_Documents  = UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
FOLDERID_Downloads  = UUID("{374DE290-123F-4565-9164-39C4925E467B}")

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

# ── Instância global — acessível pelo snapshot ────────────────────────────────
# Criada no main() e atribuída aqui para o snapshot() poder ler sem depender
# de os.environ (que pode não estar disponível se o NSSM não reinjetou).
_CONFIG: AgentConfig = None


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _uuid_to_guid(u: UUID) -> GUID:
    data = u.bytes_le
    return GUID(
        int.from_bytes(data[0:4], "little"),
        int.from_bytes(data[4:6], "little"),
        int.from_bytes(data[6:8], "little"),
        (ctypes.c_ubyte * 8)(*data[8:16]),
    )


def _get_known_folder(folder_id: UUID) -> Path | None:
    try:
        guid  = _uuid_to_guid(folder_id)
        ppath = ctypes.c_wchar_p()
        ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, 0, ctypes.byref(ppath))
        if ppath.value:
            path = Path(ppath.value)
            ctypes.windll.ole32.CoTaskMemFree(ppath)
            return path
    except Exception:
        pass
    return None


def ssl_verify(config: AgentConfig):
    return config.get("ssl_verify", True)

def auth_headers(config: AgentConfig) -> dict:
    """
    Retorna headers de autenticação.
    Inclui X-Machine-Name para permitir tokens compartilhados entre máquinas.
    """
    token_hash   = config.get("token_hash", "")
    machine_name = config.get("machine_name", socket.gethostname())
    if token_hash:
        return {
            "Authorization":  f"Bearer {token_hash}",
            "X-Machine-Name": machine_name,
        }
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
        self.logged_user: str = ""   # atualizado a cada checkin com o usuário Windows atual

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

    # ── CORREÇÃO: snapshot usa _CONFIG (instância) e não os.environ direto ────
    def snapshot(self) -> dict:
        with self._lock:
            # Usa _CONFIG se já inicializado, senão cai para os.environ como fallback
            cfg_server = (_CONFIG.get("server_url", "") if _CONFIG
                          else os.environ.get("AGENT_SERVER_URL", ""))
            cfg_token  = (_CONFIG.get("token_hash", "") if _CONFIG
                          else os.environ.get("AGENT_TOKEN_HASH", ""))

            snap = {
                "version":               self.version,
                "machine":               socket.gethostname(),
                "online":                self.online,
                "last_checkin":          self.last_checkin.isoformat() if self.last_checkin else None,
                "last_error":            self.last_error,
                "pending_notifications": len(self.pending_notifications),
                "webrtc_sessions":       len(self.webrtc_sessions),
                "server_url":            cfg_server,
                "token_hash":            cfg_token,
                "logged_user":           self.logged_user,
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
# WebRTC (idêntico ao original — sem alterações)
# ═════════════════════════════════════════════════════════════════════════════

_webrtc_data_channels: dict = {}
_webrtc_dc_lock              = threading.Lock()
_file_buffers:         dict = {}
_file_buffers_lock           = threading.Lock()


class ScreenTrack:
    _monitor_index = 1
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
            "__init__": cls._init_impl,
        })
        instance = object.__new__(DynTrack)
        return instance

    @staticmethod
    def _init_impl(self):
        from aiortc.mediastreams import VideoStreamTrack
        VideoStreamTrack.__init__(self)

    @staticmethod
    async def _recv_impl(self):
        if not hasattr(self, "_sct"):
            self._sct = mss.mss()
        # Atualiza o monitor a cada frame (permite troca em runtime)
        idx = ScreenTrack._monitor_index
        monitors = self._sct.monitors
        if idx < 1 or idx >= len(monitors):
            idx = 1
        self._monitor = monitors[idx]
        pts, time_base = await self.next_timestamp()
        img = self._sct.grab(self._monitor)
        frame = av.VideoFrame.from_ndarray(np.array(img), format="bgra")
        frame.pts = pts
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

        if   t == "mm":  win32api.SetCursorPos(abs_xy(event))
        elif t == "mc":
            x, y = abs_xy(event); win32api.SetCursorPos((x,y))
            b = event.get("b","left")
            if   b == "left":  win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x,y); win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,  x,y)
            elif b == "right": win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN,x,y); win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, x,y)
        elif t == "mdc":
            x, y = abs_xy(event); win32api.SetCursorPos((x,y))
            for _ in range(2):
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,x,y)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,  x,y)
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
            import pyautogui; char = event.get("k","")
            if char: pyautogui.typewrite(char, interval=0)
        elif t == "kp":
            import pyautogui; key = event.get("k","")
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
        if not text: return
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


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or "arquivo_recebido"


def get_explorer_path() -> str:
    try:
        resp = requests.get("http://127.0.0.1:7071/explorer/path", timeout=3)
        if resp.ok:
            return resp.json().get("path", "downloads")
    except Exception:
        pass
    return str(_get_known_folder(FOLDERID_Downloads) or Path.home() / "Downloads")


def _default_known_dirs() -> dict:
    return {
        "downloads": _get_known_folder(FOLDERID_Downloads) or Path.home() / "Downloads",
        "desktop":   _get_known_folder(FOLDERID_Desktop)   or Path.home() / "Desktop",
        "documents": _get_known_folder(FOLDERID_Documents) or Path.home() / "Documents",
    }


def _resolve_dest_dir(dest_key: str) -> Path:
    dest_map = _default_known_dirs()
    if dest_key == "explorer":
        raw = get_explorer_path()
        if raw in ("downloads", "desktop", "documents"):
            return _resolve_dest_dir(raw)
        p = Path(raw)
        if p.is_absolute():
            return p
        return dest_map["downloads"]
    if dest_key in dest_map:
        return dest_map[dest_key]
    if dest_key and (os.sep in dest_key or "/" in dest_key or
                     (len(dest_key) >= 3 and dest_key[1:3] == ":\\")):
        return Path(dest_key)
    return dest_map["downloads"]


def _handle_file_message(msg: dict, session_id: str):
    t = msg.get("t")
    if t == "file_start":
        fid = msg.get("id")
        if not fid: return
        with _file_buffers_lock:
            _file_buffers[fid] = {"meta": msg, "chunks": [], "received": 0, "done": False}
        logger.info(f"WebRTC file: recebendo '{msg.get('name')}' dest='{msg.get('dest', 'downloads')}'")
    elif t == "file_end":
        fid = msg.get("id")
        if not fid: return
        with _file_buffers_lock:
            buf = _file_buffers.get(fid)
            if not buf: return
            buf["done"] = True
            data      = b"".join(buf["chunks"])
            file_name = buf["meta"].get("name", f"arquivo_{fid[:8]}")
            dest_key  = buf["meta"].get("dest", "downloads")
            _file_buffers.pop(fid, None)
        try:
            dest_dir  = _resolve_dest_dir(dest_key)
            dest_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _sanitize_filename(file_name)
            dest_path = dest_dir / safe_name
            if dest_path.exists():
                stem, suffix = dest_path.stem, dest_path.suffix
                counter = 1
                while dest_path.exists():
                    dest_path = dest_dir / f"{stem} ({counter}){suffix}"
                    counter  += 1
            dest_path.write_bytes(data)
            logger.info(f"WebRTC file: '{file_name}' salvo em '{dest_path}'")
            ack = json.dumps({"t": "file_done", "id": fid, "name": file_name, "path": str(dest_path)})
        except Exception as e:
            logger.error(f"WebRTC file: erro ao salvar '{file_name}': {e}")
            ack = json.dumps({"t": "file_err", "id": fid, "reason": str(e)})
        with _webrtc_dc_lock:
            queue = _webrtc_data_channels.get(session_id)
        if queue:
            try: queue.put_nowait(ack)
            except Exception: pass


def _handle_webrtc_offer(body: dict) -> dict:
    import asyncio
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription, RTCRtpSender
    except ImportError:
        raise RuntimeError("aiortc não instalado")

    sdp_str  = body.get("sdp", "")
    sdp_type = body.get("type", "offer")
    if not sdp_str or sdp_type != "offer":
        raise ValueError("SDP offer ausente ou tipo inválido")

    session_id = hashlib.md5(sdp_str[:64].encode()).hexdigest()[:16]

    async def negotiate() -> dict:
        pc    = RTCPeerConnection()
        track = ScreenTrack()
        track.__init__()
        try:
            caps        = RTCRtpSender.getCapabilities("video")
            h264        = [c for c in caps.codecs if "h264" in c.mimeType.lower()]
            transceiver = pc.addTransceiver(track, direction="sendonly")
            if h264:
                transceiver.setCodecPreferences(h264)
        except Exception as e:
            logger.warning(f"WebRTC: addTransceiver falhou ({e}), usando addTrack")
            try:
                pc.addTrack(track)
            except Exception as e2:
                raise e2

        send_queue: asyncio.Queue = asyncio.Queue()
        with _webrtc_dc_lock:
            _webrtc_data_channels[session_id] = send_queue

        @pc.on("datachannel")
        def on_datachannel(channel):
            @channel.on("message")
            def on_message(message):
                if channel.label == "input":
                    if isinstance(message, str):
                        try:
                            evt = json.loads(message)

                            # ── NOVO: listar monitores ───────────────────────
                            if evt.get("t") == "list_monitors":
                                import mss as _mss
                                with _mss.mss() as sct:
                                    monitors = [
                                        {"id": i, "w": m["width"], "h": m["height"],
                                         "x": m["left"], "y": m["top"]}
                                        for i, m in enumerate(sct.monitors)
                                        if i > 0  # 0 = virtual (todos juntos)
                                    ]
                                reply = json.dumps({"t": "monitors_list", "monitors": monitors,
                                                    "current": ScreenTrack._monitor_index})
                                channel.send(reply)
                                return

                            # ── NOVO: trocar monitor ─────────────────────────
                            elif evt.get("t") == "switch_monitor":
                                idx = int(evt.get("index", 1))
                                import mss as _mss
                                with _mss.mss() as sct:
                                    count = len(sct.monitors) - 1  # exclui o virtual
                                if 1 <= idx <= count:
                                    ScreenTrack._monitor_index = idx
                                    channel.send(json.dumps({"t": "monitor_switched", "index": idx}))
                                return

                            # ── original: input de mouse/teclado ─────────────
                            threading.Thread(
                                target=_handle_input_event,
                                args=(evt, session_id),
                                daemon=True,
                            ).start()
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
                        except Exception: pass

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
    return result


# ─────────────────────────────────────────────
# IPC HTTP Server — 127.0.0.1:7070
# ─────────────────────────────────────────────
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

    def do_GET(self):
        if   self.path == "/status":          self._send_json(200, STATE.snapshot())
        elif self.path == "/notifications":   self._send_json(200, {"notifications": STATE.pop_notifications()})
        elif self.path == "/ping":            self._send_json(200, {"pong": True})
        elif self.path == "/webrtc/sessions": self._send_json(200, {"sessions": STATE.list_webrtc_sessions()})
        elif self.path == "/explorer/path":   self._send_json(200, {"path": get_explorer_path()})
        else:                                 self._send_json(404, {"error": "not found"})

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
# WebRTC HTTP Server — 0.0.0.0:7071
# ─────────────────────────────────────────────
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
        try:
            client_ip = self.client_address[0]
            network   = ipaddress.ip_network(WEBRTC_ALLOWED_SUBNET, strict=False)
            return ipaddress.ip_address(client_ip) in network
        except Exception:
            return False

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "): return False
        return auth[7:].strip() == self.config.get("token_hash", "")

    def _guard(self) -> bool:
        if not self._check_subnet():
            self._send_json(403, {"error": "Origem não permitida"}); return False
        if not self._check_auth():
            self._send_json(401, {"error": "Token inválido"}); return False
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
        # ── ADICIONADO: endpoint /command para execução remota pelo Django ─────
        # Reutiliza IPCHandler._run_command — mesma lógica, Session 0, sem WinRM.
        # O Django chama POST http://{ip}:7071/command com Bearer token.
        # Não altera nenhum outro comportamento existente.
        if self.path == "/command":
            body = self._read_json()
            logger.info(
                f"CMD remoto [{self.client_address[0]}] "
                f"[{body.get('type', 'powershell')}] {str(body.get('script', ''))[:80]}"
            )
            self._send_json(200, IPCHandler._run_command(None, body))
        # ── FIM DA ADIÇÃO ──────────────────────────────────────────────────────
        elif self.path == "/webrtc/offer":
            body = self._read_json()
            try:
                resp = _session.post("http://127.0.0.1:7071/webrtc/offer", json=body, timeout=15)
                resp.raise_for_status()
                self._send_json(200, resp.json())
            except requests.exceptions.ConnectionError:
                self._send_json(503, {"error": "Tray App offline"})
            except requests.exceptions.Timeout:
                self._send_json(504, {"error": "Tray App não respondeu"})
            except Exception as e:
                self._send_json(500, {"error": f"Erro interno: {e}"})
        elif self.path == "/webrtc/close":
            body       = self._read_json()
            session_id = body.get("session_id", "")
            if session_id:
                try: _session.post("http://127.0.0.1:7071/webrtc/close", json=body, timeout=5)
                except Exception: pass
                self._send_json(200, {"ok": True})
            else:
                self._send_json(400, {"error": "session_id obrigatório"})
        else:
            self._send_json(404, {"error": "not found"})


def start_webrtc_server(config: AgentConfig):
    WebRTCHandler.config = config
    server = HTTPServer(("0.0.0.0", WEBRTC_PORT), WebRTCHandler)
    logger.info(f"WebRTC server listening on 0.0.0.0:{WEBRTC_PORT}")
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
        STATE.logged_user  = data.get("logged_user", "")   # ── CORRIGIDO
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
            data = collect_hardware()                       # ── variável correta: data
            ok   = send_checkin(config, data)
            STATE.online       = True
            STATE.last_checkin = datetime.now()
            STATE.last_error   = "" if ok else "HTTP error on checkin"
            STATE.logged_user  = data.get("logged_user", "")  # ── CORRIGIDO: era hw_data
            logger.info(f"Check-in {'OK' if ok else 'FALHOU'} | user={STATE.logged_user}")
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


def webrtc_cleanup_loop():
    while True:
        time.sleep(600)
        STATE.cleanup_webrtc_sessions(max_age_seconds=3600)


def update_loop(config: AgentConfig):
    time.sleep(60)
    while True:
        try:
            url  = config.get("server_url") + config.get("ep_update")
            resp = _session.post(
                url,
                json={"current_version": VERSION, "machine_name": config.get("machine_name"),
                      "agent_type": AGENT_TYPE},
                headers=auth_headers(config),
                verify=ssl_verify(config), timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()
                if info.get("update_available"):
                    _apply_update(config, info)
        except Exception as e:
            logger.warning(f"Erro na verificação de update: {e}")
        time.sleep(UPDATE_CHECK_INTERVAL)


def _apply_update(config: AgentConfig, info: dict):
    download_url = info.get("download_url")
    remote_sha   = (info.get("sha256") or "").lower().strip()
    if not download_url:
        logger.warning("Update: download_url ausente"); return

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
    else:
        exe_path = Path(os.path.abspath(__file__)).resolve()

    exe_dir  = exe_path.parent
    new_exe  = exe_dir / "agent_service_new.exe"
    bat_path = exe_dir / "_update_service.bat"

    try:
        r = _session.get(download_url, headers=auth_headers(config),
                         verify=ssl_verify(config), timeout=120, stream=True)
        if r.status_code != 200:
            logger.error(f"Update: download falhou HTTP {r.status_code}"); return
        new_exe.write_bytes(r.content)

        if remote_sha:
            local_sha = hashlib.sha256(new_exe.read_bytes()).hexdigest().lower()
            if local_sha != remote_sha:
                logger.error("Update: SHA-256 inválido")
                new_exe.unlink(missing_ok=True); return

        service_name    = "TI-Agent"
        nssm_candidates = [exe_dir / "nssm.exe", Path("C:/Apps/TI-Agent/nssm.exe")]
        nssm_path       = next((str(p) for p in nssm_candidates if p.exists()), None)
        stop_cmd    = f'"{nssm_path}" stop {service_name}'    if nssm_path else f'sc stop {service_name}'
        restart_cmd = f'"{nssm_path}" start {service_name}'   if nssm_path else f'sc start {service_name}'

        bat = (f'@echo off\n{stop_cmd}\ntimeout /t 5 /nobreak > nul\n'
               f'set R=0\n:wait\ntasklist /FI "IMAGENAME eq agent_service.exe" 2>nul | find /I "agent_service.exe" > nul\n'
               f'if %ERRORLEVEL%==0 ( if %R% lss 15 ( set /A R+=1 & timeout /t 1 /nobreak > nul & goto wait ) )\n'
               f'if exist "{exe_path}.bak" del /F /Q "{exe_path}.bak"\n'
               f'if exist "{exe_path}" move /Y "{exe_path}" "{exe_path}.bak"\n'
               f'move /Y "{new_exe}" "{exe_path}"\n'
               f'if %ERRORLEVEL% neq 0 ( if exist "{exe_path}.bak" move /Y "{exe_path}.bak" "{exe_path}" & del /F /Q "%~f0" & exit /b 1 )\n'
               f'{restart_cmd}\ndel /F /Q "%~f0"\nexit /b 0\n')
        bat_path.write_text(bat, encoding="ascii", errors="replace")

        subprocess.Popen(["cmd.exe", "/c", str(bat_path)],
                         creationflags=(subprocess.CREATE_NO_WINDOW |
                                        subprocess.DETACHED_PROCESS |
                                        subprocess.CREATE_NEW_PROCESS_GROUP),
                         close_fds=True)
        time.sleep(1)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Update: falha — {e}")
        for tmp in [new_exe, bat_path]:
            try:
                if tmp.exists(): tmp.unlink()
            except Exception: pass


# ─────────────────────────────────────────────
# Ponto de entrada
# ─────────────────────────────────────────────
def main():
    global _CONFIG   # ── expõe para snapshot() usar a instância real

    token = None
    for arg in sys.argv[1:]:
        if arg.startswith("--token="):
            token = arg.split("=", 1)[1]

    config  = AgentConfig()
    _CONFIG = config   # ── atribui globalmente antes de qualquer thread

    if token:
        config.set("token_hash", hashlib.sha256(token.encode()).hexdigest())

    if not config.get("token_hash"):
        logger.error("Token não configurado. Encerrando.")
        sys.exit(1)

    logger.info(f"=== AgentService v{VERSION} ({AGENT_TYPE}) iniciando ===")
    logger.info(f"Máquina: {config.get('machine_name')} | Servidor: {config.get('server_url')}")
    logger.info(f"token_hash presente: {'sim' if config.get('token_hash') else 'NÃO'}")

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