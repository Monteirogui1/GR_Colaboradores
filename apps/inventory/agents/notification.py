"""
notification.py — Notificação tkinter centralizada, layout limpo

Layout:
  ┌─ faixa accent 3px ──────────────────────────────────┐
  │  [ico]  LABEL                                   [×]  │
  │         Título                                        │
  │         Mensagem com wrap                            │
  │  [████████░░░░░]  [Fechar]  [Ação]                   │
  └──────────────────────────────────────────────────────┘

Uso:
    from notification import ToastNotification

    ToastNotification.show(
        title="Servidor offline",
        message="Não foi possível conectar. Tentando em 60s.",
        notif_type="warning",
        duration=8,
        action_label="Tentar agora",
        action_callback=lambda: ipc_client.force_sync(),
    )

Tipos: "info" | "success" | "warning" | "error" | "alert"
"""

import sys
import time
import math
import threading
import tkinter as tk
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────────
# Temas — fundo claro, cores por tipo
# ─────────────────────────────────────────────────────────────

THEMES = {
    "info": {
        "accent":   "#378ADD",
        "icon_bg":  "#E6F1FB",
        "icon_fg":  "#185FA5",
        "icon":     "i",
        "label":    "INFO",
        "label_fg": "#185FA5",
        "btn_bg":   "#378ADD",
        "btn_fg":   "#E6F1FB",
    },
    "success": {
        "accent":   "#639922",
        "icon_bg":  "#EAF3DE",
        "icon_fg":  "#3B6D11",
        "icon":     "✓",
        "label":    "SUCCESS",
        "label_fg": "#3B6D11",
        "btn_bg":   "#639922",
        "btn_fg":   "#EAF3DE",
    },
    "warning": {
        "accent":   "#BA7517",
        "icon_bg":  "#FAEEDA",
        "icon_fg":  "#854F0B",
        "icon":     "!",
        "label":    "WARNING",
        "label_fg": "#854F0B",
        "btn_bg":   "#BA7517",
        "btn_fg":   "#FAEEDA",
    },
    "error": {
        "accent":   "#A32D2D",
        "icon_bg":  "#FCEBEB",
        "icon_fg":  "#791F1F",
        "icon":     "×",
        "label":    "ERROR",
        "label_fg": "#791F1F",
        "btn_bg":   "#A32D2D",
        "btn_fg":   "#FCEBEB",
    },
    "alert": {
        "accent":   "#534AB7",
        "icon_bg":  "#EEEDFE",
        "icon_fg":  "#3C3489",
        "icon":     "◉",
        "label":    "ALERT",
        "label_fg": "#3C3489",
        "btn_bg":   "#534AB7",
        "btn_fg":   "#EEEDFE",
    },
}

# Cores de base (neutras — funcionam em tela clara)
BG        = "#FFFFFF"
BORDER    = "#E2E8F0"
TEXT_PRI  = "#0F172A"
TEXT_SEC  = "#64748B"
TEXT_TER  = "#94A3B8"
DISMISS   = "#64748B"

WIN_W   = 420
TICK_MS = 40


# ─────────────────────────────────────────────────────────────
# ToastNotification
# ─────────────────────────────────────────────────────────────

