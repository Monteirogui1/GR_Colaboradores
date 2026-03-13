import os
import sys
import time
import threading
import platform
import tkinter as tk
from pathlib import Path
import logging
import requests

from notification import ToastNotification

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
except ImportError:
    print("ERRO: pip install pystray pillow")
    sys.exit(1)

VERSION       = "3.0.1"
IPC_URL       = "http://127.0.0.1:7070"
POLL_INTERVAL = 8   # segundos

LOG_DIR = Path(os.path.dirname(__file__)) / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "tray.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("AgentTray")


# ─────────────────────────────────────────────
# Cliente IPC
# ─────────────────────────────────────────────

class IPCClient:
    """
    Comunica com o agent_service via HTTP local (127.0.0.1:7070).

    NOTA DE SEGURANÇA: não enviamos token aqui.
    O IPC é restrito ao loopback — o agent_service é quem detém
    o token e faz todas as requisições autenticadas ao Django.
    """

    _session = requests.Session()

    @classmethod
    def _get(cls, path: str, timeout: int = 3):
        try:
            r = cls._session.get(f"{IPC_URL}{path}", timeout=timeout)
            return r.json() if r.ok else None
        except Exception:
            return None

    @classmethod
    def _post(cls, path: str, body: dict = None, timeout: int = 5):
        try:
            r = cls._session.post(f"{IPC_URL}{path}", json=body or {}, timeout=timeout)
            return r.json() if r.ok else None
        except Exception:
            return None

    @classmethod
    def get_status(cls) -> dict | None:
        return cls._get("/status")

    @classmethod
    def get_notifications(cls) -> list:
        data = cls._get("/notifications")
        return data.get("notifications", []) if data else []

    @classmethod
    def ack_notification(cls, notif_id):
        """
        Marca notificação como vista localmente E delega ao service
        o ACK para o Django (com Authorization header correto).
        """
        cls._post("/notifications/ack", {"id": notif_id})

    @classmethod
    def force_sync(cls) -> bool:
        result = cls._post("/sync")
        return bool(result and result.get("ok"))

    @classmethod
    def is_service_running(cls) -> bool:
        return cls._get("/ping", timeout=2) is not None

    @classmethod
    def run_command(cls, cmd_type: str, script: str, timeout: int = 30) -> dict | None:
        """Executa comando remoto via service (PowerShell ou CMD)."""
        return cls._post("/command", {
            "type":    cmd_type,
            "script":  script,
            "timeout": timeout,
        })


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
        self.window.geometry("440x340")
        self.window.resizable(False, False)
        self.window.configure(bg="#0f172a")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # Header
        header = tk.Frame(self.window, bg="#1e293b", pady=16, padx=20)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="Inventory Agent", fg="white", bg="#1e293b",
            font=("Segoe UI", 14, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            header, text=f"v{VERSION}", fg="#64748b",
            bg="#1e293b", font=("Segoe UI", 9),
        ).pack(side=tk.RIGHT)

        # Body
        body = tk.Frame(self.window, bg="#0f172a", padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        def row(label, default="—"):
            f = tk.Frame(body, bg="#0f172a")
            f.pack(fill=tk.X, pady=4)
            tk.Label(
                f, text=label, fg="#64748b", bg="#0f172a",
                font=("Segoe UI", 9), width=18, anchor="w",
            ).pack(side=tk.LEFT)
            val = tk.Label(
                f, text=default, fg="#e2e8f0", bg="#0f172a",
                font=("Segoe UI", 9, "bold"), anchor="w",
            )
            val.pack(side=tk.LEFT)
            return val

        self.lbl_status  = row("Status serviço")
        self.lbl_machine = row("Máquina")
        self.lbl_checkin = row("Último check-in")
        self.lbl_notif   = row("Notif. pendentes")
        self.lbl_version = row("Versão")
        self.lbl_error   = row("Último erro")

        # Botões
        btn_frame = tk.Frame(self.window, bg="#1e293b", pady=12, padx=20)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        def btn(parent, text, cmd, accent="#334155"):
            b = tk.Button(
                parent, text=text, command=cmd,
                bg=accent, fg="white", relief="flat",
                font=("Segoe UI", 9), padx=12, pady=6,
            )
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
                fg="#4ade80" if online else "#f87171",
            )
            self.lbl_machine.config(text=status.get("machine", "—"))
            checkin = status.get("last_checkin")
            self.lbl_checkin.config(
                text=checkin[:19].replace("T", " ") if checkin else "—"
            )
            self.lbl_notif.config(text=str(status.get("pending_notifications", 0)))
            self.lbl_version.config(text=status.get("version", VERSION))
            err = status.get("last_error", "")
            self.lbl_error.config(
                text=(err[:40] + "…") if len(err) > 40 else (err or "Nenhum"),
                fg="#f87171" if err else "#4ade80",
            )
        else:
            self.lbl_status.config(text="⚫ Serviço offline", fg="#94a3b8")

        self.window.after(5000, self._refresh)

    def _sync(self):
        ok = IPCClient.force_sync()
        ToastNotification.show(
            title="Sync",
            message="Sincronização iniciada!" if ok else "Serviço não respondeu.",
            notif_type="success" if ok else "error",
            duration=5,
        )

    def _open_logs(self):
        try:
            if platform.system() == "Windows":
                os.startfile(str(LOG_DIR))
        except Exception as e:
            logger.error(f"Erro ao abrir logs: {e}")

    def _on_close(self):
        self.alive = False
        self.window.destroy()


