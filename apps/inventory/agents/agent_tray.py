# agent_tray.py — v3.3.1
# Tray App: roda na sessão do usuário, recebe WebRTC do agent_service,
# exibe notificações nativas e gerencia chamados de suporte.

import os
import sys
import re
import time
import json
import hashlib
import asyncio
import threading
import platform
import tkinter as tk
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import requests
import av
import mss
import numpy as np

from notification import ToastNotification
from chamados import ChamadosManager

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
except ImportError:
    print("ERRO: pip install pystray pillow")
    sys.exit(1)

VERSION       = "3.3.1"
IPC_URL       = "http://127.0.0.1:7070"
WEBRTC_PORT   = 7071   # porta local — agent_service delega para cá
POLL_INTERVAL = 8

LOG_DIR = Path(os.path.dirname(__file__)) / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "tray.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("AgentTray")


# ═════════════════════════════════════════════════════════════════════════════
# WebRTC — captura de tela (roda na sessão do usuário ✓)
# ═════════════════════════════════════════════════════════════════════════════

_webrtc_data_channels: dict = {}
_webrtc_dc_lock              = threading.Lock()
_file_buffers:         dict = {}
_file_buffers_lock           = threading.Lock()


class ScreenTrack:
    """Captura a tela principal com mss — funciona na sessão do usuário."""
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
        return object.__new__(DynTrack)

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
    """Processa eventos de mouse/teclado recebidos via WebRTC."""
    try:
        import ctypes
        import win32api
        import win32con
        user32 = ctypes.windll.user32
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        t      = event.get("t")

        def abs_xy(e):
            return (max(0, min(sw - 1, int(e.get("x", 0) * sw))),
                    max(0, min(sh - 1, int(e.get("y", 0) * sh))))

        if t == "mm":
            win32api.SetCursorPos(abs_xy(event))
        elif t == "mc":
            x, y = abs_xy(event)
            win32api.SetCursorPos((x, y))
            b = event.get("b", "left")
            if b == "left":
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y)
            elif b == "right":
                win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, x, y)
                win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, x, y)
        elif t == "mdc":
            x, y = abs_xy(event)
            win32api.SetCursorPos((x, y))
            for _ in range(2):
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y)
        elif t == "md":
            x, y = abs_xy(event)
            win32api.SetCursorPos((x, y))
            if event.get("b") == "left":
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y)
        elif t == "mu":
            x, y = abs_xy(event)
            win32api.SetCursorPos((x, y))
            if event.get("b") == "left":
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y)
        elif t == "mw":
            delta = int(event.get("delta", 0) * 120)
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta)
        elif t == "kd":
            vk = event.get("vk")
            if vk:
                win32api.keybd_event(vk, 0, 0, 0)
        elif t == "ku":
            vk = event.get("vk")
            if vk:
                win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        elif t == "cad":
            # Ctrl+Alt+Del via SendSAS (única forma válida no Windows)
            # sas.dll está disponível em C:\Windows\System32\sas.dll
            try:
                import ctypes
                sas = ctypes.WinDLL("sas.dll")
                # SendSAS(FALSE) — FALSE = não veio de teclado físico
                sas.SendSAS(0)
                logger.info("CAD enviado via SendSAS")
            except Exception as cad_err:
                logger.warning(f"SendSAS falhou ({cad_err}), tentando WinLogon...")
                try:
                    # Fallback: post WM_HOTKEY para WinLogon (Session 0 apenas)
                    import subprocess
                    subprocess.run(
                        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                         "(New-Object -ComObject Shell.Application).WindowsSecurity()"],
                        timeout=5, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                except Exception as e2:
                    logger.error(f"CAD fallback falhou: {e2}")
        elif t == 'screen_lock':
            import tkinter as tk, threading
            def show_lock():
                root = tk.Tk()
                root.attributes('-fullscreen', True, '-topmost', True)
                root.configure(bg='black')
                root.overrideredirect(True)
                root._lock_active = True
                root.mainloop()

            threading.Thread(target=show_lock, daemon=True).start()

        elif t == 'screen_unlock':
            # Fecha a janela de bloqueio se existir
            import tkinter as tk
            for w in tk._default_root.winfo_children() if tk._default_root else []:
                w.destroy()
    except Exception as e:
        logger.error(f"Input event error: {e}")


def _handle_file_chunk(data: bytes):
    """Processa chunk binário de transferência de arquivo."""
    with _file_buffers_lock:
        if len(data) < 4:
            return
        fid_len = int.from_bytes(data[:2], "big")
        fid     = data[2:2 + fid_len].decode("utf-8", errors="replace")
        chunk   = data[2 + fid_len:]
        if fid not in _file_buffers:
            _file_buffers[fid] = bytearray()
        _file_buffers[fid].extend(chunk)