class ToastNotification:
    """
    Notificação limpa centralizada na tela.
    Thread-safe — fecha a anterior antes de abrir nova.
    """

    _lock    = threading.Lock()
    _current: Optional["ToastNotification"] = None

    def __init__(
        self,
        title:           str,
        message:         str,
        notif_type:      str = "info",
        duration:        int = 7,
        action_label:    Optional[str] = None,
        action_callback: Optional[Callable] = None,
    ):
        self.title           = title
        self.message         = message
        self.notif_type      = notif_type if notif_type in THEMES else "info"
        self.duration        = max(0, duration)
        self.action_label    = action_label
        self.action_callback = action_callback
        self.theme           = THEMES[self.notif_type]

        self._done    = threading.Event()
        self._root    = None
        self._elapsed = 0.0
        self._bar_lbl = None   # Label usada como barra de progresso

    # ── API pública ───────────────────────────────────────────

    @classmethod
    def show(
        cls,
        title:           str,
        message:         str,
        notif_type:      str = "info",
        duration:        int = 7,
        action_label:    Optional[str] = None,
        action_callback: Optional[Callable] = None,
        wait:            bool = False,
    ) -> "ToastNotification":
        n = cls(title, message, notif_type, duration, action_label, action_callback)
        t = threading.Thread(target=n._run, daemon=not wait)
        t.start()
        if wait:
            n._done.wait()
        return n

    def close(self):
        if self._root:
            try:
                self._root.after(0, self._dismiss)
            except Exception:
                pass

    # ── Ciclo de vida ─────────────────────────────────────────

    def _run(self):
        with self.__class__._lock:
            prev = self.__class__._current
            if prev:
                prev.close()
                prev._done.wait(timeout=0.6)
            self.__class__._current = self
            try:
                self._build()
            finally:
                self.__class__._current = None
                self._done.set()

    # ── Construção ────────────────────────────────────────────

    def _build(self):
        t = self.theme

        root = tk.Tk()
        self._root = root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.97)
        root.configure(bg=BORDER)
        root.resizable(False, False)

        # Borda fina: container com 1px de BG para simular borda
        outer = tk.Frame(root, bg=BORDER, padx=1, pady=1)
        outer.pack(fill=tk.BOTH, expand=True)

        main = tk.Frame(outer, bg=BG)
        main.pack(fill=tk.BOTH, expand=True)

        # ── Faixa accent no topo ─────────────────────────────
        tk.Frame(main, bg=t["accent"], height=3).pack(fill=tk.X)

        # ── Corpo ────────────────────────────────────────────
        body = tk.Frame(main, bg=BG, padx=16, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        # Linha superior: ícone + textos + fechar
        top_row = tk.Frame(body, bg=BG)
        top_row.pack(fill=tk.X)

        # Ícone
        icon_box = tk.Frame(top_row, bg=t["icon_bg"],
                            width=34, height=34)
        icon_box.pack(side=tk.LEFT, anchor="n")
        icon_box.pack_propagate(False)
        tk.Label(icon_box, text=t["icon"],
                 bg=t["icon_bg"], fg=t["icon_fg"],
                 font=("Segoe UI", 13, "bold")).place(relx=0.5, rely=0.5, anchor="center")

        # Textos
        txt = tk.Frame(top_row, bg=BG)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        tk.Label(txt, text=t["label"],
                 bg=BG, fg=t["label_fg"],
                 font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill=tk.X)

        tk.Label(txt, text=self.title,
                 bg=BG, fg=TEXT_PRI,
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", wraplength=WIN_W - 100,
                 justify="left").pack(fill=tk.X)

        tk.Label(txt, text=self.message,
                 bg=BG, fg=TEXT_SEC,
                 font=("Segoe UI", 9),
                 anchor="nw", wraplength=WIN_W - 100,
                 justify="left").pack(fill=tk.X, pady=(2, 0))

        # Botão fechar (×)
        close_btn = tk.Label(top_row, text="×",
                             bg=BG, fg=TEXT_TER,
                             font=("Segoe UI", 14),
                             cursor="hand2", padx=2)
        close_btn.pack(side=tk.RIGHT, anchor="n", padx=(8, 0))
        close_btn.bind("<Button-1>", lambda e: self._dismiss())
        close_btn.bind("<Enter>",    lambda e: close_btn.config(fg="#EF4444"))
        close_btn.bind("<Leave>",    lambda e: close_btn.config(fg=TEXT_TER))

        # ── Rodapé: barra + botões ────────────────────────────
        footer = tk.Frame(main, bg=BG, padx=16, pady=10)
        footer.pack(fill=tk.X)

        # Barra de progresso (canvas simples, 2 retângulos)
        bar_canvas = tk.Canvas(footer, height=3, bg=BORDER,
                               highlightthickness=0, bd=0)
        bar_canvas.pack(fill=tk.X, side=tk.LEFT, expand=True,
                        padx=(0, 12), pady=(6, 0))

        if self.duration > 0:
            # Trilho já é o bg do canvas (BORDER)
            self._bar_canvas = bar_canvas
            self._bar_item   = None   # criado após pack (precisa de largura real)
            root.update_idletasks()
            bw = bar_canvas.winfo_width()
            self._bar_item  = bar_canvas.create_rectangle(
                0, 0, bw, 3, fill=t["accent"], outline=""
            )
            self._bar_full_w = bw

        # Botões
        btn_row = tk.Frame(footer, bg=BG)
        btn_row.pack(side=tk.RIGHT)

        tk.Button(
            btn_row, text="Fechar",
            command=self._dismiss,
            bg=BG, fg=DISMISS,
            activebackground="#F8FAFC",
            activeforeground=TEXT_SEC,
            relief="flat", bd=0,
            font=("Segoe UI", 9),
            padx=10, pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 4))

        if self.action_label:
            def _on_action():
                self._dismiss()
                if self.action_callback:
                    threading.Thread(
                        target=self._safe_call,
                        args=(self.action_callback,),
                        daemon=True,
                    ).start()

            act = tk.Button(
                btn_row, text=self.action_label,
                command=_on_action,
                bg=t["btn_bg"], fg=t["btn_fg"],
                activebackground=t["accent"],
                activeforeground=t["btn_fg"],
                relief="flat", bd=0,
                font=("Segoe UI", 9, "bold"),
                padx=12, pady=4,
                cursor="hand2",
            )
            act.pack(side=tk.LEFT)
            act.bind("<Enter>", lambda e: act.config(bg=_darken(t["btn_bg"])))
            act.bind("<Leave>", lambda e: act.config(bg=t["btn_bg"]))

        # ── Centralizar na tela ───────────────────────────────
        root.update_idletasks()
        w = root.winfo_reqwidth()
        h = root.winfo_reqheight()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        # ── ESC fecha ─────────────────────────────────────────
        root.bind("<Escape>", lambda e: self._dismiss())

        # ── Countdown ─────────────────────────────────────────
        if self.duration > 0:
            root.after(TICK_MS, self._tick)

        root.mainloop()

    # ── Progresso ─────────────────────────────────────────────

    def _tick(self):
        if not self._root or self._bar_item is None:
            return
        try:
            self._elapsed += TICK_MS / 1000.0
            ratio = max(0.0, 1.0 - self._elapsed / self.duration)
            self._bar_canvas.coords(
                self._bar_item,
                0, 0, self._bar_full_w * ratio, 3,
            )
            if ratio > 0:
                self._root.after(TICK_MS, self._tick)
            else:
                self._dismiss()
        except Exception:
            pass

    # ── Fechar ────────────────────────────────────────────────

    def _dismiss(self):
        if self._root:
            self._fade_out(0.97)

    def _fade_out(self, alpha: float):
        alpha -= 0.13
        try:
            if alpha > 0 and self._root:
                self._root.attributes("-alpha", max(alpha, 0.0))
                self._root.after(14, lambda: self._fade_out(alpha))
            else:
                if self._root:
                    self._root.destroy()
                self._root = None
        except Exception:
            self._root = None

    @staticmethod
    def _safe_call(fn: Callable):
        try:
            fn()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Utilitário de cor