# ─────────────────────────────────────────────
# Ícone do System Tray
# ─────────────────────────────────────────────

class TrayIcon:
    STATUS_COLORS = {
        "online":  (34, 197, 94),    # verde
        "offline": (239, 68, 68),    # vermelho
        "unknown": (148, 163, 184),  # cinza
    }

    def __init__(self):
        self.icon         = None
        self._status      = "unknown"
        self._notif_count = 0

    def _make_image(self, status: str) -> Image.Image:
        size = 64
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = self.STATUS_COLORS.get(status, self.STATUS_COLORS["unknown"])

        draw.ellipse([6, 6, 58, 58], fill=color + (255,))
        draw.ellipse([6, 6, 58, 58], outline=(255, 255, 255, 180), width=3)

        # Badge de notificação
        if self._notif_count > 0:
            draw.ellipse([40, 2, 62, 24], fill=(239, 68, 68, 255))
            draw.text((47, 4), str(min(self._notif_count, 9)), fill="white")

        return img

    def update_status(self, status: str, notif_count: int = 0):
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
            item("⚡ Forçar Sync", lambda i, it: self._force_sync()),
            pystray.Menu.SEPARATOR,
            item("📄 Ver Logs",    lambda i, it: self._open_logs()),
            pystray.Menu.SEPARATOR,
            item("❌ Sair",        lambda i, it: self._quit()),
        )

    def _force_sync(self):
        ok = IPCClient.force_sync()
        ToastNotification.show(
            title="Sync",
            message="Sincronização iniciada!" if ok else "Serviço indisponível.",
            notif_type="success" if ok else "error",
            duration=5,
        )

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
        threading.Thread(target=self._poll_loop, daemon=True, name="poll").start()
        logger.info("Tray iniciado")
        self.icon.run()

    def _poll_loop(self):
        """
        Polling periódico do agent_service via IPC local.
        O Tray não acessa o Django diretamente — toda autenticação
        fica no agent_service (Session 0).
        """
        while True:
            try:
                status = IPCClient.get_status()
                if status:
                    s = "online" if status.get("online") else "offline"
                    self.update_status(s, status.get("pending_notifications", 0))

                    for notif in IPCClient.get_notifications():
                        self._show_notification(notif)
                        # ACK delega ao service → service propaga ao Django com token
                        IPCClient.ack_notification(notif.get("id"))
                else:
                    self.update_status("unknown")

            except Exception as e:
                logger.error(f"Erro no poll: {e}")
                self.update_status("unknown")

            time.sleep(POLL_INTERVAL)

    def _show_notification(self, notif: dict):
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

    if not IPCClient.is_service_running():
        logger.warning("Serviço não detectado em 127.0.0.1:7070.")
        ToastNotification.show(
            title="Inventory Agent",
            message="Serviço não encontrado. Verifique se o serviço Windows está ativo.",
            notif_type="error",
            duration=8,
        )

    TrayIcon().run()


if __name__ == "__main__":
    main()