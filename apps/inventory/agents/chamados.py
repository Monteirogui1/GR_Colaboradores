"""
chamados.py — Painel de chamados de suporte para o Inventory Agent
v4.0 — Layout com tabela de tickets, chat e painel de informações

Uso:
    from chamados import ChamadosManager

    ChamadosManager.open(
        server_url="http://192.168.1.10:8000",
        token_hash="abc123...",
        logged_user="joao.silva",   # Machine.loggedUser (opcional)
    )

Endpoints necessários (apps/tickets/views.py):
    GET  /tickets/api/agent/list/?email=X&logged_user=Y  → lista tickets
    GET  /tickets/api/agent/<pk>/                        → histórico
    POST /tickets/api/agent/<pk>/reply/                  → responder
    POST /tickets/api/agent/criar/                       → novo ticket
    GET  /api/inventario/agent/machine/                  → info + ativos
"""

import os
import json
import threading
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox
from pathlib import Path
from typing import Optional
import logging
import requests

logger = logging.getLogger("AgentTray")


# ═════════════════════════════════════════════════════════════════════════════
# _EmailStore — persiste e-mail por loggedUser em %APPDATA%\InventoryAgent\
# ═════════════════════════════════════════════════════════════════════════════
class _EmailStore:
    _path: Path = None

    @classmethod
    def _file(cls) -> Path:
        if cls._path is None:
            base = Path(os.environ.get("APPDATA", Path.home())) / "InventoryAgent"
            base.mkdir(parents=True, exist_ok=True)
            cls._path = base / "emails.json"
        return cls._path

    @classmethod
    def _load(cls) -> dict:
        try:
            return json.loads(cls._file().read_text(encoding="utf-8"))
        except Exception:
            return {}

    @classmethod
    def get(cls, logged_user: str) -> str:
        if not logged_user:
            return ""
        return cls._load().get(logged_user, "")

    @classmethod
    def save(cls, logged_user: str, email: str) -> None:
        if not logged_user:
            return
        data = cls._load()
        data[logged_user] = email.strip()
        cls._file().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# Cores
# ═════════════════════════════════════════════════════════════════════════════
_G = "#00c4a1"    # verde principal
_GD = "#00a98a"   # verde escuro (hover)
_DK = "#1a1a2e"   # sidebar escura
_BG = "#f4f6f8"   # fundo geral
_WH = "#ffffff"
_BD = "#e8eaed"   # borda padrão
_BD2 = "#e2e8f0"  # borda secundária
_TX = "#1e293b"   # texto principal
_MU = "#64748b"   # texto muted
_HI = "#94a3b8"   # texto hint

# Status → (bg_pill, fg_pill)
_ST_COLORS = {
    "Aberto":       ("#e3f2fd", "#1565c0"),
    "Em andamento": ("#fff3e0", "#e65100"),
    "Resolvido":    ("#e8f5e9", "#2e7d32"),
    "Fechado":      ("#f1f5f9", "#475569"),
    "Cancelado":    ("#fee2e2", "#7f1d1d"),
    "Planejado":    ("#e8f5e9", "#2e7d32"),
}
_PRIO_COLORS = {
    "Alta":     ("#fff3e0", "#e65100"),
    "Médio":    ("#fff8e6", "#b45309"),
    "Normal":   ("#e3f2fd", "#1565c0"),
    "Baixa":    ("#e8f5e9", "#2e7d32"),
    "Crítica":  ("#fee2e2", "#7f1d1d"),
    "Planejado":("#e8f5e9", "#2e7d32"),
}

def _st(status):
    return _ST_COLORS.get(status, ("#f1f5f9", "#475569"))

def _pr(prio):
    return _PRIO_COLORS.get(prio, ("#f1f5f9", "#475569"))


# ═════════════════════════════════════════════════════════════════════════════
# _ApiClient
# ═════════════════════════════════════════════════════════════════════════════
class _ApiClient:
    def __init__(self, server_url: str, token_hash: str):
        self._base = server_url.rstrip("/")
        self._sess = requests.Session()
        self._sess.headers.update({
            "Authorization": f"Bearer {token_hash}",
            "Content-Type":  "application/json",
        })
        self._sess.verify = False

    def get(self, path, **params):
        r = self._sess.get(f"{self._base}{path}", params=params or None, timeout=12)
        r.raise_for_status()
        return r.json()

    def post(self, path, body: dict):
        r = self._sess.post(f"{self._base}{path}", json=body, timeout=12)
        r.raise_for_status()
        return r.json()


# ═════════════════════════════════════════════════════════════════════════════
# Helpers de widget
# ═════════════════════════════════════════════════════════════════════════════
def _flat_btn(master, text, cmd, bg=_G, fg="#fff", **kw):
    b = tk.Button(master, text=text, command=cmd,
                  bg=bg, fg=fg,
                  activebackground=_GD if bg == _G else bg,
                  activeforeground=fg,
                  relief=tk.FLAT, bd=0, cursor="hand2", **kw)
    return b


def _entry(master, textvariable=None, **kw):
    e = tk.Entry(master, textvariable=textvariable,
                 bg="#f8fafc", fg=_TX,
                 insertbackground=_TX,
                 relief=tk.FLAT, bd=0,
                 highlightthickness=1,
                 highlightbackground=_BD2,
                 highlightcolor=_G, **kw)
    e.bind("<FocusIn>",  lambda _: e.config(highlightbackground=_G, bg=_WH))
    e.bind("<FocusOut>", lambda _: e.config(highlightbackground=_BD2, bg="#f8fafc"))
    return e


def _hsep(master, color=_BD):
    return tk.Frame(master, bg=color, height=1)


def _label_field(master, text, req=False, font=None):
    frm = tk.Frame(master, bg=_WH)
    frm.pack(fill=tk.X, pady=(0, 4))
    fS = font or tkfont.Font(family="Segoe UI", size=8)
    tk.Label(frm, text=text.upper(), font=fS,
             bg=_WH, fg=_MU).pack(side=tk.LEFT)
    if req:
        tk.Label(frm, text=" *", font=fS, bg=_WH, fg="#f43f5e").pack(side=tk.LEFT)