# ─────────────────────────────────────────────────────────────

def _darken(hex_color: str, factor: float = 0.12) -> str:
    try:
        h = hex_color.lstrip("#")
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


# ─────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    casos = [
        dict(title="Sincronização concluída",
             message="Dados de hardware enviados ao servidor com sucesso. Próximo check-in em 5 minutos.",
             notif_type="success", duration=6),
        dict(title="Atualização disponível — v3.1.0",
             message="Uma nova versão do agente está disponível e pronta para instalação.",
             notif_type="info", duration=8,
             action_label="Atualizar agora",
             action_callback=lambda: print("→ atualização iniciada")),
        dict(title="Servidor indisponível",
             message="Não foi possível conectar ao servidor de inventário. Tentando novamente em 60 segundos.",
             notif_type="warning", duration=7,
             action_label="Tentar agora",
             action_callback=lambda: print("→ sync forçado")),
        dict(title="Falha ao coletar hardware",
             message="O script retornou código 1. Verifique permissões e os logs do agente.",
             notif_type="error", duration=8,
             action_label="Ver logs",
             action_callback=lambda: print("→ abrindo logs")),
        dict(title="Reinicialização necessária",
             message="Reinicie este computador até sexta-feira para aplicar atualizações de segurança.",
             notif_type="alert", duration=9,
             action_label="Lembrar depois",
             action_callback=lambda: print("→ agendado")),
    ]

    print("Demo — ESC ou aguarde fechar\n")
    for caso in casos:
        print(f"  [{caso['notif_type'].upper():8s}] {caso['title']}")
        ToastNotification.show(**caso, wait=True)
        time.sleep(0.15)

    print("\nConcluído.")