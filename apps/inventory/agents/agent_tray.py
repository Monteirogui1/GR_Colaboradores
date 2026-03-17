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

VERSION       = "3.3.0"
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
            self._sct     = mss.mss()
            self._monitor = self._sct.monitors[1]
        pts, time_base  = await self.next_timestamp()
        img             = self._sct.grab(self._monitor)
        frame           = av.VideoFrame.from_ndarray(np.array(img), format="bgra")
        frame.pts       = pts
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
                            threading.Thread(
                                target=_handle_input_event,
                                args=(json.loads(message), session_id),
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

    @classmethod
    def get_agent_config(cls) -> dict:
        """Busca server_url e token_hash do agent_service via IPC."""
        status = cls.get_status()
        return {
            "server_url": (status or {}).get("server_url", ""),
            "token_hash": (status or {}).get("token_hash", ""),
        }


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
            item("📊 Status",
                 lambda i, it: StatusWindow.open(self)),
            item("🎫 Chamados",
                 lambda i, it: self._open_chamados()),
            item("⚡ Forçar Sync",
                 lambda i, it: self._force_sync()),
            pystray.Menu.SEPARATOR,
            item("❌ Sair",
                 lambda i, it: self._quit()),
        )

    def _open_chamados(self):
        cfg = IPCClient.get_agent_config()
        if not cfg["server_url"]:
            ToastNotification.show(
                title="Chamados indisponível",
                message="Serviço não respondeu. Verifique se o agent_service está rodando.",
                notif_type="error", duration=6)
            return
        ChamadosManager.open(cfg["server_url"], cfg["token_hash"])

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

    def run(self):
        self.icon = pystray.Icon(
            "inventory_agent",
            self._make_image("unknown"),
            "Inventory Agent",
            self._build_menu(),
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