def _handle_file_message(msg: dict, session_id: str):
    """Finaliza e salva arquivo recebido via WebRTC."""
    fid       = msg.get("id", "")
    file_name = msg.get("name", "arquivo")
    with _file_buffers_lock:
        data = bytes(_file_buffers.pop(fid, b""))
    try:
        desktop   = Path.home() / "Desktop"
        safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", file_name).strip(". ") or "arquivo"
        dest      = desktop / safe_name
        dest.write_bytes(data)
        logger.info(f"WebRTC file: '{file_name}' salvo em '{dest}'")
        ack = json.dumps({"t": "file_done", "id": fid})
    except Exception as e:
        logger.error(f"WebRTC file erro: {e}")
        ack = json.dumps({"t": "file_err", "id": fid, "reason": str(e)})
    with _webrtc_dc_lock:
        queue = _webrtc_data_channels.get(session_id)
    if queue:
        try:
            queue.put_nowait(ack)
        except Exception:
            pass


def _handle_webrtc_offer(body: dict) -> dict:
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
                logger.info(f"WebRTC: H264 ({len(h264)} perfis)")
        except Exception as e:
            logger.warning(f"WebRTC: addTransceiver falhou ({e}), usando addTrack")
            pc.addTrack(track)

        send_queue: asyncio.Queue = asyncio.Queue()
        with _webrtc_dc_lock:
            _webrtc_data_channels[session_id] = send_queue

        @pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"WebRTC: canal '{channel.label}' ({session_id[:8]}…)")

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
                            threading.Thread(
                                target=_handle_file_message,
                                args=(json.loads(message), session_id),
                                daemon=True,
                            ).start()
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

        offer  = RTCSessionDescription(sdp=sdp_str, type=sdp_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        logger.info(f"WebRTC: SDP answer gerado ({session_id[:8]}…)")
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
# Servidor WebRTC local — 127.0.0.1:7071
# ─────────────────────────────────────────────
class WebRTCLocalHandler(BaseHTTPRequestHandler):
    """Recebe SDP offer do agent_service via loopback."""

    def log_message(self, fmt, *args):
        logger.debug(f"WebRTC-local {fmt % args}")

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "version": VERSION})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/webrtc/offer":
            body = self._read_json()
            try:
                result = _handle_webrtc_offer(body)
                self._send_json(200, result)
            except Exception as e:
                logger.exception(f"WebRTC offer error: {e}")
                self._send_json(500, {"error": str(e)})
        elif self.path == "/webrtc/close":
            body       = self._read_json()
            session_id = body.get("session_id", "")
            if session_id:
                with _webrtc_dc_lock:
                    _webrtc_data_channels.pop(session_id, None)
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})


def start_webrtc_local_server():
    server = HTTPServer(("127.0.0.1", WEBRTC_PORT), WebRTCLocalHandler)
    logger.info(f"WebRTC local server listening on 127.0.0.1:{WEBRTC_PORT}")
    server.serve_forever()


# ─────────────────────────────────────────────
# Cliente IPC
# ─────────────────────────────────────────────
class IPCClient:
    _session = requests.Session()

    @classmethod
    def _get(cls, path, timeout=3):
        try:
            r = cls._session.get(f"{IPC_URL}{path}", timeout=timeout)
            return r.json() if r.ok else None
        except Exception:
            return None

    @classmethod
    def _post(cls, path, body=None, timeout=5):
        try:
            r = cls._session.post(f"{IPC_URL}{path}", json=body or {}, timeout=timeout)
            return r.json() if r.ok else None
        except Exception:
            return None

    @classmethod
    def get_status(cls):        return cls._get("/status")

    @classmethod
    def get_notifications(cls):
        data = cls._get("/notifications")
        return data.get("notifications", []) if data else []

    @classmethod
    def ack_notification(cls, notif_id):
        cls._post("/notifications/ack", {"id": notif_id})

    @classmethod
    def force_sync(cls):
        result = cls._post("/sync")
        return bool(result and result.get("ok"))

    @classmethod
    def is_service_running(cls):
        return cls._get("/ping", timeout=2) is not None

    @classmethod
    def run_command(cls, cmd_type, script, timeout=30):
        return cls._post("/command", {"type": cmd_type, "script": script, "timeout": timeout})


