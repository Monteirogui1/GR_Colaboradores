"""
chamados.py — Janela de chamados de suporte para o Inventory Agent

Uso (idêntico ao notification.py):
    from chamados import ChamadosManager

    ChamadosManager.open(
        server_url="http://192.168.1.10:8000",
        token_hash="abc123...",
    )

Requisitos do servidor (apps/tickets/views.py + urls.py):
    GET  /tickets/api/agent/list/                      → lista tickets
    GET  /tickets/api/agent/<pk>/                      → detalhe + histórico
    POST /tickets/api/agent/<pk>/reply/                → responder
    POST /tickets/api/agent/criar/                     → novo ticket
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox
from typing import Optional
import logging
import requests

logger = logging.getLogger("AgentTray")


# ═════════════════════════════════════════════════════════════════════════════
# Paleta
# ═════════════════════════════════════════════════════════════════════════════
_C = {
    # sidebar escura
    "sb_bg":       "#0f172a",
    "sb_hdr":      "#0d1117",
    "sb_hover":    "#161f2e",
    "sb_active":   "#1e3354",
    "sb_text":     "#f8fafc",
    "sb_muted":    "#475569",
    "sb_num":      "#334155",
    "sb_entry_bg": "#131c2e",
    "sb_entry_bd": "#1e293b",
    # main area
    "main_bg":     "#ffffff",
    "chat_bg":     "#f8fafc",
    "border":      "#f1f5f9",
    "border_md":   "#e2e8f0",
    "text":        "#0f172a",
    "muted":       "#64748b",
    "hint":        "#94a3b8",
    # balões
    "staff_bg":    "#2563eb",
    "staff_fg":    "#ffffff",
    "user_bg":     "#ffffff",
    "user_bd":     "#e2e8f0",
    "user_fg":     "#1e293b",
    # botões / inputs
    "blue":        "#2563eb",
    "blue_hov":    "#1d4ed8",
    "inp_bg":      "#f8fafc",
    "inp_bd":      "#e2e8f0",
    "inp_focus":   "#2563eb",
}

# Status → (pill_bg, pill_fg, stripe)
_STATUS = {
    "Aberto":       ("#dbeafe", "#1e40af", "#3b82f6"),
    "Em andamento": ("#fef3c7", "#92400e", "#f59e0b"),
    "Resolvido":    ("#d1fae5", "#065f46", "#10b981"),
    "Fechado":      ("#f1f5f9", "#475569", "#94a3b8"),
    "Cancelado":    ("#fee2e2", "#7f1d1d", "#ef4444"),
}

def _st(status):
    return _STATUS.get(status, ("#f1f5f9", "#475569", "#94a3b8"))


# ═════════════════════════════════════════════════════════════════════════════
# Helpers de widget
# ═════════════════════════════════════════════════════════════════════════════
def _entry(master, textvariable=None, **kw):
    e = tk.Entry(
        master,
        textvariable=textvariable,
        bg=_C["inp_bg"], fg=_C["text"],
        insertbackground=_C["text"],
        relief=tk.FLAT, bd=0,
        highlightthickness=1,
        highlightbackground=_C["inp_bd"],
        highlightcolor=_C["inp_focus"],
        **kw,
    )
    e.bind("<FocusIn>",  lambda _: e.config(highlightbackground=_C["inp_focus"]))
    e.bind("<FocusOut>", lambda _: e.config(highlightbackground=_C["inp_bd"]))
    return e


def _dark_entry(master, textvariable=None, **kw):
    e = tk.Entry(
        master,
        textvariable=textvariable,
        bg=_C["sb_entry_bg"], fg="#94a3b8",
        insertbackground="#94a3b8",
        relief=tk.FLAT, bd=0,
        highlightthickness=1,
        highlightbackground=_C["sb_entry_bd"],
        highlightcolor="#2563eb",
        **kw,
    )
    e.bind("<FocusIn>",  lambda _: e.config(highlightbackground="#2563eb", fg="#e2e8f0"))
    e.bind("<FocusOut>", lambda _: e.config(highlightbackground=_C["sb_entry_bd"], fg="#94a3b8"))
    return e


def _btn_primary(master, text, cmd, **kw):
    return tk.Button(
        master, text=text, command=cmd,
        bg=_C["blue"], fg="#ffffff",
        activebackground=_C["blue_hov"], activeforeground="#ffffff",
        relief=tk.FLAT, bd=0, cursor="hand2", **kw,
    )


def _btn_secondary(master, text, cmd, **kw):
    return tk.Button(
        master, text=text, command=cmd,
        bg="#ffffff", fg=_C["muted"],
        activebackground=_C["inp_bg"], activeforeground=_C["text"],
        relief=tk.FLAT, bd=0,
        highlightthickness=1, highlightbackground=_C["inp_bd"],
        cursor="hand2", **kw,
    )


def _hsep(master, color=None):
    return tk.Frame(master, bg=color or _C["border"], height=1)


def _vsep(master):
    return tk.Frame(master, bg="#1e293b", width=1)


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
        r = self._sess.get(f"{self._base}{path}", params=params, timeout=12)
        r.raise_for_status()
        return r.json()

    def post(self, path, body: dict):
        r = self._sess.post(f"{self._base}{path}", json=body, timeout=12)
        r.raise_for_status()
        return r.json()


# ═════════════════════════════════════════════════════════════════════════════
# _NovoTicketModal
# ═════════════════════════════════════════════════════════════════════════════
class _NovoTicketModal:

    def __init__(self, parent_win: tk.Tk, api: _ApiClient, on_success):
        self._api        = api
        self._on_success = on_success

        win = tk.Toplevel(parent_win)
        self._win = win
        win.title("Novo chamado")
        win.geometry("440x420")
        win.resizable(False, False)
        win.configure(bg=_C["main_bg"])
        win.grab_set()
        win.focus_force()
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        fT = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        fL = tkfont.Font(family="Segoe UI", size=8)
        fI = tkfont.Font(family="Segoe UI", size=10)
        fB = tkfont.Font(family="Segoe UI", size=9,  weight="bold")
        fS = tkfont.Font(family="Segoe UI", size=9)

        # Header
        hdr = tk.Frame(win, bg=_C["main_bg"], padx=18, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Novo chamado", font=fT,
                 bg=_C["main_bg"], fg=_C["text"]).pack(side=tk.LEFT)
        tk.Button(hdr, text="✕", font=fS,
                  bg=_C["main_bg"], fg=_C["hint"],
                  relief=tk.FLAT, bd=0, cursor="hand2",
                  command=win.destroy).pack(side=tk.RIGHT)
        _hsep(win, _C["border_md"]).pack(fill=tk.X)

        # Body
        body = tk.Frame(win, bg=_C["main_bg"], padx=18, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        def flbl(master, text, req=False):
            frm = tk.Frame(master, bg=_C["main_bg"])
            frm.pack(fill=tk.X, pady=(0, 4))
            tk.Label(frm, text=text.upper(), font=fL,
                     bg=_C["main_bg"], fg=_C["muted"]).pack(side=tk.LEFT)
            if req:
                tk.Label(frm, text=" *", font=fL,
                         bg=_C["main_bg"], fg="#f43f5e").pack(side=tk.LEFT)

        flbl(body, "Assunto", req=True)
        self._assunto_var = tk.StringVar()
        _entry(body, textvariable=self._assunto_var, font=fI).pack(
            fill=tk.X, ipady=7, pady=(0, 14))

        row = tk.Frame(body, bg=_C["main_bg"])
        row.pack(fill=tk.X, pady=(0, 14))

        col_l = tk.Frame(row, bg=_C["main_bg"])
        col_l.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        flbl(col_l, "Tipo de serviço")
        self._tipo_var = tk.StringVar()
        ttk.Combobox(col_l, textvariable=self._tipo_var,
                     state="readonly", font=fI,
                     values=["Suporte técnico", "Acesso e permissões",
                             "Hardware / Equipamento", "Software / Sistema",
                             "Rede e conectividade", "Outros"]).pack(
            fill=tk.X, ipady=4)

        col_r = tk.Frame(row, bg=_C["main_bg"])
        col_r.pack(side=tk.LEFT, fill=tk.X, expand=True)
        flbl(col_r, "Urgência")
        self._urg_var = tk.StringVar(value="Normal")
        ttk.Combobox(col_r, textvariable=self._urg_var,
                     state="readonly", font=fI,
                     values=["Baixa", "Normal", "Alta", "Crítica"]).pack(
            fill=tk.X, ipady=4)

        flbl(body, "Descrição", req=True)
        self._desc = tk.Text(
            body, height=5, font=fI,
            bg=_C["inp_bg"], fg=_C["text"],
            insertbackground=_C["text"],
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=_C["inp_bd"],
            highlightcolor=_C["inp_focus"],
            padx=10, pady=8, wrap=tk.WORD,
        )
        self._desc.pack(fill=tk.X, pady=(0, 2))
        self._desc.bind("<FocusIn>",
            lambda _: self._desc.config(highlightbackground=_C["inp_focus"]))
        self._desc.bind("<FocusOut>",
            lambda _: self._desc.config(highlightbackground=_C["inp_bd"]))

        # Footer
        _hsep(win, _C["border_md"]).pack(fill=tk.X, side=tk.BOTTOM)
        footer = tk.Frame(win, bg=_C["main_bg"], padx=18, pady=12)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        _btn_secondary(footer, "Cancelar", win.destroy,
                       font=fS, padx=14, pady=6).pack(side=tk.RIGHT, padx=(8, 0))
        _btn_primary(footer, "Abrir chamado", self._submit,
                     font=fB, padx=14, pady=6).pack(side=tk.RIGHT)

    def _submit(self):
        assunto   = self._assunto_var.get().strip()
        tipo      = self._tipo_var.get().strip()
        descricao = self._desc.get("1.0", tk.END).strip()

        missing = []
        if not assunto:   missing.append("Assunto")
        if not descricao: missing.append("Descrição")
        if missing:
            messagebox.showerror("Campos obrigatórios",
                                 f"Preencha: {', '.join(missing)}.",
                                 parent=self._win)
            return

        def send():
            try:
                data = self._api.post("/tickets/api/agent/criar/", {
                    "tipo_chamado": tipo,
                    "assunto":      assunto,
                    "descricao":    descricao,
                })
                if data.get("ok"):
                    self._win.after(0, self._win.destroy)
                    self._win.after(300, lambda: self._on_success(data))
                else:
                    messagebox.showerror("Erro",
                        data.get("error", "Erro desconhecido"),
                        parent=self._win)
            except Exception as ex:
                logger.error(f"NovoTicket: {ex}")
                messagebox.showerror("Erro de conexão", str(ex),
                                     parent=self._win)

        threading.Thread(target=send, daemon=True).start()


# ═════════════════════════════════════════════════════════════════════════════
# _ChamadosWindow
# ═════════════════════════════════════════════════════════════════════════════
class _ChamadosWindow:

    def __init__(self, server_url: str, token_hash: str):
        self._api       = _ApiClient(server_url, token_hash)
        self._tickets   = []
        self._selected  = None
        self._historico = []
        self.alive      = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        win = tk.Tk()
        self._win = win
        win.title("Meus Chamados")
        win.geometry("980x640")
        win.minsize(780, 520)
        win.configure(bg=_C["main_bg"])
        win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._fN  = tkfont.Font(family="Segoe UI", size=9)
        self._fB  = tkfont.Font(family="Segoe UI", size=9,  weight="bold")
        self._fS  = tkfont.Font(family="Segoe UI", size=8)
        self._fSB = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._fM  = tkfont.Font(family="Segoe UI", size=10)
        self._fBT = tkfont.Font(family="Segoe UI", size=9,  weight="bold")

        outer = tk.Frame(win, bg=_C["main_bg"])
        outer.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(outer)
        _vsep(outer).pack(side=tk.LEFT, fill=tk.Y)
        self._build_main(outer)

        win.after(300, self._load_tickets)
        win.mainloop()

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=_C["sb_bg"], width=256)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        sb.pack_propagate(False)

        hdr_frame = tk.Frame(sb, bg=_C["sb_hdr"])
        hdr_frame.pack(fill=tk.X)
        hdr = tk.Frame(hdr_frame, bg=_C["sb_hdr"], padx=14, pady=13)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Meus chamados", font=self._fB,
                 bg=_C["sb_hdr"], fg=_C["sb_text"]).pack(side=tk.LEFT)
        _btn_primary(hdr, "+ Novo", self._novo_ticket,
                     font=self._fBT, padx=9, pady=3).pack(side=tk.RIGHT)
        tk.Frame(hdr_frame, bg="#1e293b", height=1).pack(fill=tk.X)

        srch_frm = tk.Frame(sb, bg=_C["sb_bg"], padx=12, pady=10)
        srch_frm.pack(fill=tk.X)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        self._search_e = _dark_entry(srch_frm, textvariable=self._search_var,
                                     font=self._fN)
        self._search_e.pack(fill=tk.X, ipady=6)
        self._search_e.insert(0, "Buscar chamado...")
        self._search_e.config(fg=_C["sb_muted"])
        self._search_e.bind("<FocusIn>",  self._search_in)
        self._search_e.bind("<FocusOut>", self._search_out)
        tk.Frame(sb, bg="#1e293b", height=1).pack(fill=tk.X)

        lista_wrap = tk.Frame(sb, bg=_C["sb_bg"])
        lista_wrap.pack(fill=tk.BOTH, expand=True)

        vsb = tk.Scrollbar(lista_wrap, orient=tk.VERTICAL,
                           bg=_C["sb_bg"], troughcolor=_C["sb_bg"],
                           relief=tk.FLAT, bd=0, width=3)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._list_cv = tk.Canvas(lista_wrap, bg=_C["sb_bg"],
                                  bd=0, highlightthickness=0,
                                  yscrollcommand=vsb.set)
        self._list_cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=self._list_cv.yview)

        self._list_inner = tk.Frame(self._list_cv, bg=_C["sb_bg"])
        self._list_win = self._list_cv.create_window(
            (0, 0), window=self._list_inner, anchor="nw")

        self._list_inner.bind("<Configure>", lambda _:
            self._list_cv.configure(scrollregion=self._list_cv.bbox("all")))
        self._list_cv.bind("<Configure>", lambda e:
            self._list_cv.itemconfig(self._list_win, width=e.width))
        self._list_cv.bind("<MouseWheel>", lambda e:
            self._list_cv.yview_scroll(-1 * (e.delta // 120), "units"))

    def _search_in(self, _e):
        if self._search_var.get() == "Buscar chamado...":
            self._search_e.delete(0, tk.END)
            self._search_e.config(fg="#e2e8f0")

    def _search_out(self, _e):
        if not self._search_var.get():
            self._search_e.insert(0, "Buscar chamado...")
            self._search_e.config(fg=_C["sb_muted"])

    # ── MAIN ─────────────────────────────────────────────────────────────────
    def _build_main(self, parent):
        main = tk.Frame(parent, bg=_C["main_bg"])
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._empty = tk.Frame(main, bg=_C["chat_bg"])
        self._empty.pack(fill=tk.BOTH, expand=True)
        tk.Label(self._empty,
                 text="Selecione um chamado para visualizar",
                 font=self._fN, bg=_C["chat_bg"], fg=_C["hint"]).place(
            relx=0.5, rely=0.5, anchor="center")

        self._tk_frame = tk.Frame(main, bg=_C["main_bg"])

        hdr_wrap = tk.Frame(self._tk_frame, bg=_C["main_bg"])
        hdr_wrap.pack(fill=tk.X)
        hdr = tk.Frame(hdr_wrap, bg=_C["main_bg"], padx=20, pady=14)
        hdr.pack(fill=tk.X)

        left = tk.Frame(hdr, bg=_C["main_bg"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._lbl_num = tk.Label(left, text="", font=self._fS,
                                  bg=_C["main_bg"], fg=_C["hint"], anchor="w")
        self._lbl_num.pack(anchor="w")
        self._lbl_sub = tk.Label(left, text="", font=self._fSB,
                                  bg=_C["main_bg"], fg=_C["text"], anchor="w",
                                  wraplength=460)
        self._lbl_sub.pack(anchor="w", pady=(2, 0))

        self._lbl_badge = tk.Label(hdr, text="", font=self._fS,
                                    padx=9, pady=3)
        self._lbl_badge.pack(side=tk.RIGHT, anchor="n", pady=4)
        _hsep(hdr_wrap).pack(fill=tk.X)

        chat_wrap = tk.Frame(self._tk_frame, bg=_C["chat_bg"])
        chat_wrap.pack(fill=tk.BOTH, expand=True)

        chat_vsb = tk.Scrollbar(chat_wrap, orient=tk.VERTICAL,
                                bg=_C["chat_bg"], troughcolor=_C["chat_bg"],
                                relief=tk.FLAT, bd=0, width=3)
        chat_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._chat_cv = tk.Canvas(chat_wrap, bg=_C["chat_bg"],
                                   bd=0, highlightthickness=0,
                                   yscrollcommand=chat_vsb.set)
        self._chat_cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chat_vsb.config(command=self._chat_cv.yview)

        self._chat_inner = tk.Frame(self._chat_cv, bg=_C["chat_bg"])
        self._chat_win = self._chat_cv.create_window(
            (0, 0), window=self._chat_inner, anchor="nw")

        self._chat_inner.bind("<Configure>", lambda _:
            self._chat_cv.configure(scrollregion=self._chat_cv.bbox("all")))
        self._chat_cv.bind("<Configure>", self._on_chat_resize)
        self._chat_cv.bind("<MouseWheel>", lambda e:
            self._chat_cv.yview_scroll(-1 * (e.delta // 120), "units"))

        reply_wrap = tk.Frame(self._tk_frame, bg=_C["main_bg"])
        reply_wrap.pack(fill=tk.X, side=tk.BOTTOM)
        _hsep(reply_wrap).pack(fill=tk.X)
        reply_inner = tk.Frame(reply_wrap, bg=_C["main_bg"], padx=14, pady=10)
        reply_inner.pack(fill=tk.X)

        self._reply = tk.Text(
            reply_inner, height=2, font=self._fM,
            bg=_C["inp_bg"], fg=_C["text"],
            insertbackground=_C["text"],
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=_C["inp_bd"],
            highlightcolor=_C["inp_focus"],
            padx=11, pady=8, wrap=tk.WORD,
        )
        self._reply.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._reply_ph = "Escreva sua resposta...  (Enter para enviar, Shift+Enter para nova linha)"
        self._reply.insert("1.0", self._reply_ph)
        self._reply.config(fg=_C["hint"])
        self._reply.bind("<FocusIn>",      self._reply_in)
        self._reply.bind("<FocusOut>",     self._reply_out)
        self._reply.bind("<Return>",       self._reply_enter)
        self._reply.bind("<Shift-Return>", lambda _: None)

        tk.Button(
            reply_inner, text="↑",
            font=tkfont.Font(family="Segoe UI", size=13, weight="bold"),
            bg=_C["blue"], fg="#ffffff",
            activebackground=_C["blue_hov"], activeforeground="#ffffff",
            relief=tk.FLAT, bd=0, width=2, pady=5, cursor="hand2",
            command=self._send_reply,
        ).pack(side=tk.LEFT, padx=(10, 0))

    def _on_chat_resize(self, e):
        self._chat_cv.itemconfig(self._chat_win, width=e.width)
        wrap = max(e.width - 130, 200)
        for outer in self._chat_inner.winfo_children():
            for child in outer.winfo_children():
                if isinstance(child, tk.Label):
                    try: child.config(wraplength=wrap)
                    except Exception: pass

    def _reply_in(self, _e):
        if self._reply.get("1.0", tk.END).strip() == self._reply_ph:
            self._reply.delete("1.0", tk.END)
            self._reply.config(fg=_C["text"])

    def _reply_out(self, _e):
        if not self._reply.get("1.0", tk.END).strip():
            self._reply.insert("1.0", self._reply_ph)
            self._reply.config(fg=_C["hint"])

    def _reply_enter(self, e):
        if not (e.state & 0x1):
            self._send_reply()
            return "break"

    # ── API ──────────────────────────────────────────────────────────────────
    def _load_tickets(self):
        def fetch():
            try:
                data = self._api.get("/tickets/api/agent/list/")
                self._win.after(0,
                    lambda: self._render_list(data.get("tickets", [])))
            except Exception as ex:
                logger.error(f"load_tickets: {ex}")
        threading.Thread(target=fetch, daemon=True).start()

    def _load_detail(self, ticket):
        def fetch():
            try:
                data = self._api.get(f"/tickets/api/agent/{ticket['id']}/")
                self._win.after(0,
                    lambda: self._render_chat(data.get("historico", [])))
            except Exception as ex:
                logger.error(f"load_detail: {ex}")
        threading.Thread(target=fetch, daemon=True).start()

    def _send_reply(self):
        if not self._selected:
            return
        text = self._reply.get("1.0", tk.END).strip()
        if not text or text == self._reply_ph:
            return
        self._reply.delete("1.0", tk.END)
        self._reply.insert("1.0", self._reply_ph)
        self._reply.config(fg=_C["hint"])

        def send():
            try:
                data = self._api.post(
                    f"/tickets/api/agent/{self._selected['id']}/reply/",
                    {"conteudo": text},
                )
                if data.get("ok"):
                    self._win.after(0, lambda: self._prepend_msg(data["acao"]))
                else:
                    logger.error(f"reply error: {data.get('error')}")
            except Exception as ex:
                logger.error(f"send_reply: {ex}")
        threading.Thread(target=send, daemon=True).start()

    # ── RENDER ───────────────────────────────────────────────────────────────
    def _filter(self):
        q = self._search_var.get().strip().lower()
        if q in ("", "buscar chamado..."):
            self._render_list(self._tickets)
        else:
            self._render_list([
                t for t in self._tickets
                if q in t["assunto"].lower() or q in t["numero"].lower()
            ])

    def _render_list(self, tickets):
        for w in self._list_inner.winfo_children():
            w.destroy()
        if not tickets:
            tk.Label(self._list_inner,
                     text="Nenhum chamado encontrado.",
                     font=self._fS, bg=_C["sb_bg"], fg=_C["sb_muted"],
                     pady=28).pack()
            return
        for t in tickets:
            self._render_card(t)
        if not self._tickets or len(tickets) == len(self._tickets):
            self._tickets = tickets

    def _render_card(self, t):
        is_sel        = self._selected and self._selected["id"] == t["id"]
        bg            = _C["sb_active"] if is_sel else _C["sb_bg"]
        pill, fg_b, stripe = _st(t["status"])

        card = tk.Frame(self._list_inner, bg=bg, cursor="hand2")
        card.pack(fill=tk.X)
        tk.Frame(self._list_inner, bg="#1a2744", height=1).pack(fill=tk.X)

        tk.Frame(card, bg=stripe, width=2).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(card, bg=bg, padx=12, pady=10)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(body, text=t["numero"], font=self._fS,
                 bg=bg, fg=_C["sb_num"], anchor="w").pack(fill=tk.X)
        subj = t["assunto"][:46] + ("…" if len(t["assunto"]) > 46 else "")
        tk.Label(body, text=subj, font=self._fN,
                 bg=bg, fg=_C["sb_text"] if is_sel else "#cbd5e1",
                 anchor="w", wraplength=216).pack(fill=tk.X, pady=(2, 6))

        meta = tk.Frame(body, bg=bg)
        meta.pack(fill=tk.X)
        tk.Label(meta, text=t["status"], font=self._fS,
                 bg=pill, fg=fg_b, padx=6, pady=2).pack(side=tk.LEFT)
        tk.Label(meta, text=t["criado_em"], font=self._fS,
                 bg=bg, fg=_C["sb_num"]).pack(side=tk.RIGHT)

        all_w = ([card, body, meta]
                 + list(body.winfo_children())
                 + list(meta.winfo_children()))

        def click(_e, tk_=t): self._select(tk_)
        def enter(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in all_w:
                    try: w.config(bg=_C["sb_hover"])
                    except Exception: pass
        def leave(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in all_w:
                    try: w.config(bg=_C["sb_bg"])
                    except Exception: pass

        for w in all_w:
            w.bind("<Button-1>", click)
            w.bind("<Enter>",    enter)
            w.bind("<Leave>",    leave)

    def _select(self, ticket):
        self._selected = ticket
        self._empty.pack_forget()
        self._tk_frame.pack(fill=tk.BOTH, expand=True)
        self._lbl_num.config(text=ticket["numero"])
        self._lbl_sub.config(text=ticket["assunto"])
        pill, fg_b, _ = _st(ticket["status"])
        self._lbl_badge.config(text=ticket["status"], bg=pill, fg=fg_b)
        q = self._search_var.get().strip().lower()
        visible = self._tickets if q in ("", "buscar chamado...") else [
            t for t in self._tickets
            if q in t["assunto"].lower() or q in t["numero"].lower()
        ]
        self._render_list(visible)
        self._load_detail(ticket)

    def _render_chat(self, historico):
        self._historico = historico
        for w in self._chat_inner.winfo_children():
            w.destroy()
        if not historico:
            tk.Label(self._chat_inner,
                     text="Nenhuma mensagem ainda.",
                     font=self._fS, bg=_C["chat_bg"], fg=_C["hint"],
                     pady=32).pack()
        else:
            for msg in historico:
                self._render_bubble(msg)
        self._chat_cv.update_idletasks()
        self._chat_cv.yview_moveto(0)

    def _render_bubble(self, msg):
        is_staff = msg.get("is_staff", False)
        cv_w     = self._chat_cv.winfo_width()
        wrap     = max(cv_w - 140, 220)

        outer = tk.Frame(self._chat_inner, bg=_C["chat_bg"])
        outer.pack(fill=tk.X, padx=18, pady=5)

        meta = tk.Frame(outer, bg=_C["chat_bg"])
        meta.pack(fill=tk.X)
        if is_staff:
            tk.Label(meta, text=msg["criado_em"], font=self._fS,
                     bg=_C["chat_bg"], fg=_C["hint"]).pack(side=tk.LEFT, padx=2)
            tk.Label(meta, text=msg["autor"], font=self._fS,
                     bg=_C["chat_bg"], fg=_C["muted"]).pack(side=tk.RIGHT)
        else:
            tk.Label(meta, text=msg["autor"], font=self._fS,
                     bg=_C["chat_bg"], fg=_C["muted"]).pack(side=tk.LEFT)
            tk.Label(meta, text=msg["criado_em"], font=self._fS,
                     bg=_C["chat_bg"], fg=_C["hint"]).pack(side=tk.RIGHT, padx=2)

        if is_staff:
            bubble = tk.Label(
                outer, text=msg["conteudo"], font=self._fM,
                bg=_C["staff_bg"], fg=_C["staff_fg"],
                wraplength=wrap, justify=tk.LEFT, anchor="w",
                padx=13, pady=9,
            )
        else:
            bubble = tk.Label(
                outer, text=msg["conteudo"], font=self._fM,
                bg=_C["user_bg"], fg=_C["user_fg"],
                wraplength=wrap, justify=tk.LEFT, anchor="w",
                padx=13, pady=9,
                highlightthickness=1,
                highlightbackground=_C["user_bd"],
            )
        bubble.pack(anchor="e" if is_staff else "w", pady=(2, 0))

    def _prepend_msg(self, msg):
        self._historico.insert(0, msg)
        for w in self._chat_inner.winfo_children():
            w.destroy()
        for m in self._historico:
            self._render_bubble(m)
        self._chat_cv.update_idletasks()
        self._chat_cv.yview_moveto(0)

    def _novo_ticket(self):
        _NovoTicketModal(
            parent_win=self._win,
            api=self._api,
            on_success=self._on_ticket_criado,
        )

    def _on_ticket_criado(self, data):
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
    Gerenciador singleton da janela de chamados.

    Uso:
        from chamados import ChamadosManager

        ChamadosManager.open(
            server_url=os.environ.get("AGENT_SERVER_URL", ""),
            token_hash=os.environ.get("AGENT_TOKEN_HASH", ""),
        )
    """

    _instance: Optional[_ChamadosWindow] = None
    _lock = threading.Lock()

    @classmethod
    def open(cls, server_url: str, token_hash: str) -> None:
        with cls._lock:
            if cls._instance and cls._instance.alive:
                cls._instance.lift()
                return
            cls._instance = _ChamadosWindow(server_url, token_hash)


