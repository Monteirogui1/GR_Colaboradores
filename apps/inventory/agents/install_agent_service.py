"""
install_agent.py — Instalador v3.4 | Layout Moderno
  • Instala agent_service.exe como Serviço Windows (NSSM, Session 0)
  • Instala agent_tray.exe como autorun de TODOS os usuários (HKLM Run)
  • Cria atalho "Chamados.lnk" no Desktop Público (todos os usuários)
"""

import os
import sys
import time
import shutil
import hashlib
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, font as tkfont
from pathlib import Path
import math
import ctypes
import ctypes.wintypes
import winreg

# ─────────────────────────────────────────────
# Configurações
# ─────────────────────────────────────────────
try:
    from installer_config import *
except ImportError:
    SERVER_URL          = "http://192.168.100.247:5002"
    INSTALL_DIR         = r"C:\Program Files\InventoryAgent"
    AGENT_NAME          = "Inventory Agent"
    AGENT_VERSION       = "3.3.1"
    DEFAULT_AUTO_UPDATE = True
    DEFAULT_NOTIFS      = True
    IPC_PORT            = 7070

SERVICE_NAME = "InventoryAgent"

# ── HKLM → executa para TODOS os usuários ao logar ──────────────────────────
# HKCU só registraria para o usuário atual (e com UAC, para o admin, não o AD)
TRAY_REG_ROOT = winreg.HKEY_LOCAL_MACHINE
TRAY_REG_KEY  = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
TRAY_REG_VAL  = "InventoryAgentTray"

# ─────────────────────────────────────────────
# Paleta
# ─────────────────────────────────────────────
C = {
    "bg":        "#0d1117",
    "panel":     "#161b22",
    "surface":   "#21262d",
    "border":    "#30363d",
    "accent":    "#58a6ff",
    "accent2":   "#1f6feb",
    "success":   "#3fb950",
    "warn":      "#d29922",
    "error":     "#f85149",
    "muted":     "#8b949e",
    "text":      "#e6edf3",
    "text_dim":  "#c9d1d9",
    "white":     "#ffffff",
    "step_done": "#238636",
    "step_act":  "#1f6feb",
    "step_idle": "#21262d",
}

STEPS = [
    ("01", "Bem‑vindo",     "Visão geral da instalação"),
    ("02", "Configuração",  "Diretório, token e opções"),
    ("03", "Instalando",    "Progresso em tempo real"),
    ("04", "Concluído",     "Instalação finalizada"),
]


# ═══════════════════════════════════════════════════════════════
# Helpers de registro e atalho
# ═══════════════════════════════════════════════════════════════