# ═════════════════════════════════════════════════════════════════════════════
# _NovoTicketModal
# ═════════════════════════════════════════════════════════════════════════════
class _NovoTicketModal:

    def __init__(self, parent_win: tk.Tk, api: _ApiClient,
                 logged_user: str, email_salvo: str, on_success):
        self._api         = api
        self._logged_user = logged_user
        self._on_success  = on_success

        win = tk.Toplevel(parent_win)
        self._win = win
        win.title("Novo Ticket")
        win.update_idletasks()

        width = 420
        height = 470

        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()

        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)

        win.geometry(f"{width}x{height}+{x}+{y}")
        win.resizable(False, False)
        win.configure(bg=_WH)
        win.grab_set()
        win.focus_force()
        win.overrideredirect(True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        def start_move(event):
            win.x = event.x
            win.y = event.y

        def do_move(event):
            deltax = event.x - win.x
            deltay = event.y - win.y
            x = win.winfo_x() + deltax
            y = win.winfo_y() + deltay
            win.geometry(f"+{x}+{y}")

        win.bind("<Button-1>", start_move)
        win.bind("<B1-Motion>", do_move)

        fT = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        fL = tkfont.Font(family="Segoe UI", size=8)
        fI = tkfont.Font(family="Segoe UI", size=10)
        fB = tkfont.Font(family="Segoe UI", size=9,  weight="bold")
        fS = tkfont.Font(family="Segoe UI", size=9)

        # Header
        hdr = tk.Frame(win, bg=_WH, padx=18, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Novo Ticket", font=fT,
                 bg=_WH, fg=_DK).pack(side=tk.LEFT)
        tk.Button(hdr, text="✕", font=fS, bg=_WH, fg=_HI,
                  relief=tk.FLAT, bd=0, cursor="hand2",
                  command=win.destroy).pack(side=tk.RIGHT)
        _hsep(win).pack(fill=tk.X)

        # Body
        body = tk.Frame(win, bg=_WH, padx=18, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        # E-mail
        _label_field(body, "E-mail", req=True, font=fL)
        self._email_var = tk.StringVar(value=email_salvo)
        email_e = _entry(body, textvariable=self._email_var, font=fI)
        email_e.pack(fill=tk.X, ipady=7, pady=(0, 3))
        hint_txt = "Salvo para próximos chamados" if not email_salvo else "E-mail salvo — altere se necessário"
        tk.Label(body, text=hint_txt, font=tkfont.Font(family="Segoe UI", size=8),
                 bg=_WH, fg=_HI, anchor="w").pack(fill=tk.X, pady=(0, 12))

        # Assunto
        _label_field(body, "Assunto", req=True, font=fL)
        self._assunto_var = tk.StringVar()
        _entry(body, textvariable=self._assunto_var, font=fI).pack(
            fill=tk.X, ipady=7, pady=(0, 14))

        # Tipo de serviço
        _label_field(body, "Tipo de Serviço", font=fL)
        self._tipo_var = tk.StringVar()
        style = ttk.Style()
        style.configure("TCombobox", fieldbackground="#f8fafc",
                        background="#f8fafc", foreground=_TX)
        ttk.Combobox(body, textvariable=self._tipo_var,
                     state="readonly", font=fI,
                     values=["Suporte técnico", "Acesso e permissões",
                             "Hardware / Equipamento", "Software / Sistema",
                             "Rede e conectividade", "Outros"]).pack(
            fill=tk.X, ipady=4, pady=(0, 14))

        # Descrição
        _label_field(body, "Descrição", req=True, font=fL)
        self._desc = tk.Text(
            body, height=4, font=fI,
            bg="#f8fafc", fg=_TX,
            insertbackground=_TX,
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=_BD2,
            highlightcolor=_G,
            padx=10, pady=8, wrap=tk.WORD,
        )
        self._desc.pack(fill=tk.X, pady=(0, 2))
        self._desc.bind("<FocusIn>",
            lambda _: self._desc.config(highlightbackground=_G, bg=_WH))
        self._desc.bind("<FocusOut>",
            lambda _: self._desc.config(highlightbackground=_BD2, bg="#f8fafc"))

        # Footer
        _hsep(win).pack(fill=tk.X, side=tk.BOTTOM)
        footer = tk.Frame(win, bg=_WH, padx=18, pady=6)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        _flat_btn(footer, "Cancelar", win.destroy,
                  bg=_WH, fg=_MU,
                  highlightthickness=1, highlightbackground=_BD2,
                  font=fS, padx=18, pady=14).pack(side=tk.RIGHT, padx=(8, 0))
        _flat_btn(footer, "Abrir Ticket", self._submit,
                  font=fB, padx=18, pady=14).pack(side=tk.RIGHT)

        if not email_salvo:
            email_e.focus_set()

    def _submit(self):
        email     = self._email_var.get().strip()
        assunto   = self._assunto_var.get().strip()
        tipo      = self._tipo_var.get().strip()
        descricao = self._desc.get("1.0", tk.END).strip()

        missing = []
        if not email:     missing.append("E-mail")
        if not assunto:   missing.append("Assunto")
        if not descricao: missing.append("Descrição")
        if missing:
            messagebox.showerror("Campos obrigatórios",
                                 f"Preencha: {', '.join(missing)}.",
                                 parent=self._win)
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            messagebox.showerror("E-mail inválido",
                                 "Informe um e-mail válido.",
                                 parent=self._win)
            return

        def send():
            try:
                data = self._api.post("/tickets/api/agent/criar/", {
                    "email_solicitante": email,
                    "logged_user":       self._logged_user,
                    "tipo_chamado":      tipo,
                    "assunto":           assunto,
                    "descricao":         descricao,
                })
                if data.get("ok"):
                    _EmailStore.save(self._logged_user, email)
                    self._win.after(0, self._win.destroy)
                    self._win.after(300, lambda: self._on_success(data, email))
                else:
                    messagebox.showerror("Erro",
                        data.get("error", "Erro desconhecido"),
                        parent=self._win)
            except Exception as ex:
                logger.error(f"NovoTicket: {ex}")
                messagebox.showerror("Erro de conexão", str(ex), parent=self._win)

        threading.Thread(target=send, daemon=True).start()


# ═════════════════════════════════════════════════════════════════════════════
# _ChamadosWindow — janela principal
# ═════════════════════════════════════════════════════════════════════════════
class _ChamadosWindow:

    def __init__(self, server_url: str, token_hash: str, logged_user: str = ""):
        self._api         = _ApiClient(server_url, token_hash)
        self._logged_user = logged_user
        self._email       = _EmailStore.get(logged_user)
        self._tickets     = []
        self._selected    = None
        self._historico   = []
        self._machine_info = {}
        self.alive        = True
        threading.Thread(target=self._run, daemon=True).start()

    # ── run ──────────────────────────────────────────────────────────────────
    def _run(self):
        win = tk.Tk()
        self._win = win
        win.title("Suporte TI")
        win.geometry("1060x660")
        win.minsize(860, 540)
        win.configure(bg=_BG)
        win.protocol("WM_DELETE_WINDOW", self._on_close)

        # fontes
        self._fN  = tkfont.Font(family="Segoe UI", size=9)
        self._fB  = tkfont.Font(family="Segoe UI", size=9,  weight="bold")
        self._fS  = tkfont.Font(family="Segoe UI", size=8)
        self._fSB = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._fM  = tkfont.Font(family="Segoe UI", size=10)
        self._fH  = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self._fBT = tkfont.Font(family="Segoe UI", size=9,  weight="bold")
        self._fLB = tkfont.Font(family="Segoe UI", size=8)

        outer = tk.Frame(win, bg=_BG)
        outer.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(outer)
        tk.Frame(outer, bg=_BD, width=1).pack(side=tk.LEFT, fill=tk.Y)

        self._main_area = tk.Frame(outer, bg=_BG)
        self._main_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_tickets_view()
        self._build_info_view()
        self._build_chat_view()

        self._show_view("tickets")

        if self._email:
            win.after(400, self._load_tickets)

        # carrega info da máquina em background
        win.after(600, self._load_machine_info)
        win.mainloop()

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=_DK, width=170)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        sb.pack_propagate(False)

        # logo
        logo_frm = tk.Frame(sb, bg=_DK, padx=14, pady=18)
        logo_frm.pack(fill=tk.X)
        tk.Label(logo_frm, text="Suporte", font=self._fH,
                 bg=_DK, fg=_WH).pack(anchor="w")
        tk.Label(logo_frm, text="TI", font=self._fH,
                 bg=_DK, fg=_G).pack(anchor="w")
        tk.Frame(sb, bg="#2d2d4e", height=1).pack(fill=tk.X)

        # botões de navegação
        nav = tk.Frame(sb, bg=_DK, padx=10, pady=12)
        nav.pack(fill=tk.X)

        self._btn_tickets = self._sb_btn(nav, "Tickets",
                                          lambda: self._show_view("tickets"))
        self._btn_tickets.pack(fill=tk.X, pady=(0, 6))

        self._btn_info = self._sb_btn(nav, "Informações",
                                       lambda: self._show_view("info"))
        self._btn_info.pack(fill=tk.X)

        # spacer
        tk.Frame(sb, bg=_DK).pack(fill=tk.BOTH, expand=True)

        # QR placeholder + versão
        qr_frm = tk.Frame(sb, bg=_DK, padx=14, pady=14)
        qr_frm.pack(fill=tk.X)
        qr_box = tk.Canvas(qr_frm, width=64, height=64, bg="#2a2a3e",
                           highlightthickness=0)
        qr_box.pack()
        qr_box.create_rectangle(8, 8, 28, 28, fill=_WH, outline="")
        qr_box.create_rectangle(12, 12, 24, 24, fill="#2a2a3e", outline="")
        qr_box.create_rectangle(36, 8, 56, 28, fill=_WH, outline="")
        qr_box.create_rectangle(40, 12, 52, 24, fill="#2a2a3e", outline="")
        qr_box.create_rectangle(8, 36, 28, 56, fill=_WH, outline="")
        qr_box.create_rectangle(12, 40, 24, 52, fill="#2a2a3e", outline="")
        qr_box.create_rectangle(36, 36, 42, 42, fill=_WH, outline="")
        qr_box.create_rectangle(44, 44, 50, 50, fill=_WH, outline="")
        qr_box.create_rectangle(36, 50, 56, 56, fill=_WH, outline="")
        tk.Label(qr_frm, text="v3.3.0", font=self._fS,
                 bg=_DK, fg=_HI).pack(pady=(6, 0))

    def _sb_btn(self, master, label, cmd):
        frm = tk.Frame(master, bg=_DK, cursor="hand2")
        frm.bind("<Button-1>", lambda _: cmd())
        frm.bind("<Enter>", lambda _: self._sb_hover(frm, True))
        frm.bind("<Leave>", lambda _: self._sb_hover(frm, False))

        inner = tk.Frame(frm, bg=_DK, padx=10, pady=9)
        inner.pack(fill=tk.X)
        inner.bind("<Button-1>", lambda _: cmd())
        inner.bind("<Enter>", lambda _: self._sb_hover(frm, True))
        inner.bind("<Leave>", lambda _: self._sb_hover(frm, False))

        icon_c = tk.Canvas(inner, width=16, height=16, bg=_DK,
                           highlightthickness=0)
        self._draw_icon(icon_c, label)
        icon_c.pack(side=tk.LEFT)
        icon_c.bind("<Button-1>", lambda _: cmd())

        lbl = tk.Label(inner, text=label, font=self._fN,
                       bg=_DK, fg="#d1d5db")
        lbl.pack(side=tk.LEFT, padx=(8, 0))
        lbl.bind("<Button-1>", lambda _: cmd())
        lbl.bind("<Enter>", lambda _: self._sb_hover(frm, True))
        lbl.bind("<Leave>", lambda _: self._sb_hover(frm, False))

        frm._label  = lbl
        frm._icon   = icon_c
        frm._inner  = inner
        frm._active = False
        return frm

    def _draw_icon(self, c, label):
        c.delete("all")
        if "Ticket" in label:
            c.create_rectangle(1, 1, 15, 15, outline="#d1d5db", width=1)
            c.create_line(4, 5, 12, 5, fill="#d1d5db", width=1)
            c.create_line(4, 8, 12, 8, fill="#d1d5db", width=1)
            c.create_line(4, 11, 9, 11, fill="#d1d5db", width=1)
        else:
            c.create_rectangle(1, 1, 15, 11, outline="#d1d5db", width=1)
            c.create_line(5, 11, 5, 15, fill="#d1d5db", width=1)
            c.create_line(11, 11, 11, 15, fill="#d1d5db", width=1)
            c.create_line(3, 15, 13, 15, fill="#d1d5db", width=1)

    def _sb_hover(self, frm, on):
        # só aplica hover se não for o ativo
        if getattr(frm, "_active", False):
            return
        bg = "#252545" if on else _DK
        for w in [frm, frm._inner, frm._label, frm._icon]:
            try: w.config(bg=bg)
            except Exception: pass

    def _sb_set_active(self, active_frm):
        for frm in [self._btn_tickets, self._btn_info]:
            is_active = (frm is active_frm)
            frm._active = is_active
            bg = _G if is_active else _DK
            fg = _WH if is_active else "#d1d5db"
            for w in [frm, frm._inner, frm._label, frm._icon]:
                try: w.config(bg=bg)
                except Exception: pass
            frm._label.config(fg=fg)

    # ── VIEWS ─────────────────────────────────────────────────────────────────
    def _show_view(self, name):
        for v in [self._view_tickets, self._view_info, self._view_chat]:
            v.pack_forget()
        if name == "tickets":
            self._view_tickets.pack(fill=tk.BOTH, expand=True)
            self._sb_set_active(self._btn_tickets)
        elif name == "info":
            self._view_info.pack(fill=tk.BOTH, expand=True)
            self._sb_set_active(self._btn_info)
        elif name == "chat":
            self._view_chat.pack(fill=tk.BOTH, expand=True)

    # ── TICKETS VIEW ──────────────────────────────────────────────────────────
    def _build_tickets_view(self):
        self._view_tickets = tk.Frame(self._main_area, bg=_WH)

        # header
        hdr = tk.Frame(self._view_tickets, bg=_WH, padx=18, pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Meus Tickets", font=self._fH,
                 bg=_WH, fg=_DK).pack(side=tk.LEFT)
        _flat_btn(hdr, "+ Novo Ticket", self._open_novo,
                  font=self._fBT, padx=16, pady=7).pack(side=tk.RIGHT)
        _hsep(self._view_tickets).pack(fill=tk.X)

        # tabela
        tbl_wrap = tk.Frame(self._view_tickets, bg=_WH)
        tbl_wrap.pack(fill=tk.BOTH, expand=True)

        # header da tabela
        th = tk.Frame(tbl_wrap, bg=_WH)
        th.pack(fill=tk.X)
        _hsep(th).pack(fill=tk.X)
        th_row = tk.Frame(th, bg=_WH)
        th_row.pack(fill=tk.X)
        cols = [("Ticket", 70), ("Prioridade", 90), ("Assunto / Descrição", 260),
                ("Tipo de Serviço", 160), ("St.", 40), ("Operador", 100),
                ("Criado", 90), ("", 40)]
        for text, w in cols:
            tk.Label(th_row, text=text, font=self._fS, bg=_WH, fg=_MU,
                     width=w // 7, anchor="w",
                     padx=10, pady=8).pack(side=tk.LEFT)
        _hsep(th).pack(fill=tk.X)

        # corpo scrollável
        body_wrap = tk.Frame(tbl_wrap, bg=_WH)
        body_wrap.pack(fill=tk.BOTH, expand=True)

        vsb = tk.Scrollbar(body_wrap, orient=tk.VERTICAL,
                           bg=_WH, troughcolor=_WH,
                           relief=tk.FLAT, bd=0, width=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tbl_cv = tk.Canvas(body_wrap, bg=_WH, bd=0,
                                  highlightthickness=0,
                                  yscrollcommand=vsb.set)
        self._tbl_cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=self._tbl_cv.yview)

        self._tbl_inner = tk.Frame(self._tbl_cv, bg=_WH)
        self._tbl_win = self._tbl_cv.create_window(
            (0, 0), window=self._tbl_inner, anchor="nw")

        self._tbl_inner.bind("<Configure>", lambda _:
            self._tbl_cv.configure(scrollregion=self._tbl_cv.bbox("all")))
        self._tbl_cv.bind("<Configure>", lambda e:
            self._tbl_cv.itemconfig(self._tbl_win, width=e.width))
        self._tbl_cv.bind("<MouseWheel>", lambda e:
            self._tbl_cv.yview_scroll(-1 * (e.delta // 120), "units"))

        # rodapé
        _hsep(self._view_tickets).pack(fill=tk.X, side=tk.BOTTOM)
        ftr = tk.Frame(self._view_tickets, bg=_WH, padx=16, pady=8)
        ftr.pack(fill=tk.X, side=tk.BOTTOM)
        self._lbl_count = tk.Label(ftr, text="", font=self._fS,
                                    bg=_WH, fg=_MU)
        self._lbl_count.pack(side=tk.RIGHT)

    def _render_tickets(self):
        for w in self._tbl_inner.winfo_children():
            w.destroy()

        if not self._tickets:
            tk.Label(self._tbl_inner,
                     text="Nenhum chamado encontrado.",
                     font=self._fN, bg=_WH, fg=_HI,
                     pady=40).pack()
            self._lbl_count.config(text="0 itens")
            return

        for t in self._tickets:
            self._render_row(t)

        n = len(self._tickets)
        self._lbl_count.config(text=f"Mostrando 1 à {n} de {n} itens.")

    def _render_row(self, t):
        is_sel = self._selected and self._selected["id"] == t["id"]
        bg     = "#e6faf7" if is_sel else _WH
        hover  = "#f0fdf9"

        row = tk.Frame(self._tbl_inner, bg=bg, cursor="hand2")
        row.pack(fill=tk.X)
        _hsep(self._tbl_inner, "#f1f5f9").pack(fill=tk.X)

        def cell(text, width, fg=_TX, font=None, anchor="w"):
            lbl = tk.Label(row, text=text, font=font or self._fN,
                           bg=bg, fg=fg, width=width // 7,
                           anchor=anchor, padx=10, pady=10,
                           wraplength=width - 20)
            lbl.pack(side=tk.LEFT)
            return lbl

        # número
        cell(t["numero"], 70, fg=_G, font=self._fB)

        # prioridade — pill
        prio = t.get("prioridade", "Normal")
        bg_p, fg_p = _pr(prio)
        pfrm = tk.Frame(row, bg=bg, width=90, padx=10)
        pfrm.pack(side=tk.LEFT)
        pfrm.pack_propagate(False)
        pill = tk.Label(pfrm, text=prio, font=self._fS,
                        bg=bg_p, fg=fg_p, padx=8, pady=3)
        pill.pack(pady=10)

        # assunto
        assunto_short = t["assunto"][:42] + ("…" if len(t["assunto"]) > 42 else "")
        cell(assunto_short, 240, fg=_TX, font=self._fN)

        # serviço
        cell(t.get("servico", "—"), 150, fg=_MU, font=self._fS)

        # status — ícone check
        st_frm = tk.Frame(row, bg=bg, width=50, padx=10)
        st_frm.pack(side=tk.LEFT)
        st_frm.pack_propagate(False)
        bg_s, _ = _st(t["status"])
        st_c = tk.Canvas(st_frm, width=22, height=22,
                         bg=bg, highlightthickness=0)
        st_c.pack(pady=9)
        st_c.create_oval(1, 1, 21, 21, fill=_DK, outline="")
        st_c.create_line(5, 11, 9, 15, fill=_WH, width=2)
        st_c.create_line(9, 15, 17, 7, fill=_WH, width=2)

        # operador
        op_frm = tk.Frame(row, bg=bg, width=100, padx=10)
        op_frm.pack(side=tk.LEFT)
        op_frm.pack_propagate(False)
        tk.Label(op_frm, text=t.get("responsavel", "—"),
                 font=self._fB, bg=bg, fg=_TX, anchor="w").pack(anchor="w", pady=(10, 0))
        tk.Label(op_frm, text=t.get("status", ""),
                 font=self._fS, bg=bg, fg=_MU, anchor="w").pack(anchor="w", pady=(0, 8))

        # data
        cell(t["criado_em"], 90, fg=_MU, font=self._fS)

        # botão olho
        eye_frm = tk.Frame(row, bg=bg, width=46, padx=6)
        eye_frm.pack(side=tk.LEFT)
        eye_frm.pack_propagate(False)
        eye_c = tk.Canvas(eye_frm, width=28, height=28,
                          bg=_WH, highlightthickness=1,
                          highlightbackground=_BD, cursor="hand2")
        eye_c.pack(pady=8)
        eye_c.create_oval(5, 9, 23, 19, outline=_MU, width=1)
        eye_c.create_oval(11, 11, 17, 17, fill=_MU, outline="")
        eye_c.bind("<Button-1>", lambda _, tk_=t: self._open_chat(tk_))
        eye_c.bind("<Enter>", lambda _, w=eye_c: w.config(bg="#f0f0f0"))
        eye_c.bind("<Leave>", lambda _, w=eye_c: w.config(bg=_WH))

        # bind click em toda a linha
        def on_click(_e, tk_=t): self._open_chat(tk_)
        def on_enter(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in row.winfo_children():
                    try: w.config(bg=hover)
                    except Exception: pass
                row.config(bg=hover)
        def on_leave(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in row.winfo_children():
                    try: w.config(bg=_WH)
                    except Exception: pass
                row.config(bg=_WH)

        for w in [row] + list(row.winfo_children()):
            if w is not eye_c:
                w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    # ── INFO VIEW ──────────────────────────────────────────────────────────────
    def _build_info_view(self):
        self._view_info = tk.Frame(self._main_area, bg=_WH)

        hdr = tk.Frame(self._view_info, bg=_WH, padx=18, pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Informações da Máquina", font=self._fH,
                 bg=_WH, fg=_DK).pack(side=tk.LEFT)
        _hsep(self._view_info).pack(fill=tk.X)

        # body scrollável
        info_vsb = tk.Scrollbar(self._view_info, orient=tk.VERTICAL,
                                bg=_WH, troughcolor=_WH, relief=tk.FLAT, bd=0, width=4)
        info_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        info_cv = tk.Canvas(self._view_info, bg="#f8fafc",
                             bd=0, highlightthickness=0,
                             yscrollcommand=info_vsb.set)
        info_cv.pack(fill=tk.BOTH, expand=True)
        info_vsb.config(command=info_cv.yview)

        self._info_inner = tk.Frame(info_cv, bg="#f8fafc", padx=20, pady=16)
        info_win = info_cv.create_window((0, 0), window=self._info_inner, anchor="nw")
        self._info_inner.bind("<Configure>", lambda _:
            info_cv.configure(scrollregion=info_cv.bbox("all")))
        info_cv.bind("<Configure>", lambda e:
            info_cv.itemconfig(info_win, width=e.width))

        self._render_info_placeholder()

    def _render_info_placeholder(self):
        for w in self._info_inner.winfo_children():
            w.destroy()
        tk.Label(self._info_inner, text="Carregando informações...",
                 font=self._fN, bg="#f8fafc", fg=_HI, pady=40).pack()

    def _render_info(self):
        for w in self._info_inner.winfo_children():
            w.destroy()

        m = self._machine_info

        def section(title):
            tk.Label(self._info_inner, text=title.upper(), font=self._fS,
                     bg="#f8fafc", fg=_MU, anchor="w",
                     padx=0, pady=(0)).pack(fill=tk.X, pady=(0, 8))

        def card():
            frm = tk.Frame(self._info_inner, bg=_WH,
                           highlightthickness=1, highlightbackground=_BD2)
            frm.pack(fill=tk.X, pady=(0, 20))
            return frm

        def row(parent, label, value, val_color=_TX):
            r = tk.Frame(parent, bg=_WH, padx=14, pady=0)
            r.pack(fill=tk.X)
            _hsep(r, "#f1f5f9").pack(fill=tk.X)
            inner = tk.Frame(r, bg=_WH, pady=8)
            inner.pack(fill=tk.X)
            tk.Label(inner, text=label, font=self._fN,
                     bg=_WH, fg=_MU, anchor="w").pack(side=tk.LEFT)
            tk.Label(inner, text=value, font=self._fB,
                     bg=_WH, fg=val_color, anchor="e").pack(side=tk.RIGHT)

        # seção máquina
        section("Máquina")
        c = card()
        row(c, "Hostname",       m.get("hostname", "—"))
        row(c, "Status",         "● Online" if m.get("online") else "● Offline",
            val_color=_G if m.get("online") else "#ef4444")
        row(c, "IP",             m.get("ip", "—"))
        row(c, "Usuário logado", m.get("logged_user", self._logged_user or "—"))
        row(c, "Último checkin", m.get("last_checkin", "—"))

        # seção ativos
        section("Ativos vinculados")
        ativos = m.get("ativos", [])
        if ativos:
            c2 = card()
            for i, a in enumerate(ativos):
                r = tk.Frame(c2, bg=_WH, padx=14, pady=0)
                r.pack(fill=tk.X)
                if i > 0:
                    _hsep(r, "#f1f5f9").pack(fill=tk.X)
                inner = tk.Frame(r, bg=_WH, pady=10)
                inner.pack(fill=tk.X)

                # ícone
                ic = tk.Canvas(inner, width=32, height=32, bg="#e8f5e9",
                               highlightthickness=0)
                ic.pack(side=tk.LEFT, padx=(0, 10))
                ic.create_rectangle(4, 6, 28, 22, outline="#2e7d32", width=1)
                ic.create_line(4, 22, 4, 26, fill="#2e7d32", width=1)
                ic.create_line(28, 22, 28, 26, fill="#2e7d32", width=1)
                ic.create_line(2, 26, 30, 26, fill="#2e7d32", width=1)

                info_col = tk.Frame(inner, bg=_WH)
                info_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
                tk.Label(info_col, text=a.get("nome", "—"), font=self._fB,
                         bg=_WH, fg=_TX, anchor="w").pack(anchor="w")
                tag = f"#{a.get('etiqueta','—')} · {a.get('categoria','')}"
                tk.Label(info_col, text=tag, font=self._fS,
                         bg=_WH, fg=_MU, anchor="w").pack(anchor="w")
        else:
            c2 = card()
            tk.Label(c2, text="Nenhum ativo vinculado.",
                     font=self._fN, bg=_WH, fg=_HI,
                     padx=14, pady=16, anchor="w").pack(fill=tk.X)

    # ── CHAT VIEW ─────────────────────────────────────────────────────────────
    def _build_chat_view(self):
        self._view_chat = tk.Frame(self._main_area, bg=_WH)

        # header
        hdr = tk.Frame(self._view_chat, bg=_WH, padx=14, pady=10)
        hdr.pack(fill=tk.X)

        back_btn = tk.Button(hdr, text="←", font=self._fSB,
                             bg=_WH, fg=_TX,
                             relief=tk.FLAT, bd=0,
                             highlightthickness=1, highlightbackground=_BD,
                             padx=8, pady=4, cursor="hand2",
                             command=lambda: self._show_view("tickets"))
        back_btn.pack(side=tk.LEFT, padx=(0, 12))

        info_col = tk.Frame(hdr, bg=_WH)
        info_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._chat_num  = tk.Label(info_col, text="", font=self._fS,
                                    bg=_WH, fg=_HI, anchor="w")
        self._chat_num.pack(anchor="w")
        self._chat_subj = tk.Label(info_col, text="", font=self._fSB,
                                    bg=_WH, fg=_DK, anchor="w", wraplength=500)
        self._chat_subj.pack(anchor="w")

        self._chat_badge = tk.Label(hdr, text="", font=self._fS,
                                     padx=30, pady=16)
        self._chat_badge.pack(side=tk.RIGHT, anchor="n", pady=4)
        _hsep(self._view_chat).pack(fill=tk.X)

        # mensagens
        msgs_wrap = tk.Frame(self._view_chat, bg="#f8fafc")
        msgs_wrap.pack(fill=tk.BOTH, expand=True)

        msg_vsb = tk.Scrollbar(msgs_wrap, orient=tk.VERTICAL,
                               bg="#f8fafc", troughcolor="#f8fafc",
                               relief=tk.FLAT, bd=0, width=3)
        msg_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._chat_cv = tk.Canvas(msgs_wrap, bg="#f8fafc",
                                   bd=0, highlightthickness=0,
                                   yscrollcommand=msg_vsb.set)
        self._chat_cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msg_vsb.config(command=self._chat_cv.yview)

        self._chat_inner = tk.Frame(self._chat_cv, bg="#f8fafc")
        self._chat_win = self._chat_cv.create_window(
            (0, 0), window=self._chat_inner, anchor="nw")

        self._chat_inner.bind("<Configure>", lambda _:
            self._chat_cv.configure(scrollregion=self._chat_cv.bbox("all")))
        self._chat_cv.bind("<Configure>", self._on_chat_resize)
        self._chat_cv.bind("<MouseWheel>", lambda e:
            self._chat_cv.yview_scroll(-1 * (e.delta // 120), "units"))

        # reply bar
        reply_wrap = tk.Frame(self._view_chat, bg=_WH)
        reply_wrap.pack(fill=tk.X, side=tk.BOTTOM)
        _hsep(reply_wrap).pack(fill=tk.X)
        reply_inner = tk.Frame(reply_wrap, bg=_WH, padx=14, pady=10)
        reply_inner.pack(fill=tk.X)

        self._reply = tk.Text(
            reply_inner, height=5, font=self._fM,
            bg="#f8fafc", fg=_TX,
            insertbackground=_TX,
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=_BD2,
            highlightcolor=_G,
            padx=11, pady=8, wrap=tk.WORD,
        )
        self._reply.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._reply_ph = "Escreva sua resposta...  (Enter para enviar)"
        self._reply.insert("1.0", self._reply_ph)
        self._reply.config(fg=_HI)
        self._reply.bind("<FocusIn>",      self._reply_in)
        self._reply.bind("<FocusOut>",     self._reply_out)
        self._reply.bind("<Return>",       self._reply_enter)
        self._reply.bind("<Shift-Return>", lambda _: None)

        _flat_btn(reply_inner, "↑",
                  self._send_reply,
                  font=tkfont.Font(family="Segoe UI", size=13, weight="bold"),
                  width=10, pady=15).pack(side=tk.LEFT, padx=(10, 0))

    def _on_chat_resize(self, e):
        self._chat_cv.itemconfig(self._chat_win, width=e.width)
        wrap = max(e.width - 140, 200)
        for outer in self._chat_inner.winfo_children():
            for child in outer.winfo_children():
                if isinstance(child, tk.Label):
                    try: child.config(wraplength=wrap)
                    except Exception: pass

    # ── reply helpers ─────────────────────────────────────────────────────────
    def _reply_in(self, _e):
        if self._reply.get("1.0", tk.END).strip() == self._reply_ph:
            self._reply.delete("1.0", tk.END)
            self._reply.config(fg=_TX)

    def _reply_out(self, _e):
        if not self._reply.get("1.0", tk.END).strip():
            self._reply.insert("1.0", self._reply_ph)
            self._reply.config(fg=_HI)

    def _reply_enter(self, e):
        if not (e.state & 0x1):
            self._send_reply()
            return "break"

    # ── abrir chat ────────────────────────────────────────────────────────────
    def _open_chat(self, ticket):
        self._selected = ticket
        self._render_tickets()

        self._chat_num.config(text=ticket["numero"])
        self._chat_subj.config(text=ticket["assunto"])
        bg_s, fg_s = _st(ticket["status"])
        self._chat_badge.config(text=ticket["status"], bg=bg_s, fg=fg_s)

        self._show_view("chat")
        self._load_detail(ticket)

    # ── API calls ─────────────────────────────────────────────────────────────
    def _load_tickets(self):
        if not self._email:
            return
        def fetch():
            try:
                data = self._api.get(
                    "/tickets/api/agent/list/",
                    email=self._email,
                    logged_user=self._logged_user,
                )
                self._win.after(0,
                    lambda: self._set_tickets(data.get("tickets", [])))
            except Exception as ex:
                logger.error(f"load_tickets: {ex}")
        threading.Thread(target=fetch, daemon=True).start()

    def _set_tickets(self, tickets):
        self._tickets = tickets
        self._render_tickets()

    def _load_detail(self, ticket):
        def fetch():
            try:
                data = self._api.get(f"/tickets/api/agent/{ticket['id']}/")
                self._win.after(0,
                    lambda: self._render_chat(data.get("historico", [])))
            except Exception as ex:
                logger.error(f"load_detail: {ex}")
        threading.Thread(target=fetch, daemon=True).start()

    def _load_machine_info(self):
        def fetch():
            try:
                data = self._api.get("/api/inventario/agent/machine/")
                if data.get("ok"):
                    self._machine_info = data
                    self._win.after(0, self._render_info)
            except Exception as ex:
                logger.warning(f"machine info: {ex}")
        threading.Thread(target=fetch, daemon=True).start()

    def _send_reply(self):
        if not self._selected:
            return
        text = self._reply.get("1.0", tk.END).strip()
        if not text or text == self._reply_ph:
            return
        self._reply.delete("1.0", tk.END)
        self._reply.insert("1.0", self._reply_ph)
        self._reply.config(fg=_HI)

        def send():
            try:
                data = self._api.post(
                    f"/tickets/api/agent/{self._selected['id']}/reply/",
                    {"conteudo": text, "email": self._email},
                )
                if data.get("ok"):
                    self._win.after(0, lambda: self._append_msg(data["acao"]))
                else:
                    logger.error(f"reply: {data.get('error')}")
            except Exception as ex:
                logger.error(f"send_reply: {ex}")
        threading.Thread(target=send, daemon=True).start()

    # ── render chat ───────────────────────────────────────────────────────────
    def _render_chat(self, historico):
        self._historico = historico
        for w in self._chat_inner.winfo_children():
            w.destroy()

        if not historico:
            tk.Label(self._chat_inner,
                     text="Nenhuma mensagem ainda.",
                     font=self._fS, bg="#f8fafc", fg=_HI,
                     pady=32).pack()
        else:
            # mais antigo primeiro → mais novo no fim (scroll para baixo)
            for msg in reversed(historico):
                self._render_bubble(msg)

        self._chat_cv.update_idletasks()
        self._chat_cv.yview_moveto(1.0)   # scroll para baixo (mais recente)

    def _render_bubble(self, msg):
        is_staff = msg.get("is_staff", False)
        cv_w     = self._chat_cv.winfo_width()
        wrap     = max(cv_w - 140, 220)

        outer = tk.Frame(self._chat_inner, bg="#f8fafc")
        outer.pack(fill=tk.X, padx=18, pady=5)

        meta = tk.Frame(outer, bg="#f8fafc")
        meta.pack(fill=tk.X)

        if is_staff:
            # staff → esquerda
            tk.Label(meta, text=msg["autor"], font=self._fS,
                     bg="#f8fafc", fg=_MU).pack(side=tk.LEFT)
            tk.Label(meta, text=msg["criado_em"], font=self._fS,
                     bg="#f8fafc", fg=_HI).pack(side=tk.LEFT, padx=(6, 0))
        else:
            # usuário → direita
            tk.Label(meta, text=msg["criado_em"], font=self._fS,
                     bg="#f8fafc", fg=_HI).pack(side=tk.RIGHT, padx=(6, 0))
            tk.Label(meta, text=msg["autor"], font=self._fS,
                     bg="#f8fafc", fg=_MU).pack(side=tk.RIGHT)

        if is_staff:
            bubble = tk.Label(
                outer, text=msg["conteudo"], font=self._fM,
                bg=_WH, fg=_TX,
                wraplength=wrap, justify=tk.LEFT, anchor="w",
                padx=13, pady=9,
                highlightthickness=1, highlightbackground=_BD2,
            )
            bubble.pack(anchor="w", pady=(3, 0))
        else:
            bubble = tk.Label(
                outer, text=msg["conteudo"], font=self._fM,
                bg=_G, fg=_WH,
                wraplength=wrap, justify=tk.LEFT, anchor="w",
                padx=13, pady=9,
            )
            bubble.pack(anchor="e", pady=(3, 0))

    def _append_msg(self, msg):
        self._historico.insert(0, msg)
        for w in self._chat_inner.winfo_children():
            w.destroy()
        for m in reversed(self._historico):
            self._render_bubble(m)
        self._chat_cv.update_idletasks()
        self._chat_cv.yview_moveto(1.0)

    # ── novo ticket ───────────────────────────────────────────────────────────
    def _open_novo(self):
        _NovoTicketModal(
            parent_win=self._win,
            api=self._api,
            logged_user=self._logged_user,
            email_salvo=self._email,
            on_success=self._on_ticket_criado,
        )

    def _on_ticket_criado(self, data, email: str):
        self._email    = email
        self._selected = None
        self._load_tickets()

    def _on_close(self):
        self.alive = False
        ChamadosManager._instance = None
        self._win.destroy()

    def lift(self):
        try:
            self._win.lift()
            self._win.focus_force()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# ChamadosManager — API pública
# ═════════════════════════════════════════════════════════════════════════════
class ChamadosManager:
    """
    from chamados import ChamadosManager
    ChamadosManager.open(server_url="...", token_hash="...", logged_user="joao")
    """
    _instance: Optional[_ChamadosWindow] = None
    _lock = threading.Lock()

    @classmethod
    def open(cls, server_url: str, token_hash: str,
             logged_user: str = "") -> None:
        with cls._lock:
            if cls._instance and cls._instance.alive:
                cls._instance.lift()
                return
            cls._instance = _ChamadosWindow(server_url, token_hash, logged_user)


# ─────────────────────────────────────────────────────────────────────────────
# __main__ — smoke-test (sem servidor real)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("chamados.py v4 — smoke test")

    _MOCK = {
        "tickets": [
            {"id":281,"numero":"#281","prioridade":"Médio",
             "assunto":"REQUISIÇÃO — Pedido de periférico teclado sem fio",
             "servico":"Periféricos / Teclado","status":"Resolvido",
             "responsavel":"José","criado_em":"há 2 meses"},
            {"id":230,"numero":"#230","prioridade":"Planejado",
             "assunto":"REQUISIÇÃO — Troca de peça notebook",
             "servico":"Notebooks / Troca de peça","status":"Resolvido",
             "responsavel":"José","criado_em":"há 3 meses"},
            {"id":295,"numero":"#295","prioridade":"Alta",
             "assunto":"Impressora do andar 3 não reconhecida",
             "servico":"Hardware / Impressora","status":"Em andamento",
             "responsavel":"Ana","criado_em":"há 5 dias"},
            {"id":310,"numero":"#310","prioridade":"Normal",
             "assunto":"Lentidão no sistema ao abrir relatórios",
             "servico":"Software / Sistema","status":"Aberto",
             "responsavel":"—","criado_em":"há 1 dia"},
        ],
        "historico": {
            281: [
                {"id":2,"autor":"José","is_staff":True,
                 "conteudo":"Teclado sem fio separado. Retire na recepção do TI.","criado_em":"10/01 10:05"},
                {"id":1,"autor":"Você","is_staff":False,
                 "conteudo":"Preciso de um teclado sem fio para uso no escritório.","criado_em":"10/01 09:14"},
            ],
            230: [
                {"id":3,"autor":"José","is_staff":True,
                 "conteudo":"Peça substituída. Notebook liberado para retirada.","criado_em":"05/12 14:00"},
                {"id":2,"autor":"José","is_staff":True,
                 "conteudo":"Peça chegou. Realizaremos a troca hoje.","criado_em":"05/12 09:30"},
                {"id":1,"autor":"Você","is_staff":False,
                 "conteudo":"Bateria do notebook não carrega. Preciso de troca.","criado_em":"01/12 16:20"},
            ],
            295: [
                {"id":2,"autor":"Ana","is_staff":True,
                 "conteudo":"Verificando o driver. Aguarde.","criado_em":"13/03 11:00"},
                {"id":1,"autor":"Você","is_staff":False,
                 "conteudo":"Impressora sumiu da lista após atualização do Windows.","criado_em":"12/03 14:30"},
            ],
            310: [
                {"id":1,"autor":"Você","is_staff":False,
                 "conteudo":"Sistema lento ao abrir relatórios desde ontem. Demora +3 min.","criado_em":"16/03 09:14"},
            ],
        },
        "machine": {
            "ok": True,
            "hostname": "DESKTOP-MOCK01",
            "online": True,
            "ip": "192.168.1.42",
            "logged_user": "joao.silva",
            "last_checkin": "17/03/2026 08:00",
            "ativos": [
                {"nome":"Dell OptiPlex 7090","etiqueta":"ETQ-0042","categoria":"Computador"},
                {"nome":"Monitor LG 24\"",    "etiqueta":"ETQ-0101","categoria":"Monitor"},
                {"nome":"Teclado Logitech",   "etiqueta":"ETQ-0203","categoria":"Periférico"},
            ],
        },
    }

    def _mock_get(self, path, **params):
        if "list" in path:
            return {"ok": True, "tickets": _MOCK["tickets"]}
        if "machine" in path:
            return _MOCK["machine"]
        for tid, hist in _MOCK["historico"].items():
            if f"/{tid}/" in path:
                t = next(x for x in _MOCK["tickets"] if x["id"] == tid)
                return {"ok": True, "ticket": t, "historico": hist}
        return {"ok": True, "tickets": []}

    def _mock_post(self, path, body):
        if "criar" in path:
            nid = max(x["id"] for x in _MOCK["tickets"]) + 1
            t = {"id": nid, "numero": f"#{nid}", "prioridade": "Normal",
                 "assunto": body["assunto"],
                 "servico": body.get("tipo_chamado", "Suporte técnico"),
                 "status": "Aberto", "responsavel": "—", "criado_em": "agora"}
            _MOCK["tickets"].insert(0, t)
            _MOCK["historico"][nid] = [
                {"id": 1, "autor": "Você", "is_staff": False,
                 "conteudo": body["descricao"], "criado_em": "agora"}]
            return {"ok": True, "numero": t["numero"], "id": nid}
        if "reply" in path:
            tid = int(path.split("/")[-3])
            msg = {"id": 99, "autor": "Você", "is_staff": False,
                   "conteudo": body["conteudo"], "criado_em": "agora"}
            _MOCK["historico"].setdefault(tid, []).insert(0, msg)
            return {"ok": True, "acao": msg}
        return {"ok": True}

    _ApiClient.get  = _mock_get
    _ApiClient.post = _mock_post

    # ── força e-mail mock para que _load_tickets dispare ──────────────────
    _MOCK_EMAIL = "joao.silva@empresa.com"
    _EmailStore.save("joao.silva", _MOCK_EMAIL)

    inst = _ChamadosWindow.__new__(_ChamadosWindow)
    inst._api          = _ApiClient("http://mock", "mock")
    inst._logged_user  = "joao.silva"
    inst._email        = _MOCK_EMAIL          # ← era "" antes, tickets nunca carregavam
    inst._tickets      = []
    inst._selected     = None
    inst._historico    = []
    inst._machine_info = {}
    inst.alive         = True
    ChamadosManager._instance = inst
    inst._run()