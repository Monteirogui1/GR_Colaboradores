"""
install_agent.py — Instalador atualizado para arquitetura dual
  • Instala agent_service.exe como Serviço Windows (NSSM, Session 0)
  • Instala agent_tray.exe como autorun do usuário (HKCU Run, Session 1+)
"""

import os
import sys
import time
import shutil
import hashlib
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from pathlib import Path

# ─────────────────────────────────────────────
# Configurações (substitua pelo installer_config.py em produção)
# ─────────────────────────────────────────────
try:
    from installer_config import *
except ImportError:
    SERVER_URL          = "http://192.168.1.54:5001"
    INSTALL_DIR         = r"C:\Program Files\InventoryAgent"
    AGENT_NAME          = "Agente de Inventário"
    AGENT_VERSION       = "3.0.0"
    DEFAULT_AUTO_UPDATE = True
    DEFAULT_NOTIFS      = True
    IPC_PORT            = 7070

SERVICE_NAME  = "InventoryAgent"
TRAY_REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
TRAY_REG_VAL  = "InventoryAgentTray"


# ─────────────────────────────────────────────
# Instalador
# ─────────────────────────────────────────────
class AgentInstaller:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Instalador — {AGENT_NAME} v{AGENT_VERSION}")
        self.root.geometry("720x620")
        self.root.resizable(False, False)

        # Variáveis de form
        self.install_dir   = tk.StringVar(value=INSTALL_DIR)
        self.token         = tk.StringVar()
        self.show_token    = tk.BooleanVar(value=False)
        self.auto_update   = tk.BooleanVar(value=DEFAULT_AUTO_UPDATE)
        self.notifs        = tk.BooleanVar(value=DEFAULT_NOTIFS)
        self.install_tray  = tk.BooleanVar(value=True)

        # Caminhos NSSM e executáveis (resolvidos na instalação)
        self.nssm_path: str | None = None

        self._setup_style()
        self._build_ui()
        self._require_admin()

    # ─────────────────────────────────────────
    # Estilo
    # ─────────────────────────────────────────
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        bg = "#f8fafc"
        self.root.configure(bg=bg)
        style.configure("Title.TLabel",  font=("Segoe UI", 15, "bold"), background=bg, foreground="#0f172a")
        style.configure("Sub.TLabel",    font=("Segoe UI", 9),           background=bg, foreground="#64748b")
        style.configure("Primary.TButton", font=("Segoe UI", 10), padding=10)

    # ─────────────────────────────────────────
    # UI Principal
    # ─────────────────────────────────────────
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # Header
        ttk.Label(main, text=f"🚀 {AGENT_NAME}", style="Title.TLabel").pack()
        ttk.Label(main, text="Serviço Windows + Tray App", style="Sub.TLabel").pack()
        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)

        # Notebook
        self.nb = ttk.Notebook(main)
        self.nb.pack(fill=tk.BOTH, expand=True)
        self._tab_welcome()
        self._tab_config()
        self._tab_install()
        self._tab_done()

        # Botões
        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        self.btn_back   = ttk.Button(btn_row, text="← Voltar",  command=self._prev, state=tk.DISABLED)
        self.btn_back.pack(side=tk.LEFT)
        self.btn_cancel = ttk.Button(btn_row, text="Cancelar",  command=self._cancel)
        self.btn_cancel.pack(side=tk.RIGHT, padx=(0, 8))
        self.btn_next   = ttk.Button(btn_row, text="Avançar →", command=self._next, style="Primary.TButton")
        self.btn_next.pack(side=tk.RIGHT)

    # ─────────────────────────────────────────
    # Abas
    # ─────────────────────────────────────────
    def _tab_welcome(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Bem-vindo")
        txt = tk.Text(f, wrap=tk.WORD, height=18, font=("Segoe UI", 10),
                      relief=tk.FLAT, bg="#ffffff", padx=20, pady=16)
        txt.insert("1.0", f"""
Bem-vindo ao Instalador do {AGENT_NAME} v{AGENT_VERSION}

ARQUITETURA NOVA (v3):
━━━━━━━━━━━━━━━━━━━━━
 ┌─────────────────────────────────────────┐
 │  Serviço Windows (Session 0)            │
 │  • Coleta hardware via PowerShell       │
 │  • Envia dados ao servidor Django       │
 │  • Servidor HTTP local (127.0.0.1:7070) │
 └────────────────┬────────────────────────┘
                  │ HTTP local (IPC)
 ┌────────────────▼────────────────────────┐
 │  Tray App (Session do usuário)          │
 │  • Ícone na bandeja do sistema          │
 │  • Notificações nativas Windows         │
 │  • Terminal para executar PS/CMD        │
 │  • Painel de status em tempo real       │
 └─────────────────────────────────────────┘

🔒 SEGURANÇA:
 • Token nunca salvo em disco
 • IPC restrito a 127.0.0.1
 • Comandos remotos com timeout máximo

⚡ PERFORMANCE:
 • Heartbeat a cada 5 min + jitter aleatório
 • Evita sobrecarga simultânea no servidor
""")
        txt.config(state=tk.DISABLED)
        txt.pack(fill=tk.BOTH, expand=True)

    def _tab_config(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Configuração")

        # Diretório
        grp = ttk.LabelFrame(f, text="Diretório de Instalação", padding=12)
        grp.pack(fill=tk.X, pady=(0, 12))
        entry = ttk.Entry(grp, textvariable=self.install_dir, width=52, font=("Segoe UI", 10))
        entry.pack(side=tk.LEFT)
        ttk.Button(grp, text="…", command=self._browse, width=3).pack(side=tk.LEFT, padx=6)

        # Token
        grp2 = ttk.LabelFrame(f, text="Autenticação", padding=12)
        grp2.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(grp2, text="Token (8 caracteres):").grid(row=0, column=0, sticky=tk.W)
        self._token_entry = ttk.Entry(grp2, textvariable=self.token, width=32,
                                      font=("Courier New", 12, "bold"), show="*")
        self._token_entry.grid(row=0, column=1, padx=8)
        ttk.Checkbutton(grp2, text="Mostrar", variable=self.show_token,
                        command=self._toggle_token).grid(row=1, column=1, sticky=tk.W, padx=8)
        ttk.Label(grp2, text="🔒 Não salvo em disco — apenas em variável de ambiente do serviço",
                  foreground="#16a34a", font=("Segoe UI", 8)).grid(row=2, column=1, sticky=tk.W, padx=8, pady=4)

        # Opções
        grp3 = ttk.LabelFrame(f, text="Opções", padding=12)
        grp3.pack(fill=tk.X)
        ttk.Checkbutton(grp3, text="Atualizações automáticas do agente", variable=self.auto_update).pack(anchor=tk.W)
        ttk.Checkbutton(grp3, text="Notificações (requer Tray App)",      variable=self.notifs).pack(anchor=tk.W)
        ttk.Checkbutton(grp3, text="Instalar Tray App (autorun do usuário)", variable=self.install_tray).pack(anchor=tk.W)

    def _tab_install(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Instalação")
        ttk.Label(f, text="Instalando…", font=("Segoe UI", 11, "bold")).pack(pady=(8, 4))
        self.progress = ttk.Progressbar(f, mode="indeterminate", length=450)
        self.progress.pack(pady=8)
        log_frame = ttk.LabelFrame(f, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_widget = scrolledtext.ScrolledText(
            log_frame, height=14, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="#ffffff")
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        # Tags
        self.log_widget.tag_config("OK",   foreground="#4ec9b0")
        self.log_widget.tag_config("WARN", foreground="#dcdcaa")
        self.log_widget.tag_config("ERR",  foreground="#f48771")
        self.log_widget.tag_config("INFO", foreground="#d4d4d4")

    def _tab_done(self):
        f = ttk.Frame(self.nb, padding=20)
        self.nb.add(f, text="Concluído")
        self.lbl_done = ttk.Label(f, text="", font=("Segoe UI", 10), justify=tk.CENTER)
        self.lbl_done.pack(expand=True)

    # ─────────────────────────────────────────
    # Navegação
    # ─────────────────────────────────────────
    def _next(self):
        cur = self.nb.index("current")
        if cur == 0:
            self.nb.select(1); self.btn_back.config(state=tk.NORMAL)
        elif cur == 1:
            if self._validate():
                self.nb.select(2)
                self.btn_back.config(state=tk.DISABLED)
                self.btn_next.config(state=tk.DISABLED)
                self.btn_cancel.config(state=tk.DISABLED)
                self.progress.start(10)
                threading.Thread(target=self._install, daemon=True).start()
        elif cur == 3:
            self.root.quit()

    def _prev(self):
        cur = self.nb.index("current")
        if cur > 0:
            self.nb.select(cur - 1)
        if self.nb.index("current") == 0:
            self.btn_back.config(state=tk.DISABLED)

    def _cancel(self):
        if messagebox.askyesno("Cancelar", "Deseja cancelar a instalação?"):
            self.root.quit()

    # ─────────────────────────────────────────
    # Validação
    # ─────────────────────────────────────────
    def _validate(self) -> bool:
        token = self.token.get().strip()
        if not self.install_dir.get().strip():
            messagebox.showerror("Erro", "Informe o diretório de instalação.")
            return False
        if not token:
            messagebox.showerror("Erro", "Informe o token de instalação.")
            return False
        if len(token) != 8:
            messagebox.showerror("Erro", "Token deve ter exatamente 8 caracteres.")
            return False
        return True

    # ─────────────────────────────────────────
    # Instalação
    # ─────────────────────────────────────────
    def _log(self, msg: str, level="INFO"):
        ts = time.strftime("%H:%M:%S")
        self.log_widget.insert(tk.END, f"[{ts}] ", "INFO")
        self.log_widget.insert(tk.END, f"{msg}\n", level)
        self.log_widget.see(tk.END)
        self.log_widget.update()

    def _install(self):
        try:
            install_dir = Path(self.install_dir.get())
            token = self.token.get().strip()
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            installer_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent

            # 1. Diretório
            self._log("Criando diretório de instalação…")
            install_dir.mkdir(parents=True, exist_ok=True)
            self._log(f"✓ {install_dir}", "OK")

            # 2. NSSM
            self._log("Localizando NSSM…")
            nssm = self._find_nssm(installer_dir)
            self._log(f"✓ NSSM: {nssm}", "OK")

            # 3. Copiar executável do serviço
            self._log("Copiando agent_service…")
            svc_src, svc_dst = self._copy_agent(installer_dir, install_dir, "agent_service")
            self._log(f"✓ Serviço: {svc_dst.name}", "OK")

            # 4. Copiar Tray App (se habilitado)
            tray_dst = None
            if self.install_tray.get():
                self._log("Copiando agent_tray…")
                _, tray_dst = self._copy_agent(installer_dir, install_dir, "agent_tray")
                self._log(f"✓ Tray: {tray_dst.name}", "OK")

            # 5. Remover serviço anterior
            self._log("Removendo serviço anterior (se existir)…")
            self._remove_service(nssm)

            # 6. Instalar serviço Windows
            self._log("Instalando serviço Windows…")
            self._install_service(nssm, svc_dst, token)

            # 7. Variáveis de ambiente do serviço
            self._log("Configurando variáveis de ambiente…")
            envs = {
                "AGENT_SERVER_URL":   SERVER_URL,
                "AGENT_TOKEN_HASH":   token_hash,
                "AGENT_AUTO_UPDATE":  "true" if self.auto_update.get() else "false",
                "AGENT_NOTIFICATIONS": "true" if self.notifs.get() else "false",
            }
            for k, v in envs.items():
                subprocess.run(
                    [nssm, "set", SERVICE_NAME, "AppEnvironmentExtra", f"{k}={v}"],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            self._log("✓ Variáveis configuradas", "OK")

            # 8. Autorun do Tray App via registro
            if tray_dst and self.install_tray.get():
                self._log("Registrando Tray App no autorun do usuário…")
                self._register_tray_autorun(tray_dst)
                self._log("✓ Tray registrado em HKCU\\Run", "OK")

            # 9. Iniciar serviço
            self._log("Iniciando serviço…")
            r = subprocess.run(
                [nssm, "start", SERVICE_NAME],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                self._log("✓ Serviço iniciado!", "OK")
            else:
                self._log("⚠ Serviço instalado, mas não iniciou automaticamente", "WARN")

            # 10. Iniciar Tray App imediatamente
            if tray_dst and self.install_tray.get():
                self._log("Iniciando Tray App…")
                subprocess.Popen(
                    [str(tray_dst)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self._log("✓ Tray App iniciado", "OK")

            # Finalização
            self._log("")
            self._log("━" * 48, "OK")
            self._log("  INSTALAÇÃO CONCLUÍDA COM SUCESSO!", "OK")
            self._log("━" * 48, "OK")
            self._log(f"  Serviço:  {SERVICE_NAME} (services.msc)")
            self._log(f"  IPC:      127.0.0.1:{IPC_PORT}")
            self._log(f"  Diretório: {install_dir}")
            self._log(f"  🔒 Token em memória — não salvo em disco")

            self.root.after(0, self.progress.stop)
            self.root.after(0, lambda: self.lbl_done.config(text=self._done_text(install_dir)))
            self.root.after(500, lambda: self.nb.select(3))
            self.root.after(500, lambda: self.btn_next.config(text="Concluir", state=tk.NORMAL))

        except Exception as e:
            self._log(f"✗ ERRO: {e}", "ERR")
            self.progress.stop()
            self.root.after(0, lambda: messagebox.showerror("Erro", str(e)))
            self.root.after(0, lambda: self.nb.select(1))
            self.root.after(0, lambda: self.btn_next.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.btn_back.config(state=tk.NORMAL))

    # ─────────────────────────────────────────
    # Helpers de instalação
    # ─────────────────────────────────────────
    def _find_nssm(self, base: Path) -> str:
        candidates = [
            base / "nssm" / "win64" / "nssm.exe",
            base / "nssm.exe",
            Path(__file__).parent / "nssm" / "win64" / "nssm.exe",
            Path(__file__).parent / "nssm.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        raise FileNotFoundError(
            "nssm.exe não encontrado. Coloque-o na pasta do instalador ou em nssm/win64/"
        )

    def _copy_agent(self, src_dir: Path, dst_dir: Path, name: str):
        """Copia agent_service.exe ou agent_tray.exe para o diretório de instalação."""
        candidates = [
            src_dir / f"{name}.exe",
            Path(__file__).parent / f"{name}.exe",
        ]
        for src in candidates:
            if src.exists():
                dst = dst_dir / src.name
                shutil.copy2(src, dst)
                return src, dst
        raise FileNotFoundError(
            f"{name}.exe não encontrado. Compile os executáveis com PyInstaller antes de distribuir."
        )

    def _remove_service(self, nssm: str):
        for cmd in [["stop", SERVICE_NAME], ["remove", SERVICE_NAME, "confirm"]]:
            subprocess.run(
                [nssm] + cmd,
                capture_output=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    def _install_service(self, nssm: str, svc_exe: Path, token: str):
        r = subprocess.run(
            [nssm, "install", SERVICE_NAME, str(svc_exe), f"--token={token}"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Falha ao instalar serviço: {r.stderr}")
        # Configurações adicionais
        for args in [
            ["set", SERVICE_NAME, "DisplayName", AGENT_NAME],
            ["set", SERVICE_NAME, "Description", "Agente de Inventário — coleta hardware e envia ao servidor"],
            ["set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"],
        ]:
            subprocess.run([nssm] + args, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)

    def _register_tray_autorun(self, tray_exe: Path):
        """Registra o Tray App no autorun do usuário atual (HKCU)."""
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TRAY_REG_KEY,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, TRAY_REG_VAL, 0, winreg.REG_SZ, str(tray_exe))

    def _done_text(self, install_dir: Path) -> str:
        tray_info = "✓ Tray App ativo na bandeja do sistema" if self.install_tray.get() else ""
        return f"""
✅ Instalação Concluída!

 Serviço Windows:  {SERVICE_NAME}  (services.msc)
 Tray App:         {tray_info}
 Diretório:        {install_dir}
 IPC local:        127.0.0.1:{IPC_PORT}

 🔒 Token em memória — não salvo em disco.

 O agente está coletando e enviando dados
 automaticamente a cada 5 minutos.
"""

    # ─────────────────────────────────────────
    # Utilitários
    # ─────────────────────────────────────────
    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.install_dir.get())
        if d:
            self.install_dir.set(d)

    def _toggle_token(self):
        self._token_entry.config(show="" if self.show_token.get() else "*")

    def _require_admin(self):
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                messagebox.showerror(
                    "Permissão necessária",
                    "Execute o instalador como Administrador.\n"
                    "(Botão direito → Executar como administrador)"
                )
                self.root.quit()
        except Exception:
            pass  # não-Windows


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    root = tk.Tk()
    app = AgentInstaller(root)
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth()  // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()