# ─────────────────────────────────────────────
# Janela de Status
# ─────────────────────────────────────────────
class StatusWindow:
    _instance = None

    @classmethod
    def open(cls, tray_app):
        if cls._instance and cls._instance.alive:
            cls._instance.window.lift()
            return
        cls._instance = cls(tray_app)

    def __init__(self, tray_app):
        self.tray_app = tray_app
        self.alive    = True
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        self.window = tk.Tk()
        self.window.title("Inventory Agent — Status")
        self.window.geometry("440x360")
        self.window.resizable(False, False)
        self.window.configure(bg="#0f172a")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        header = tk.Frame(self.window, bg="#1e293b", pady=16, padx=20)
        header.pack(fill=tk.X)
        tk.Label(header, text="Inventory Agent", fg="white", bg="#1e293b",
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        tk.Label(header, text=f"v{VERSION}", fg="#64748b", bg="#1e293b",
                 font=("Segoe UI", 9)).pack(side=tk.RIGHT)

        body = tk.Frame(self.window, bg="#0f172a", padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        def row(label, default="—"):
            f = tk.Frame(body, bg="#0f172a")
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, fg="#64748b", bg="#0f172a",
                     font=("Segoe UI", 9), width=18, anchor="w").pack(side=tk.LEFT)
            val = tk.Label(f, text=default, fg="#e2e8f0", bg="#0f172a",
                           font=("Segoe UI", 9, "bold"), anchor="w")
            val.pack(side=tk.LEFT)
            return val

        self.lbl_status  = row("Status serviço")
        self.lbl_machine = row("Máquina")
        self.lbl_checkin = row("Último check-in")
        self.lbl_notif   = row("Notif. pendentes")
        self.lbl_webrtc  = row("Sessões WebRTC")
        self.lbl_version = row("Versão")
        self.lbl_error   = row("Último erro")

        btn_frame = tk.Frame(self.window, bg="#1e293b", pady=12, padx=20)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        def btn(parent, text, cmd, accent="#334155"):
            b = tk.Button(parent, text=text, command=cmd,
                          bg=accent, fg="white", relief="flat",
                          font=("Segoe UI", 9), padx=12, pady=6)
            b.pack(side=tk.LEFT, padx=4)
            return b

        btn(btn_frame, "⚡ Sync agora", self._sync, "#0369a1")
        btn(btn_frame, "📄 Logs",       self._open_logs)

        self._refresh()
        self.window.mainloop()

    def _refresh(self):
        if not self.alive:
            return
        status = IPCClient.get_status()
        if status:
            online = status.get("online", False)
            self.lbl_status.config(
                text="🟢 Online" if online else "🔴 Offline",
                fg="#4ade80" if online else "#f87171")
            self.lbl_machine.config(text=status.get("machine", "—"))
            checkin = status.get("last_checkin")
            self.lbl_checkin.config(
                text=checkin[:19].replace("T", " ") if checkin else "—")
            self.lbl_notif.config(text=str(status.get("pending_notifications", 0)))
            self.lbl_version.config(text=status.get("version", VERSION))
            err = status.get("last_error", "")
            self.lbl_error.config(
                text=(err[:40] + "…") if len(err) > 40 else (err or "Nenhum"),
                fg="#f87171" if err else "#4ade80")
            self.lbl_webrtc.config(
                text=str(len(_webrtc_data_channels)),
                fg="#4ade80" if _webrtc_data_channels else "#64748b")
        else:
            self.lbl_status.config(text="⚫ Serviço offline", fg="#94a3b8")
        self.window.after(5000, self._refresh)

    def _sync(self):
        ok = IPCClient.force_sync()
        ToastNotification.show(
            title="Sync",
            message="Sincronização iniciada!" if ok else "Serviço não respondeu.",
            notif_type="success" if ok else "error", duration=5)

    def _open_logs(self):
        try:
            if platform.system() == "Windows":
                os.startfile(str(LOG_DIR))
        except Exception as e:
            logger.error(e)

    def _on_close(self):
        self.alive = False
        StatusWindow._instance = None
        self.window.destroy()


# ─────────────────────────────────────────────
# Janela de Chamados
# ─────────────────────────────────────────────
class ChamadosWindow:
    _instance = None

    @classmethod
    def open(cls, server_url, token_hash):
        if cls._instance and cls._instance.alive:
            cls._instance.window.lift()
            return
        cls._instance = cls(server_url, token_hash)

    def __init__(self, server_url, token_hash):
        self.server_url = server_url.rstrip("/")
        self.token_hash = token_hash
        self.alive      = True
        self._tickets   = []
        self._selected  = None
        self._historico = []
        self._email     = os.environ.get("AGENT_USER_EMAIL", "")
        threading.Thread(target=self._build, daemon=True).start()

    # ── helpers de API ──────────────────────────────────────
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token_hash}",
            "Content-Type":  "application/json",
        }

    def _api_get(self, path, params=None):
        r = requests.get(
            f"{self.server_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=10,
            verify=False,
        )
        r.raise_for_status()
        return r.json()

    def _api_post(self, path, body):
        r = requests.post(
            f"{self.server_url}{path}",
            headers=self._headers(),
            json=body,
            timeout=10,
            verify=False,
        )
        r.raise_for_status()
        return r.json()

    # ── build da UI ──────────────────────────────────────────
    def _build(self):
        win = tk.Tk()
        self.window = win
        win.title("Meus Chamados")
        win.geometry("980x640")
        win.minsize(800, 520)
        win.configure(bg="#f1f5f9")
        win.protocol("WM_DELETE_WINDOW", self._on_close)

        main = tk.Frame(win, bg="#f1f5f9")
        main.pack(fill=tk.BOTH, expand=True)

        # ── SIDEBAR ─────────────────────────────────────────
        sidebar = tk.Frame(main, bg="#1e293b", width=290)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Cabeçalho sidebar
        hdr = tk.Frame(sidebar, bg="#0f172a", pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="🎫  Chamados", font=("Segoe UI", 12, "bold"),
                 bg="#0f172a", fg="#f8fafc").pack(side=tk.LEFT, padx=14)
        tk.Button(
            hdr, text="+ Novo",
            font=("Segoe UI", 9, "bold"),
            bg="#1a73e8", fg="white",
            relief=tk.FLAT, padx=10, pady=4,
            cursor="hand2",
            command=self._abrir_novo_ticket,
        ).pack(side=tk.RIGHT, padx=10)

        # Campo de e-mail + botão carregar
        email_frm = tk.Frame(sidebar, bg="#1e293b", pady=6, padx=10)
        email_frm.pack(fill=tk.X)
        tk.Label(email_frm, text="Seu e-mail:", font=("Segoe UI", 8),
                 bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.email_var = tk.StringVar(value=self._email)
        tk.Entry(
            email_frm,
            textvariable=self.email_var,
            font=("Segoe UI", 9),
            bg="#334155", fg="white",
            insertbackground="white",
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground="#475569",
        ).pack(fill=tk.X, pady=(2, 4))
        tk.Button(
            email_frm, text="🔄  Carregar chamados",
            font=("Segoe UI", 8),
            bg="#334155", fg="#94a3b8",
            relief=tk.FLAT, pady=4,
            cursor="hand2",
            command=self._carregar_tickets,
        ).pack(fill=tk.X)

        # Lista scrollável de tickets
        lista_frm = tk.Frame(sidebar, bg="#1e293b")
        lista_frm.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        sb = tk.Scrollbar(lista_frm, orient=tk.VERTICAL, bg="#334155",
                          troughcolor="#1e293b", bd=0)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.lista_canvas = tk.Canvas(lista_frm, bg="#1e293b", bd=0,
                                      highlightthickness=0,
                                      yscrollcommand=sb.set)
        self.lista_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lista_canvas.yview)

        self.lista_inner = tk.Frame(self.lista_canvas, bg="#1e293b")
        self.lista_canvas.create_window((0, 0), window=self.lista_inner, anchor="nw")
        self.lista_inner.bind(
            "<Configure>",
            lambda e: self.lista_canvas.configure(
                scrollregion=self.lista_canvas.bbox("all")),
        )

        # ── CONTEÚDO DIREITO ─────────────────────────────────
        content = tk.Frame(main, bg="#f1f5f9")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Cabeçalho do ticket selecionado
        self.ticket_hdr = tk.Frame(
            content, bg="#ffffff",
            highlightthickness=1, highlightbackground="#e2e8f0",
        )
        self.ticket_hdr.pack(fill=tk.X)

        self.lbl_assunto = tk.Label(
            self.ticket_hdr,
            text="← Selecione um chamado na lista",
            font=("Segoe UI", 12, "bold"),
            bg="#ffffff", fg="#1e293b",
            pady=14, padx=20, anchor="w",
        )
        self.lbl_assunto.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.lbl_status_ticket = tk.Label(
            self.ticket_hdr, text="",
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff", fg="#64748b",
            padx=16,
        )
        self.lbl_status_ticket.pack(side=tk.RIGHT)

        # Área de histórico (balões)
        hist_wrap = tk.Frame(content, bg="#f1f5f9")
        hist_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(10, 0))

        hist_sb = tk.Scrollbar(hist_wrap, orient=tk.VERTICAL)
        hist_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.hist_canvas = tk.Canvas(
            hist_wrap, bg="#f1f5f9", bd=0,
            highlightthickness=0,
            yscrollcommand=hist_sb.set,
        )
        self.hist_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_sb.config(command=self.hist_canvas.yview)

        self.hist_inner = tk.Frame(self.hist_canvas, bg="#f1f5f9")
        self.hist_canvas.create_window((0, 0), window=self.hist_inner, anchor="nw")
        self.hist_inner.bind(
            "<Configure>",
            lambda e: self.hist_canvas.configure(
                scrollregion=self.hist_canvas.bbox("all")),
        )

        # Área de resposta
        reply_frm = tk.Frame(
            content, bg="#ffffff",
            highlightthickness=1, highlightbackground="#e2e8f0",
        )
        reply_frm.pack(fill=tk.X, padx=14, pady=10)

        tk.Label(reply_frm, text="Responder:", font=("Segoe UI", 9, "bold"),
                 bg="#ffffff", fg="#374151").pack(anchor="w", padx=12, pady=(8, 2))

        self.reply_text = tk.Text(
            reply_frm, height=4,
            font=("Segoe UI", 10),
            relief=tk.FLAT, bg="#f8fafc",
            bd=0, highlightthickness=1,
            highlightbackground="#e2e8f0",
            padx=10, pady=8,
        )
        self.reply_text.pack(fill=tk.X, padx=12, pady=(0, 6))
        self._placeholder_text = "Digite sua resposta aqui…"
        self.reply_text.insert("1.0", self._placeholder_text)
        self.reply_text.config(fg="#9ca3af")
        self.reply_text.bind("<FocusIn>",  self._reply_focus_in)
        self.reply_text.bind("<FocusOut>", self._reply_focus_out)

        tk.Button(
            reply_frm, text="Enviar Resposta  ➤",
            font=("Segoe UI", 9, "bold"),
            bg="#1a73e8", fg="white",
            relief=tk.FLAT, padx=16, pady=6,
            cursor="hand2",
            command=self._enviar_resposta,
        ).pack(anchor="e", padx=12, pady=(0, 10))

        # Carrega tickets ao abrir
        win.after(200, self._carregar_tickets)
        win.mainloop()

    # ── placeholder ─────────────────────────────────────────
    def _reply_focus_in(self, _e):
        if self.reply_text.get("1.0", tk.END).strip() == self._placeholder_text:
            self.reply_text.delete("1.0", tk.END)
            self.reply_text.config(fg="#1e293b")

    def _reply_focus_out(self, _e):
        if not self.reply_text.get("1.0", tk.END).strip():
            self.reply_text.insert("1.0", self._placeholder_text)
            self.reply_text.config(fg="#9ca3af")

    # ── carregar lista ───────────────────────────────────────
    def _carregar_tickets(self):
        email = self.email_var.get().strip()
        if not email:
            return
        self._email = email

        def fetch():
            try:
                data = self._api_get("/tickets/api/agent/list/", params={"email": email})
                self.window.after(0, lambda: self._render_lista(data.get("tickets", [])))
            except Exception as ex:
                logger.error(f"Erro ao carregar tickets: {ex}")
                ToastNotification.show(
                    title="Erro", message=f"Não foi possível carregar chamados: {ex}",
                    notif_type="error", duration=5)

        threading.Thread(target=fetch, daemon=True).start()

    def _render_lista(self, tickets):
        self._tickets = tickets
        for w in self.lista_inner.winfo_children():
            w.destroy()

        if not tickets:
            tk.Label(
                self.lista_inner,
                text="Nenhum chamado encontrado.",
                font=("Segoe UI", 9, "italic"),
                bg="#1e293b", fg="#64748b",
                pady=24,
            ).pack()
            return

        for t in tickets:
            self._render_ticket_card(t)

        # Seleciona o primeiro automaticamente
        if tickets and self._selected is None:
            self._selecionar_ticket(tickets[0])

    def _render_ticket_card(self, t):
        is_sel  = self._selected and self._selected["id"] == t["id"]
        bg_base = "#2d4a7a" if is_sel else "#1e293b"
        bg_hvr  = "#253352"
        cor     = t.get("status_cor", "#64748b")

        card = tk.Frame(self.lista_inner, bg=bg_base, cursor="hand2",
                        highlightthickness=0)
        card.pack(fill=tk.X, padx=0, pady=1)

        # Faixa lateral colorida com status
        tk.Frame(card, bg=cor, width=4).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(card, bg=bg_base, padx=10, pady=10)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(body, text=f"#{t['numero']}", font=("Segoe UI", 8, "bold"),
                 bg=bg_base, fg="#94a3b8", anchor="w").pack(fill=tk.X)

        assunto_txt = t["assunto"][:44] + ("…" if len(t["assunto"]) > 44 else "")
        tk.Label(body, text=assunto_txt, font=("Segoe UI", 9, "bold"),
                 bg=bg_base, fg="#f1f5f9", anchor="w",
                 wraplength=238).pack(fill=tk.X)

        meta = tk.Frame(body, bg=bg_base)
        meta.pack(fill=tk.X, pady=(4, 0))
        tk.Label(meta, text=t["status"], font=("Segoe UI", 8),
                 bg=bg_base, fg=cor, anchor="w").pack(side=tk.LEFT)
        tk.Label(meta, text=t["criado_em"], font=("Segoe UI", 7),
                 bg=bg_base, fg="#64748b", anchor="e").pack(side=tk.RIGHT)

        # Bind click + hover em todos os filhos
        all_widgets = [card, body, meta] + body.winfo_children() + meta.winfo_children()

        def on_click(_e, ticket=t):
            self._selecionar_ticket(ticket)

        def on_enter(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in all_widgets:
                    try:
                        w.config(bg=bg_hvr)
                    except Exception:
                        pass

        def on_leave(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in all_widgets:
                    try:
                        w.config(bg="#1e293b")
                    except Exception:
                        pass

        for w in all_widgets:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>",    on_enter)
            w.bind("<Leave>",    on_leave)

    # ── selecionar ticket ────────────────────────────────────
    def _selecionar_ticket(self, ticket):
        self._selected = ticket
        self.lbl_assunto.config(text=f"#{ticket['numero']}  —  {ticket['assunto']}")
        self.lbl_status_ticket.config(text=ticket["status"])

        # Redesenha cards para refletir seleção
        self._render_lista(self._tickets)

        def fetch():
            try:
                data = self._api_get(f"/tickets/api/agent/{ticket['id']}/")
                self.window.after(0, lambda: self._render_historico(
                    data.get("historico", [])))
            except Exception as ex:
                logger.error(f"Erro ao carregar histórico: {ex}")

        threading.Thread(target=fetch, daemon=True).start()

    # ── renderizar histórico ─────────────────────────────────
    def _render_historico(self, historico):
        self._historico = historico
        for w in self.hist_inner.winfo_children():
            w.destroy()

        if not historico:
            tk.Label(
                self.hist_inner,
                text="Nenhuma mensagem ainda. Seja o primeiro a responder!",
                font=("Segoe UI", 9, "italic"),
                bg="#f1f5f9", fg="#94a3b8",
                pady=24,
            ).pack()
            return

        for acao in historico:           # já vem mais recente primeiro
            self._render_balao(acao)

        self.hist_canvas.update_idletasks()
        self.hist_canvas.yview_moveto(0) # topo = mais recente

    def _render_balao(self, acao):
        is_staff = acao.get("is_staff", False)
        # Staff (suporte) → direita azul  |  cliente → esquerda branco
        anchor  = "e" if is_staff else "w"
        bg_msg  = "#1a73e8" if is_staff else "#ffffff"
        fg_msg  = "#ffffff"  if is_staff else "#1e293b"

        outer = tk.Frame(self.hist_inner, bg="#f1f5f9")
        outer.pack(fill=tk.X, padx=12, pady=5)

        # Linha de meta (nome + hora)
        meta = tk.Frame(outer, bg="#f1f5f9")
        meta.pack(fill=tk.X)
        if is_staff:
            tk.Label(meta, text=acao["criado_em"], font=("Segoe UI", 7),
                     bg="#f1f5f9", fg="#94a3b8").pack(side=tk.LEFT, padx=4)
            tk.Label(meta, text=acao["autor"], font=("Segoe UI", 8, "bold"),
                     bg="#f1f5f9", fg="#475569").pack(side=tk.RIGHT)
        else:
            tk.Label(meta, text=acao["autor"], font=("Segoe UI", 8, "bold"),
                     bg="#f1f5f9", fg="#475569").pack(side=tk.LEFT)
            tk.Label(meta, text=acao["criado_em"], font=("Segoe UI", 7),
                     bg="#f1f5f9", fg="#94a3b8").pack(side=tk.RIGHT, padx=4)

        # Balão
        bubble = tk.Label(
            outer,
            text=acao["conteudo"],
            font=("Segoe UI", 10),
            bg=bg_msg, fg=fg_msg,
            wraplength=520,
            justify=tk.LEFT,
            anchor="w",
            padx=14, pady=10,
            relief=tk.FLAT,
        )
        bubble.pack(anchor=anchor, pady=(2, 0))

    # ── enviar resposta ──────────────────────────────────────
    def _enviar_resposta(self):
        if not self._selected:
            ToastNotification.show(title="Aviso",
                                   message="Selecione um chamado antes de responder.",
                                   notif_type="warning", duration=4)
            return

        conteudo = self.reply_text.get("1.0", tk.END).strip()
        if not conteudo or conteudo == self._placeholder_text:
            return

        email = self.email_var.get().strip()

        def send():
            try:
                data = self._api_post(
                    f"/tickets/api/agent/{self._selected['id']}/reply/",
                    {"email": email, "conteudo": conteudo},
                )
                if data.get("ok"):
                    nova_acao = data["acao"]
                    self.window.after(0, lambda: self._append_acao(nova_acao))
                    self.window.after(0, self._limpar_reply)
                    ToastNotification.show(
                        title="Resposta enviada",
                        message=f"Ticket #{self._selected['numero']} atualizado.",
                        notif_type="success", duration=4)
                else:
                    ToastNotification.show(title="Erro",
                                           message=data.get("error", "Erro desconhecido"),
                                           notif_type="error", duration=5)
            except Exception as ex:
                logger.error(f"Erro ao responder: {ex}")
                ToastNotification.show(title="Erro", message=str(ex),
                                       notif_type="error", duration=5)

        threading.Thread(target=send, daemon=True).start()

    def _append_acao(self, acao):
        """Insere nova ação no topo sem recarregar tudo."""
        self._historico.insert(0, acao)
        for w in self.hist_inner.winfo_children():
            w.destroy()
        for a in self._historico:
            self._render_balao(a)
        self.hist_canvas.update_idletasks()
        self.hist_canvas.yview_moveto(0)

    def _limpar_reply(self):
        self.reply_text.delete("1.0", tk.END)
        self.reply_text.insert("1.0", self._placeholder_text)
        self.reply_text.config(fg="#9ca3af")

    # ── abrir novo ticket ────────────────────────────────────
    def _abrir_novo_ticket(self):
        NovoTicketModal(self)

    def _on_close(self):
        self.alive = False
        ChamadosWindow._instance = None
        self.window.destroy()


# ─────────────────────────────────────────────
# Modal: Novo Ticket
# ─────────────────────────────────────────────
class NovoTicketModal:
    def __init__(self, parent: ChamadosWindow):
        self.parent = parent
        win = tk.Toplevel(parent.window)
        self.window = win
        win.title("Abrir Novo Chamado")
        win.geometry("460x420")
        win.resizable(False, False)
        win.configure(bg="#f8fafc")
        win.grab_set()  # modal

        pad = {"padx": 18, "pady": 3}

        tk.Label(win, text="Novo Chamado", font=("Segoe UI", 13, "bold"),
                 bg="#f8fafc", fg="#0f172a").pack(pady=(16, 8))

        def lbl(text):
            tk.Label(win, text=text, font=("Segoe UI", 9),
                     bg="#f8fafc", fg="#374151", anchor="w").pack(fill=tk.X, **pad)

        def entry_var():
            var = tk.StringVar()
            e = tk.Entry(
                win, textvariable=var,
                font=("Segoe UI", 10), relief=tk.FLAT,
                bd=0, highlightthickness=1,
                highlightbackground="#d1d5db",
                bg="#ffffff",
            )
            e.pack(fill=tk.X, padx=18, pady=(0, 6))
            return var

        lbl("E-mail do solicitante *")
        self.email_var = entry_var()
        self.email_var.set(parent.email_var.get())

        lbl("Tipo do chamado (Serviço)  — opcional")
        self.tipo_var = entry_var()

        lbl("Assunto *")
        self.assunto_var = entry_var()

        lbl("Descrição *")
        self.desc_widget = tk.Text(
            win, height=5,
            font=("Segoe UI", 10), relief=tk.FLAT,
            bd=0, highlightthickness=1,
            highlightbackground="#d1d5db",
            bg="#ffffff", padx=8, pady=6,
        )
        self.desc_widget.pack(fill=tk.X, padx=18, pady=(0, 10))

        btns = tk.Frame(win, bg="#f8fafc")
        btns.pack(fill=tk.X, padx=18, pady=6)
        tk.Button(btns, text="Cancelar", command=win.destroy,
                  font=("Segoe UI", 10), bg="#e5e7eb",
                  relief=tk.FLAT, padx=12, pady=6).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btns, text="Abrir Chamado", command=self._submit,
                  font=("Segoe UI", 10, "bold"), bg="#1a73e8", fg="white",
                  relief=tk.FLAT, padx=12, pady=6).pack(side=tk.RIGHT)

    def _submit(self):
        from tkinter import messagebox
        email    = self.email_var.get().strip()
        tipo     = self.tipo_var.get().strip()
        assunto  = self.assunto_var.get().strip()
        descricao = self.desc_widget.get("1.0", tk.END).strip()

        if not email or not assunto or not descricao:
            messagebox.showerror("Campos obrigatórios",
                                 "Preencha: E-mail, Assunto e Descrição.")
            return

        def send():
            try:
                data = self.parent._api_post(
                    "/tickets/api/agent/criar/",
                    {
                        "email_solicitante": email,
                        "tipo_chamado":      tipo,
                        "assunto":           assunto,
                        "descricao":         descricao,
                    },
                )
                if data.get("ok"):
                    ToastNotification.show(
                        title="Chamado aberto!",
                        message=f"Ticket #{data['numero']} criado com sucesso.",
                        notif_type="success", duration=5)
                    self.window.after(0, self.window.destroy)
                    # Recarrega a lista após 500ms
                    self.parent.window.after(500, self.parent._carregar_tickets)
                else:
                    ToastNotification.show(title="Erro",
                                           message=data.get("error", "Erro desconhecido"),
                                           notif_type="error", duration=5)
            except Exception as ex:
                logger.error(f"NovoTicket erro: {ex}")
                ToastNotification.show(title="Erro", message=str(ex),
                                       notif_type="error", duration=5)

        threading.Thread(target=send, daemon=True).start()


# ─────────────────────────────────────────────
# Ícone do System Tray
# ─────────────────────────────────────────────
class TrayIcon:
    STATUS_COLORS = {
        "online":  (34, 197, 94),
        "offline": (239, 68, 68),
        "unknown": (148, 163, 184),
    }

    def __init__(self):
        self.icon         = None
        self._status      = "unknown"
        self._notif_count = 0

    def _make_image(self, status):
        size  = 64
        img   = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(img)
        color = self.STATUS_COLORS.get(status, self.STATUS_COLORS["unknown"])
        draw.ellipse([6, 6, 58, 58], fill=color + (255,))
        draw.ellipse([6, 6, 58, 58], outline=(255, 255, 255, 180), width=3)
        if self._notif_count > 0:
            draw.ellipse([40, 2, 62, 24], fill=(239, 68, 68, 255))
            draw.text((47, 4), str(min(self._notif_count, 9)), fill="white")
        return img

    def update_status(self, status, notif_count=0):
        self._status      = status
        self._notif_count = notif_count
        if self.icon:
            self.icon.icon  = self._make_image(status)
            label           = {"online": "Online", "offline": "Offline"}.get(status, "...")
            notif_str       = f" ({notif_count} notif)" if notif_count else ""
            self.icon.title = f"Inventory Agent — {label}{notif_str}"

    def _build_menu(self):
        return pystray.Menu(
            item("📊 Status",      lambda i, it: StatusWindow.open(self)),
            item("🎫 Chamados",    lambda i, it: self._open_chamados(), default=True,),
            item("⚡ Forçar Sync", lambda i, it: self._force_sync()),
            pystray.Menu.SEPARATOR,
            item("❌ Sair",        lambda i, it: self._quit()),
        )

    def _open_chamados(self):
        """Busca server_url, token_hash e logged_user do agent_service via IPC."""
        status = IPCClient.get_status()
        if not status:
            logger.warning("Chamados: agent_service não respondeu via IPC")
            return

        server_url  = status.get("server_url", "").rstrip("/")
        token_hash  = status.get("token_hash", "")
        logged_user = status.get("logged_user", "")

        if not server_url or not token_hash:
            logger.warning(
                f"Chamados: server_url={server_url!r} "
                f"token_hash={'presente' if token_hash else 'AUSENTE'} "
                "— agent_service pode não ter carregado as variáveis NSSM ainda"
            )
            return

        ChamadosManager.open(
            server_url=server_url,
            token_hash=token_hash,
            logged_user=logged_user,
        )

    def _force_sync(self):
        ok = IPCClient.force_sync()
        ToastNotification.show(
            title="Sync",
            message="Sincronização iniciada!" if ok else "Serviço indisponível.",
            notif_type="success" if ok else "error", duration=5)

    def _open_logs(self):
        try:
            if platform.system() == "Windows":
                os.startfile(str(LOG_DIR))
        except Exception as e:
            logger.error(e)

    def _quit(self):
        logger.info("Tray encerrado pelo usuário")
        if self.icon:
            self.icon.stop()

    def _on_click(self, icon, event):
        """
        Duplo clique no ícone abre os Chamados.

        pystray no Windows entrega um objeto MouseButton/HookEvent — não a
        string "double".  Verificamos via atributo .double (pystray >= 0.19)
        e, como fallback, pela string para outros backends (Linux/macOS).
        Sempre executado em thread separada para não bloquear o loop do tray.
        """
        try:
            is_double = getattr(event, "double", False)
        except Exception:
            is_double = False

        if not is_double and event != "double":
            return  # clique simples — ignora

        threading.Thread(target=self._open_chamados, daemon=True).start()

    def run(self):
        self.icon = pystray.Icon(
            "inventory_agent",
            self._make_image("unknown"),
            "Inventory Agent",
            self._build_menu(),
            on_clicked=self._on_click,
        )
        threading.Thread(target=self._poll_loop,           daemon=True, name="poll").start()
        threading.Thread(target=start_webrtc_local_server, daemon=True, name="webrtc-local").start()
        logger.info(f"Tray iniciado | WebRTC local em 127.0.0.1:{WEBRTC_PORT}")
        self.icon.run()

    def _poll_loop(self):
        while True:
            try:
                status = IPCClient.get_status()
                if status:
                    s = "online" if status.get("online") else "offline"
                    self.update_status(s, status.get("pending_notifications", 0))
                    for notif in IPCClient.get_notifications():
                        self._show_notification(notif)
                        IPCClient.ack_notification(notif.get("id"))
                else:
                    self.update_status("unknown")
            except Exception as e:
                logger.error(f"Erro no poll: {e}")
                self.update_status("unknown")
            time.sleep(POLL_INTERVAL)

    def _show_notification(self, notif):
        notif_type = notif.get("type", "info")
        if notif_type not in ("info", "success", "warning", "error", "alert"):
            notif_type = "info"
        ToastNotification.show(
            title=notif.get("title", "Notificação"),
            message=notif.get("message", ""),
            notif_type=notif_type,
            duration=notif.get("duration", 360),
            action_label=notif.get("action_label"),
            action_callback=None,
        )
        logger.info(f"Notificação exibida: {notif.get('title')}")


# ─────────────────────────────────────────────
# Ponto de entrada
# ─────────────────────────────────────────────
def main():
    logger.info(f"=== AgentTray v{VERSION} iniciando ===")
    logger.info(f"WebRTC local: 127.0.0.1:{WEBRTC_PORT}")

    if not IPCClient.is_service_running():
        logger.warning("Serviço não detectado em 127.0.0.1:7070.")
        ToastNotification.show(
            title="Inventory Agent",
            message="Serviço não encontrado. Verifique se o serviço Windows está ativo.",
            notif_type="error", duration=8)

    TrayIcon().run()


if __name__ == "__main__":
    main()