def register_tray_autorun_all_users(tray_exe: Path) -> bool:
    """
    Registra agent_tray.exe em HKLM\\...\\Run.
    Isso faz o tray iniciar para TODOS os usuários que logarem,
    incluindo usuários de domínio AD que nunca logaram antes.

    Requer que o processo esteja elevado (admin) — o instalador
    já pede UAC, então isso sempre funciona.

    Fallback: reg.exe (caso winreg falhe por alguma razão).
    """
    value = str(tray_exe)

    # Método 1: winreg direto em HKLM (privilegiado, simples)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            TRAY_REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, TRAY_REG_VAL, 0, winreg.REG_SZ, value)
        return True
    except Exception as e:
        pass  # tenta fallback

    # Método 2: reg.exe (fallback)
    try:
        r = subprocess.run(
            ["reg", "add",
             rf"HKLM\{TRAY_REG_KEY}",
             "/v", TRAY_REG_VAL,
             "/t", "REG_SZ",
             "/d", value,
             "/f"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass

    return False


def get_public_desktop() -> Path:
    """
    Retorna C:\\Users\\Public\\Desktop — área de trabalho compartilhada
    por todos os usuários. Atalhos aqui aparecem para todos.
    """
    # Tenta via variável de ambiente PUBLIC
    public = os.environ.get("PUBLIC", r"C:\Users\Public")
    desktop = Path(public) / "Desktop"
    if desktop.exists():
        return desktop

    # Fallback via CSIDL_COMMON_DESKTOPDIRECTORY (0x0019)
    try:
        CSIDL_COMMON_DESKTOP = 0x0019
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(
            None, CSIDL_COMMON_DESKTOP, None, 0, buf)
        path = Path(buf.value)
        if path.exists():
            return path
    except Exception:
        pass

    return Path(r"C:\Users\Public\Desktop")


def create_shortcut_all_users(tray_exe: Path) -> bool:
    """
    Cria Chamados.lnk no Desktop Público (C:\\Users\\Public\\Desktop).
    Fica visível para todos os usuários da máquina.
    Usa win32com com fallback PowerShell.
    """
    desktop       = get_public_desktop()
    shortcut_path = desktop / "Chamados.lnk"

    # Método 1: win32com / pythoncom
    try:
        import pythoncom
        from win32com.shell import shell as w32shell

        pythoncom.CoInitialize()
        lnk = pythoncom.CoCreateInstance(
            w32shell.CLSID_ShellLink, None,
            pythoncom.CLSCTX_INPROC_SERVER,
            w32shell.IID_IShellLink,
        )
        lnk.SetPath(str(tray_exe))
        lnk.SetArguments("--chamados")
        lnk.SetDescription("Abrir painel de Chamados")
        lnk.SetWorkingDirectory(str(tray_exe.parent))
        lnk.SetIconLocation(str(tray_exe), 0)
        lnk.QueryInterface(pythoncom.IID_IPersistFile).Save(str(shortcut_path), 0)
        pythoncom.CoUninitialize()
        return True

    except ImportError:
        pass  # pywin32 não disponível
    except Exception:
        pass

    # Método 2: PowerShell WScript.Shell
    try:
        sp = str(shortcut_path).replace("'", "''")
        tp = str(tray_exe).replace("'", "''")
        wd = str(tray_exe.parent).replace("'", "''")
        ps = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{sp}'); "
            f"$s.TargetPath = '{tp}'; "
            f"$s.Arguments = '--chamados'; "
            f"$s.Description = 'Abrir painel de Chamados'; "
            f"$s.WorkingDirectory = '{wd}'; "
            f"$s.IconLocation = '{tp},0'; "
            f"$s.Save()"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# Widget: Canvas Animado
# ═══════════════════════════════════════════════════════════════
class AnimatedBg(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C["bg"], highlightthickness=0, **kw)
        self._dots = []
        self._after_id = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, _e=None):
        self._dots = []
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        import random
        for _ in range(22):
            self._dots.append({
                "x": random.uniform(0, w), "y": random.uniform(0, h),
                "r": random.uniform(1, 2.5),
                "vx": random.uniform(-0.18, 0.18), "vy": random.uniform(-0.18, 0.18),
                "alpha": random.uniform(0.3, 0.9),
            })
        if self._after_id:
            self.after_cancel(self._after_id)
        self._tick()

    def _tick(self):
        self.delete("dot")
        w, h = self.winfo_width(), self.winfo_height()
        for d in self._dots:
            d["x"] = (d["x"] + d["vx"]) % w
            d["y"] = (d["y"] + d["vy"]) % h
            a = int(d["alpha"] * 80)
            col = f"#{a:02x}{a+20:02x}{min(a+60,255):02x}"
            r = d["r"]
            self.create_oval(d["x"]-r, d["y"]-r, d["x"]+r, d["y"]+r,
                             fill=col, outline="", tags="dot")
        self._after_id = self.after(60, self._tick)

    def stop(self):
        if self._after_id:
            self.after_cancel(self._after_id)


# ═══════════════════════════════════════════════════════════════
# Widget: StepBar vertical
# ═══════════════════════════════════════════════════════════════
class StepBar(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self._labels = []
        self._circles = []
        self._build()

    def _build(self):
        logo_f = tk.Frame(self, bg=C["bg"])
        logo_f.pack(fill=tk.X, padx=24, pady=(32, 40))
        logo_c = tk.Canvas(logo_f, width=36, height=36, bg=C["bg"], highlightthickness=0)
        logo_c.pack(side=tk.LEFT)
        cx, cy, r = 18, 18, 16
        pts = []
        for i in range(6):
            ang = math.radians(60*i - 30)
            pts += [cx + r*math.cos(ang), cy + r*math.sin(ang)]
        logo_c.create_polygon(pts, fill=C["accent2"], outline=C["accent"], width=1.5)
        logo_c.create_text(cx, cy, text="IA", fill=C["white"], font=("Consolas", 10, "bold"))
        tk.Label(logo_f, text=AGENT_NAME, font=("Segoe UI", 11, "bold"),
                 bg=C["bg"], fg=C["white"]).pack(side=tk.LEFT, padx=10)

        steps_f = tk.Frame(self, bg=C["bg"])
        steps_f.pack(fill=tk.X, padx=16)
        for i, (num, title, sub) in enumerate(STEPS):
            row = tk.Frame(steps_f, bg=C["bg"])
            row.pack(fill=tk.X, pady=2)
            left = tk.Frame(row, bg=C["bg"], width=40)
            left.pack(side=tk.LEFT, fill=tk.Y)
            left.pack_propagate(False)
            c = tk.Canvas(left, width=32, height=32, bg=C["bg"], highlightthickness=0)
            c.pack(pady=(4, 0))
            self._circles.append((c, num))
            if i < len(STEPS) - 1:
                tk.Frame(left, bg=C["border"], width=1, height=28).pack()
            txt_f = tk.Frame(row, bg=C["bg"])
            txt_f.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
            lbl_title = tk.Label(txt_f, text=title, font=("Segoe UI", 10, "bold"),
                                 bg=C["bg"], fg=C["muted"], anchor="w")
            lbl_title.pack(fill=tk.X)
            lbl_sub = tk.Label(txt_f, text=sub, font=("Segoe UI", 8),
                               bg=C["bg"], fg=C["border"], anchor="w")
            lbl_sub.pack(fill=tk.X, pady=(0, 6))
            self._labels.append((lbl_title, lbl_sub))

        tk.Frame(self, bg=C["border"], height=1).pack(fill=tk.X, side=tk.BOTTOM, padx=16, pady=(0, 12))
        tk.Label(self, text=f"v{AGENT_VERSION}", font=("Consolas", 8),
                 bg=C["bg"], fg=C["border"]).pack(side=tk.BOTTOM, pady=(0, 8))
        self.set_step(0)

    def _draw_circle(self, canvas, num, state):
        canvas.delete("all")
        if state == "done":
            canvas.create_oval(2, 2, 30, 30, fill=C["step_done"], outline="")
            canvas.create_text(16, 16, text="✓", fill=C["white"], font=("Segoe UI", 11, "bold"))
        elif state == "active":
            canvas.create_oval(2, 2, 30, 30, fill=C["step_act"], outline=C["accent"], width=2)
            canvas.create_text(16, 16, text=num, fill=C["white"], font=("Consolas", 9, "bold"))
        else:
            canvas.create_oval(2, 2, 30, 30, fill=C["step_idle"], outline=C["border"], width=1)
            canvas.create_text(16, 16, text=num, fill=C["muted"], font=("Consolas", 9))

    def set_step(self, idx):
        for i, (canvas, num) in enumerate(self._circles):
            state = "done" if i < idx else ("active" if i == idx else "idle")
            self._draw_circle(canvas, num, state)
            t_lbl, s_lbl = self._labels[i]
            if i < idx:
                t_lbl.config(fg=C["success"]); s_lbl.config(fg=C["step_done"])
            elif i == idx:
                t_lbl.config(fg=C["white"]); s_lbl.config(fg=C["muted"])
            else:
                t_lbl.config(fg=C["muted"]); s_lbl.config(fg=C["border"])


# ═══════════════════════════════════════════════════════════════
# Helpers de UI
# ═══════════════════════════════════════════════════════════════
def _section(parent, title):
    f = tk.Frame(parent, bg=C["panel"])
    f.pack(fill=tk.X, pady=(0, 16))
    tk.Label(f, text=title.upper(), font=("Consolas", 8, "bold"),
             bg=C["panel"], fg=C["accent"]).pack(anchor="w", padx=16, pady=(12, 4))
    tk.Frame(f, bg=C["border"], height=1).pack(fill=tk.X, padx=16, pady=(0, 12))
    body = tk.Frame(f, bg=C["panel"])
    body.pack(fill=tk.X, padx=16, pady=(0, 12))
    return body

def _entry(parent, var, show=None, width=None):
    e = tk.Entry(parent, textvariable=var,
                 bg=C["surface"], fg=C["text"], insertbackground=C["accent"],
                 relief=tk.FLAT, bd=0, font=("Consolas", 10),
                 highlightthickness=1, highlightbackground=C["border"],
                 highlightcolor=C["accent"])
    if show:   e.config(show=show)
    if width:  e.config(width=width)
    return e

def _label(parent, text, size=9, fg=None, bold=False):
    return tk.Label(parent, text=text,
                    font=("Segoe UI", size, "bold") if bold else ("Segoe UI", size),
                    bg=C["panel"], fg=fg or C["muted"])

def _check(parent, text, var):
    return tk.Checkbutton(parent, text=text, variable=var,
                          bg=C["panel"], fg=C["text_dim"],
                          selectcolor=C["surface"],
                          activebackground=C["panel"], activeforeground=C["white"],
                          font=("Segoe UI", 9), cursor="hand2")


# ═══════════════════════════════════════════════════════════════
# Instalador Principal
# ═══════════════════════════════════════════════════════════════
class AgentInstaller:
    def __init__(self, root: tk.Tk):
        self.root             = root
        self.root.title(f"{AGENT_NAME} — Instalador")
        self.root.geometry("900x750")
        self.root.resizable(False, False)
        self.root.configure(bg=C["bg"])

        self.install_dir      = tk.StringVar(value=INSTALL_DIR)
        self.token            = tk.StringVar()
        self.show_token       = tk.BooleanVar(value=False)
        self.auto_update      = tk.BooleanVar(value=DEFAULT_AUTO_UPDATE)
        self.notifs           = tk.BooleanVar(value=DEFAULT_NOTIFS)
        self.install_tray     = tk.BooleanVar(value=True)
        self.desktop_shortcut = tk.BooleanVar(value=True)
        self._cur_step        = 0
        self._pb_value        = 0

        self._build()
        self._require_admin()

    # ── Layout ────────────────────────────────────────────────
    def _build(self):
        left = tk.Frame(self.root, bg=C["bg"], width=220)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)
        self._bg_anim = AnimatedBg(left)
        self._bg_anim.place(x=0, y=0, relwidth=1, relheight=1)
        self._stepbar = StepBar(left)
        self._stepbar.place(x=0, y=0, relwidth=1, relheight=1)

        tk.Frame(self.root, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        right = tk.Frame(self.root, bg=C["panel"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._hdr_f = tk.Frame(right, bg=C["panel"])
        self._hdr_f.pack(fill=tk.X)
        self._hdr_title = tk.Label(self._hdr_f, text="",
                                   font=("Segoe UI", 16, "bold"),
                                   bg=C["panel"], fg=C["white"],
                                   anchor="w", pady=24, padx=28)
        self._hdr_title.pack(side=tk.LEFT)
        self._hdr_sub = tk.Label(self._hdr_f, text="",
                                 font=("Segoe UI", 9),
                                 bg=C["panel"], fg=C["muted"],
                                 anchor="e", padx=28)
        self._hdr_sub.pack(side=tk.RIGHT)
        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X)

        self._content = tk.Frame(right, bg=C["panel"])
        self._content.pack(fill=tk.BOTH, expand=True)

        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X, side=tk.BOTTOM)
        btn_row = tk.Frame(right, bg=C["bg"], pady=14, padx=24)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)

        self._btn_back = self._mk_btn(btn_row, "← Voltar", self._prev,
                                      bg=C["surface"], fg=C["muted"], state=tk.DISABLED)
        self._btn_back.pack(side=tk.LEFT)
        self._btn_cancel = self._mk_btn(btn_row, "Cancelar", self._cancel,
                                        bg=C["surface"], fg=C["muted"])
        self._btn_cancel.pack(side=tk.RIGHT, padx=(8, 0))
        self._btn_next = self._mk_btn(btn_row, "Avançar  →", self._next,
                                      bg=C["accent2"], fg=C["white"], bold=True)
        self._btn_next.pack(side=tk.RIGHT)

        self._pages = [
            self._page_welcome(self._content),
            self._page_config(self._content),
            self._page_install(self._content),
            self._page_done(self._content),
        ]
        self._show_page(0)

    def _mk_btn(self, parent, text, cmd, bg=C["surface"], fg=C["text"],
                bold=False, state=tk.NORMAL):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      relief=tk.FLAT,
                      font=("Segoe UI", 10, "bold") if bold else ("Segoe UI", 10),
                      padx=20, pady=8, cursor="hand2", state=state,
                      activebackground=C["accent2"], activeforeground=C["white"])
        b.bind("<Enter>", lambda _: b.config(bg=C["accent2"], fg=C["white"])
               if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda _: b.config(bg=bg, fg=fg)
               if str(b["state"]) != "disabled" else None)
        return b

    # ── Páginas ───────────────────────────────────────────────
    def _page_welcome(self, parent):
        f = tk.Frame(parent, bg=C["panel"])
        scroll_f = tk.Frame(f, bg=C["panel"])
        scroll_f.pack(fill=tk.BOTH, expand=True, padx=28, pady=20)

        arch = tk.Frame(scroll_f, bg=C["surface"],
                        highlightthickness=1, highlightbackground=C["border"])
        arch.pack(fill=tk.X, pady=(0, 16))
        tk.Label(arch, text="ARQUITETURA DO SISTEMA",
                 font=("Consolas", 8, "bold"), bg=C["surface"],
                 fg=C["accent"]).pack(anchor="w", padx=16, pady=(12, 6))
        tk.Frame(arch, bg=C["border"], height=1).pack(fill=tk.X, padx=16)
        diagram = tk.Frame(arch, bg=C["surface"])
        diagram.pack(fill=tk.X, padx=16, pady=12)

        def arch_block(p, title, items, col):
            blk = tk.Frame(p, bg=C["panel"],
                           highlightthickness=1, highlightbackground=col)
            blk.pack(fill=tk.X, pady=4)
            hdr = tk.Frame(blk, bg=col)
            hdr.pack(fill=tk.X)
            tk.Label(hdr, text=title, font=("Segoe UI", 9, "bold"),
                     bg=col, fg=C["white"], pady=6, padx=12, anchor="w").pack(fill=tk.X)
            for item in items:
                tk.Label(blk, text=f"  {item}", font=("Consolas", 8),
                         bg=C["panel"], fg=C["muted"],
                         anchor="w", pady=2).pack(fill=tk.X, padx=8)
            tk.Frame(blk, height=6, bg=C["panel"]).pack()

        arch_block(diagram, "⚙  Serviço Windows  (Session 0 — sem desktop)",
                   ["• Coleta hardware via PowerShell",
                    "• Envia dados ao servidor Django",
                    f"• IPC local  127.0.0.1:{IPC_PORT}"], "#1a3a5c")
        tk.Label(diagram, text="↕  HTTP local (IPC)",
                 font=("Consolas", 8), bg=C["surface"], fg=C["muted"]).pack()
        arch_block(diagram, "🔔  Tray App  (Todos os usuários — HKLM Run)",
                   ["• Inicia automaticamente para qualquer usuário AD",
                    "• Ícone na bandeja do sistema",
                    "• Notificações e painel de chamados"], "#1a3a2e")

        cards_f = tk.Frame(scroll_f, bg=C["panel"])
        cards_f.pack(fill=tk.X, pady=(16, 0))
        cards_f.columnconfigure(0, weight=1)
        cards_f.columnconfigure(1, weight=1)

        def info_card(col, icon, title, body):
            c = tk.Frame(cards_f, bg=C["surface"],
                         highlightthickness=1, highlightbackground=C["border"])
            c.grid(row=0, column=col, sticky="nsew", padx=(0, 8 if col == 0 else 0))
            tk.Label(c, text=f"{icon}  {title}", font=("Segoe UI", 9, "bold"),
                     bg=C["surface"], fg=C["text"],
                     anchor="w", pady=10, padx=14).pack(fill=tk.X)
            tk.Frame(c, bg=C["border"], height=1).pack(fill=tk.X, padx=14)
            tk.Label(c, text=body, font=("Segoe UI", 8),
                     bg=C["surface"], fg=C["muted"],
                     justify=tk.LEFT, anchor="w",
                     padx=14, pady=10, wraplength=220).pack(fill=tk.X)

        info_card(0, "👥", "Todos os usuários",
                  "Tray App registrado em HKLM\\Run.\nInicia para qualquer usuário AD\nque logar nesta máquina.")
        info_card(1, "🔒", "Segurança",
                  "Token nunca salvo em disco.\nIPC restrito ao loopback.\nComandos remotos com timeout.")
        return f

    def _page_config(self, parent):
        f = tk.Frame(parent, bg=C["panel"])
        wrap = tk.Frame(f, bg=C["panel"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=28, pady=20)

        body = _section(wrap, "Diretório de instalação")
        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill=tk.X)
        _entry(row, self.install_dir).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7)
        tk.Button(row, text="…", command=self._browse,
                  bg=C["surface"], fg=C["muted"], relief=tk.FLAT,
                  font=("Segoe UI", 10), padx=12, pady=6,
                  cursor="hand2").pack(side=tk.LEFT, padx=(8, 0))

        body2 = _section(wrap, "Autenticação")
        _label(body2, "Token de instalação (8 caracteres)").pack(anchor="w", pady=(0, 4))
        tok_row = tk.Frame(body2, bg=C["panel"])
        tok_row.pack(fill=tk.X)
        self._tok_entry = _entry(tok_row, self.token, show="●")
        self._tok_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7)
        self._eye_btn = tk.Button(tok_row, text="👁", command=self._toggle_token,
                                  bg=C["surface"], fg=C["muted"], relief=tk.FLAT,
                                  font=("Segoe UI", 10), padx=10, pady=6, cursor="hand2")
        self._eye_btn.pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(body2, text="🔒  Não salvo em disco — armazenado apenas em memória do serviço",
                 font=("Segoe UI", 8), bg=C["panel"], fg=C["success"]).pack(anchor="w", pady=(6, 0))

        body3 = _section(wrap, "Opções")
        _check(body3, "Atualizações automáticas do agente", self.auto_update).pack(anchor="w", pady=2)
        _check(body3, "Notificações nativas (requer Tray App)", self.notifs).pack(anchor="w", pady=2)
        _check(body3, "Instalar Tray App (todos os usuários — HKLM Run)", self.install_tray).pack(anchor="w", pady=2)
        _check(body3, "Criar atalho 'Chamados' no Desktop Público", self.desktop_shortcut).pack(anchor="w", pady=2)

        srv_f = tk.Frame(wrap, bg=C["surface"],
                         highlightthickness=1, highlightbackground=C["border"])
        srv_f.pack(fill=tk.X, pady=(4, 0))
        tk.Label(srv_f, text=f"Servidor:  {SERVER_URL}",
                 font=("Consolas", 9), bg=C["surface"], fg=C["muted"],
                 anchor="w", padx=14, pady=10).pack(fill=tk.X)
        return f

    def _page_install(self, parent):
        f = tk.Frame(parent, bg=C["panel"])
        wrap = tk.Frame(f, bg=C["panel"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=28, pady=20)

        status_f = tk.Frame(wrap, bg=C["surface"],
                             highlightthickness=1, highlightbackground=C["border"])
        status_f.pack(fill=tk.X, pady=(0, 16))
        self._status_icon = tk.Label(status_f, text="⏳",
                                     font=("Segoe UI", 20),
                                     bg=C["surface"], fg=C["accent"])
        self._status_icon.pack(side=tk.LEFT, padx=(16, 0), pady=12)
        status_txt = tk.Frame(status_f, bg=C["surface"])
        status_txt.pack(side=tk.LEFT, padx=14, pady=12, fill=tk.X, expand=True)
        self._status_title = tk.Label(status_txt, text="Preparando…",
                                      font=("Segoe UI", 11, "bold"),
                                      bg=C["surface"], fg=C["text"], anchor="w")
        self._status_title.pack(fill=tk.X)
        self._status_sub = tk.Label(status_txt, text="",
                                    font=("Segoe UI", 9),
                                    bg=C["surface"], fg=C["muted"], anchor="w")
        self._status_sub.pack(fill=tk.X)

        pb_wrap = tk.Frame(wrap, bg=C["surface"],
                           highlightthickness=1, highlightbackground=C["border"])
        pb_wrap.pack(fill=tk.X, pady=(0, 16))
        pb_inner = tk.Frame(pb_wrap, bg=C["surface"])
        pb_inner.pack(fill=tk.X, padx=16, pady=12)
        tk.Label(pb_inner, text="PROGRESSO", font=("Consolas", 8, "bold"),
                 bg=C["surface"], fg=C["accent"]).pack(anchor="w", pady=(0, 6))
        self._pb_track = tk.Frame(pb_inner, bg=C["border"], height=6)
        self._pb_track.pack(fill=tk.X)
        self._pb_fill = tk.Frame(self._pb_track, bg=C["accent2"], height=6, width=0)
        self._pb_fill.place(x=0, y=0, height=6)
        self._pb_pct = tk.Label(pb_inner, text="0%",
                                font=("Consolas", 8), bg=C["surface"], fg=C["muted"])
        self._pb_pct.pack(anchor="e", pady=(4, 0))

        log_lbl = tk.Frame(wrap, bg=C["panel"])
        log_lbl.pack(fill=tk.X)
        tk.Label(log_lbl, text="LOG DE INSTALAÇÃO", font=("Consolas", 8, "bold"),
                 bg=C["panel"], fg=C["accent"]).pack(anchor="w", pady=(0, 6))
        log_outer = tk.Frame(wrap, bg=C["bg"],
                             highlightthickness=1, highlightbackground=C["border"])
        log_outer.pack(fill=tk.BOTH, expand=True)
        self.log_widget = scrolledtext.ScrolledText(
            log_outer, font=("Consolas", 8),
            bg=C["bg"], fg=C["text_dim"],
            insertbackground=C["accent"],
            relief=tk.FLAT, bd=0, padx=12, pady=8)
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        self.log_widget.tag_config("OK",   foreground=C["success"])
        self.log_widget.tag_config("WARN", foreground=C["warn"])
        self.log_widget.tag_config("ERR",  foreground=C["error"])
        self.log_widget.tag_config("INFO", foreground=C["muted"])
        self.log_widget.tag_config("TS",   foreground=C["border"])
        return f

    def _page_done(self, parent):
        f = tk.Frame(parent, bg=C["panel"])
        wrap = tk.Frame(f, bg=C["panel"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=28, pady=40)
        icon_c = tk.Canvas(wrap, width=72, height=72,
                           bg=C["panel"], highlightthickness=0)
        icon_c.pack()
        icon_c.create_oval(4, 4, 68, 68, fill=C["step_done"], outline="")
        icon_c.create_text(36, 36, text="✓", fill=C["white"],
                           font=("Segoe UI", 28, "bold"))
        self._done_title = tk.Label(wrap, text="Instalação Concluída!",
                                    font=("Segoe UI", 15, "bold"),
                                    bg=C["panel"], fg=C["white"])
        self._done_title.pack(pady=(16, 4))
        self._done_sub = tk.Label(wrap, text="",
                                  font=("Segoe UI", 9),
                                  bg=C["panel"], fg=C["muted"],
                                  justify=tk.CENTER)
        self._done_sub.pack()
        self._done_cards = tk.Frame(wrap, bg=C["panel"])
        self._done_cards.pack(fill=tk.X, pady=(24, 0))
        return f

    # ── Navegação ─────────────────────────────────────────────
    def _show_page(self, idx):
        for p in self._pages:
            p.pack_forget()
        self._pages[idx].pack(fill=tk.BOTH, expand=True)
        self._stepbar.set_step(idx)
        titles = [
            ("Bem‑vindo ao Instalador",  f"{AGENT_NAME} v{AGENT_VERSION}"),
            ("Configuração",             "Defina as opções de instalação"),
            ("Instalando…",              "Aguarde, isso levará alguns segundos"),
            ("Tudo pronto!",             "O agente está em operação"),
        ]
        t, s = titles[idx]
        self._hdr_title.config(text=t)
        self._hdr_sub.config(text=s)
        self._cur_step = idx

    def _next(self):
        if self._cur_step == 0:
            self._show_page(1)
            self._btn_back.config(state=tk.NORMAL)
        elif self._cur_step == 1:
            if self._validate():
                self._show_page(2)
                self._btn_back.config(state=tk.DISABLED)
                self._btn_next.config(state=tk.DISABLED)
                self._btn_cancel.config(state=tk.DISABLED)
                threading.Thread(target=self._install, daemon=True).start()
        elif self._cur_step == 3:
            self.root.quit()

    def _prev(self):
        if self._cur_step > 0:
            self._show_page(self._cur_step - 1)
        if self._cur_step == 0:
            self._btn_back.config(state=tk.DISABLED)

    def _cancel(self):
        if messagebox.askyesno("Cancelar instalação",
                               "Deseja realmente cancelar?", icon="warning"):
            self.root.quit()

    # ── Validação ─────────────────────────────────────────────
    def _validate(self) -> bool:
        token = self.token.get().strip()
        if not self.install_dir.get().strip():
            self._flash_error("Informe o diretório de instalação.")
            return False
        if not token:
            self._flash_error("Informe o token de instalação.")
            return False
        if len(token) != 8:
            self._flash_error("O token deve ter exatamente 8 caracteres.")
            return False
        return True

    def _flash_error(self, msg):
        top = tk.Toplevel(self.root)
        top.title("Atenção")
        top.geometry("360x140")
        top.resizable(False, False)
        top.configure(bg=C["panel"])
        top.grab_set()
        tk.Label(top, text="⚠", font=("Segoe UI", 24),
                 bg=C["panel"], fg=C["warn"]).pack(pady=(20, 4))
        tk.Label(top, text=msg, font=("Segoe UI", 10),
                 bg=C["panel"], fg=C["text"]).pack()
        tk.Button(top, text="OK", command=top.destroy,
                  bg=C["accent2"], fg=C["white"], relief=tk.FLAT,
                  font=("Segoe UI", 10), padx=24, pady=6,
                  cursor="hand2").pack(pady=12)

    # ── Progress ──────────────────────────────────────────────
    def _set_progress(self, pct, title="", sub=""):
        def _upd():
            self._pb_value = pct
            total_w  = self._pb_track.winfo_width()
            fill_w   = max(0, int(total_w * pct / 100))
            self._pb_fill.place(x=0, y=0, width=fill_w, height=6)
            self._pb_pct.config(text=f"{pct}%")
            if title: self._status_title.config(text=title)
            if sub:   self._status_sub.config(text=sub)
        self.root.after(0, _upd)

    def _set_status_icon(self, icon, color=None):
        self.root.after(0, lambda: self._status_icon.config(
            text=icon, fg=color or C["accent"]))

    # ── Log ───────────────────────────────────────────────────
    def _log(self, msg: str, level="INFO"):
        def _upd():
            ts = time.strftime("%H:%M:%S")
            self.log_widget.insert(tk.END, f"[{ts}]  ", "TS")
            self.log_widget.insert(tk.END, f"{msg}\n", level)
            self.log_widget.see(tk.END)
        self.root.after(0, _upd)

    # ── Instalação ────────────────────────────────────────────
    def _install(self):
        try:
            install_dir   = Path(self.install_dir.get())
            token         = self.token.get().strip()
            token_hash    = hashlib.sha256(token.encode()).hexdigest()
            installer_dir = Path(sys.executable if getattr(sys, "frozen", False)
                                 else __file__).parent

            steps = [
                (5,  "Preparando",               "Criando estrutura de diretórios…"),
                (20, "Localizando NSSM",          "Verificando dependências…"),
                (35, "Copiando arquivos",         "Copiando executáveis…"),
                (50, "Configurando serviço",      "Registrando no Windows…"),
                (65, "Variáveis de ambiente",     "Aplicando configurações…"),
                (78, "Autorun (todos usuários)",  "Registrando em HKLM\\Run…"),
                (88, "Atalho Desktop Público",    "Criando em C:\\Users\\Public\\Desktop…"),
                (94, "Iniciando serviços",        "Iniciando agent_service e agent_tray…"),
                (100,"Concluído",                 "Instalação finalizada com sucesso!"),
            ]

            def step(i):
                pct, t, s = steps[i]
                self._set_progress(pct, t, s)
                self._log(s)

            # 1. Diretório
            step(0)
            install_dir.mkdir(parents=True, exist_ok=True)
            self._log(f"✓  {install_dir}", "OK")

            # 2. NSSM
            step(1)
            nssm = self._find_nssm(installer_dir)
            self._log(f"✓  NSSM: {nssm}", "OK")

            # 3. Executáveis
            step(2)
            _, svc_dst = self._copy_agent(installer_dir, install_dir, "agent_service")
            self._log(f"✓  Serviço: {svc_dst.name}", "OK")
            tray_dst = None
            if self.install_tray.get():
                _, tray_dst = self._copy_agent(installer_dir, install_dir, "agent_tray")
                self._log(f"✓  Tray: {tray_dst.name}", "OK")

            # 4. Serviço
            step(3)
            self._remove_service(nssm)
            self._install_service(nssm, svc_dst, token)
            self._log(f"✓  Serviço '{SERVICE_NAME}' registrado", "OK")

            # 5. Envs
            step(4)
            envs = {
                "AGENT_SERVER_URL":    SERVER_URL,
                "AGENT_TOKEN_HASH":    token_hash,
                "AGENT_AUTO_UPDATE":   "true" if self.auto_update.get() else "false",
                "AGENT_NOTIFICATIONS": "true" if self.notifs.get() else "false",
            }
            for k, v in envs.items():
                subprocess.run(
                    [nssm, "set", SERVICE_NAME, "AppEnvironmentExtra", f"{k}={v}"],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self._log("✓  Variáveis configuradas", "OK")

            # 6. Autorun HKLM — todos os usuários
            step(5)
            if tray_dst and self.install_tray.get():
                ok = register_tray_autorun_all_users(tray_dst)
                if ok:
                    self._log("✓  Tray registrado em HKLM\\Run (todos os usuários)", "OK")
                else:
                    self._log("⚠  Falha ao registrar HKLM\\Run", "WARN")
            else:
                self._log("—  Tray App não selecionado, pulado", "INFO")

            # 7. Atalho Desktop Público
            step(6)
            if tray_dst and self.desktop_shortcut.get():
                ok = create_shortcut_all_users(tray_dst)
                desktop_path = get_public_desktop()
                if ok:
                    self._log(f"✓  Atalho criado em {desktop_path}", "OK")
                else:
                    self._log("⚠  Atalho não criado", "WARN")
            else:
                self._log("—  Atalho não solicitado, pulado", "INFO")

            # 8. Iniciar
            step(7)
            r = subprocess.run(
                [nssm, "start", SERVICE_NAME],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                self._log("✓  agent_service iniciado", "OK")
            else:
                self._log("⚠  Serviço instalado, mas não iniciou automaticamente", "WARN")

            if tray_dst and self.install_tray.get():
                subprocess.Popen([str(tray_dst)],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                self._log("✓  agent_tray iniciado", "OK")

            # 9. Fim
            step(8)
            self._set_status_icon("✓", C["success"])
            self._log("", "INFO")
            self._log("━" * 44, "OK")
            self._log("  INSTALAÇÃO CONCLUÍDA!", "OK")
            self._log("━" * 44, "OK")
            self.root.after(800, lambda: self._finish(install_dir))

        except Exception as e:
            self._log(f"✗  ERRO: {e}", "ERR")
            self._set_status_icon("✗", C["error"])
            self._set_progress(self._pb_value, "Erro na instalação", str(e))
            self.root.after(0, lambda: self._btn_cancel.config(state=tk.NORMAL))
            self.root.after(0, lambda: self._btn_back.config(state=tk.NORMAL))
            self.root.after(0, lambda: self._btn_next.config(state=tk.NORMAL,
                                                              text="Tentar novamente"))

    def _finish(self, install_dir: Path):
        self._show_page(3)
        self._btn_next.config(text="Concluir", state=tk.NORMAL)
        for w in self._done_cards.winfo_children():
            w.destroy()
        infos = [
            ("⚙",  "Serviço Windows",    SERVICE_NAME),
            ("👥", "Autorun",            "HKLM\\Run — todos os usuários"),
            ("📡", "IPC local",          f"127.0.0.1:{IPC_PORT}"),
            ("📁", "Diretório",          str(install_dir)),
            ("🔒", "Token",              "Em memória — não salvo em disco"),
        ]
        if self.desktop_shortcut.get():
            infos.append(("🖥", "Atalho", f"{get_public_desktop()}\\Chamados.lnk"))
        for icon, label, value in infos:
            row = tk.Frame(self._done_cards, bg=C["surface"],
                           highlightthickness=1, highlightbackground=C["border"])
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=icon, font=("Segoe UI", 12),
                     bg=C["surface"], fg=C["accent"],
                     padx=14, pady=8).pack(side=tk.LEFT)
            tk.Label(row, text=label, font=("Segoe UI", 9),
                     bg=C["surface"], fg=C["muted"],
                     width=18, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=value, font=("Consolas", 9),
                     bg=C["surface"], fg=C["text"], anchor="w").pack(side=tk.LEFT)
        self._done_sub.config(text="O agente está coletando e enviando dados automaticamente.")

    # ── Helpers de instalação ─────────────────────────────────
    def _find_nssm(self, base: Path) -> str:
        for p in [base/"nssm"/"win64"/"nssm.exe", base/"nssm.exe",
                  Path(__file__).parent/"nssm"/"win64"/"nssm.exe",
                  Path(__file__).parent/"nssm.exe"]:
            if p.exists():
                return str(p)
        raise FileNotFoundError("nssm.exe não encontrado.")

    def _copy_agent(self, src_dir, dst_dir, name):
        for src in [src_dir/f"{name}.exe", Path(__file__).parent/f"{name}.exe"]:
            if src.exists():
                dst = dst_dir / src.name
                shutil.copy2(src, dst)
                return src, dst
        raise FileNotFoundError(f"{name}.exe não encontrado.")

    def _remove_service(self, nssm):
        for cmd in [["stop", SERVICE_NAME], ["remove", SERVICE_NAME, "confirm"]]:
            subprocess.run([nssm]+cmd, capture_output=True, timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW)

    def _install_service(self, nssm, svc_exe, token):
        r = subprocess.run(
            [nssm, "install", SERVICE_NAME, str(svc_exe), f"--token={token}"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(f"Falha: {r.stderr}")
        for args in [
            ["set", SERVICE_NAME, "DisplayName", AGENT_NAME],
            ["set", SERVICE_NAME, "Description",
             "Agente de Inventário — coleta hardware e envia ao servidor"],
            ["set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"],
        ]:
            subprocess.run([nssm]+args, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.install_dir.get())
        if d:
            self.install_dir.set(d)

    def _toggle_token(self):
        self.show_token.set(not self.show_token.get())
        self._tok_entry.config(show="" if self.show_token.get() else "●")
        self._eye_btn.config(text="🙈" if self.show_token.get() else "👁")

    def _require_admin(self):
        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                top = tk.Toplevel(self.root)
                top.title("Permissão necessária")
                top.geometry("400x200")
                top.resizable(False, False)
                top.configure(bg=C["panel"])
                top.grab_set()
                tk.Label(top, text="🛡", font=("Segoe UI", 28),
                         bg=C["panel"], fg=C["warn"]).pack(pady=(20, 4))
                tk.Label(top, text="Execute como Administrador",
                         font=("Segoe UI", 11, "bold"),
                         bg=C["panel"], fg=C["text"]).pack()
                tk.Label(top, text="Botão direito → Executar como administrador",
                         font=("Segoe UI", 9), bg=C["panel"], fg=C["muted"]).pack()
                tk.Button(top, text="Fechar", command=self.root.quit,
                          bg=C["error"], fg=C["white"], relief=tk.FLAT,
                          font=("Segoe UI", 10), padx=24, pady=6,
                          cursor="hand2").pack(pady=14)
        except Exception:
            pass


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    root = tk.Tk()
    app  = AgentInstaller(root)
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth()  // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()