# ─────────────────────────────────────────────────────────────────────────────
# __main__ — smoke-test (sem servidor real)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("chamados.py — smoke test")

    _MOCK = {
        "tickets": [
            {"id":1,"numero":"#2025-000042","assunto":"Lentidão ao abrir relatórios",
             "status":"Em andamento","status_cor":"#f59e0b","servico":"Suporte técnico","criado_em":"10/03 09:14"},
            {"id":2,"numero":"#2025-000038","assunto":"Impressora do andar 3 não aparece",
             "status":"Aberto","status_cor":"#3b82f6","servico":"Hardware","criado_em":"08/03 14:30"},
            {"id":3,"numero":"#2025-000031","assunto":"Acesso ao módulo de estoque ERP",
             "status":"Resolvido","status_cor":"#10b981","servico":"Acesso","criado_em":"01/03 08:55"},
            {"id":4,"numero":"#2025-000027","assunto":"Monitor com linhas verticais",
             "status":"Fechado","status_cor":"#6b7280","servico":"Hardware","criado_em":"22/02 11:20"},
        ],
        "historico":{
            1:[
                {"id":3,"autor":"Suporte Técnico","is_staff":True,
                 "conteudo":"Reindexação em andamento. Estimamos solução em 2h.","criado_em":"10/03 10:05"},
                {"id":2,"autor":"Suporte Técnico","is_staff":True,
                 "conteudo":"Reproduzimos o problema — índice desatualizado no banco.","criado_em":"10/03 10:02"},
                {"id":1,"autor":"Você","is_staff":False,
                 "conteudo":"Sistema lento ao abrir relatórios desde ontem. Demora +3 min.","criado_em":"10/03 09:14"},
            ],
            2:[{"id":4,"autor":"Você","is_staff":False,
                "conteudo":"Impressora sumiu da lista após atualização do Windows.","criado_em":"08/03 14:30"}],
            3:[
                {"id":6,"autor":"Você","is_staff":False,"conteudo":"Perfeito, obrigado!","criado_em":"01/03 09:55"},
                {"id":5,"autor":"Suporte Técnico","is_staff":True,
                 "conteudo":"Acesso criado. Perfil de visualização liberado.","criado_em":"01/03 09:40"},
                {"id":4,"autor":"Você","is_staff":False,
                 "conteudo":"Preciso de acesso ao módulo de estoque para João Silva, matrícula 4872.","criado_em":"01/03 08:55"},
            ],
            4:[
                {"id":8,"autor":"Suporte Técnico","is_staff":True,
                 "conteudo":"Troca do cabo DisplayPort resolveu. Chamado encerrado.","criado_em":"22/02 13:00"},
                {"id":7,"autor":"Você","is_staff":False,
                 "conteudo":"Monitor com linhas verticais desde esta manhã.","criado_em":"22/02 11:20"},
            ],
        },
    }

    def _mock_get(self, path, **params):
        if "list" in path:
            return {"ok":True,"tickets":_MOCK["tickets"]}
        for tid,hist in _MOCK["historico"].items():
            if f"/{tid}/" in path:
                t=next(x for x in _MOCK["tickets"] if x["id"]==tid)
                return {"ok":True,"ticket":t,"historico":hist}
        return {"ok":True,"tickets":[]}

    def _mock_post(self, path, body):
        if "criar" in path:
            nid=max(x["id"] for x in _MOCK["tickets"])+1
            t={"id":nid,"numero":f"#2025-{1000+nid:06d}","assunto":body["assunto"],
               "status":"Aberto","status_cor":"#3b82f6","servico":body.get("tipo_chamado",""),"criado_em":"agora"}
            _MOCK["tickets"].insert(0,t)
            _MOCK["historico"][nid]=[{"id":99,"autor":"Você","is_staff":False,"conteudo":body["descricao"],"criado_em":"agora"}]
            return {"ok":True,"numero":t["numero"],"id":nid}
        if "reply" in path:
            tid=int(path.split("/")[-3])
            msg={"id":100,"autor":"Você","is_staff":False,"conteudo":body["conteudo"],"criado_em":"agora"}
            _MOCK["historico"].setdefault(tid,[]).insert(0,msg)
            return {"ok":True,"acao":msg}
        return {"ok":True}

    _ApiClient.get  = _mock_get
    _ApiClient.post = _mock_post

    ChamadosManager.open(server_url="http://mock", token_hash="mock")
    print("Janela aberta. Feche-a para encerrar.")