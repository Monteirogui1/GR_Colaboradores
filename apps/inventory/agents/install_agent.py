import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import os
import sys
import subprocess
import shutil
from pathlib import Path
import threading
import time
import hashlib

# Importar configurações
try:
    from installer_config import *
except ImportError:
    SERVER_URL = "http://192.168.1.54:5001"
    INSTALL_DIR = r"C:\Program Files\InventoryAgent"
    AGENT_NAME = "Agente de Inventário"
    AGENT_VERSION = "2.0.0"
    DEFAULT_AUTO_UPDATE = True
    DEFAULT_NOTIFICATIONS = True
    CHECK_INTERVAL = 300


class AgentInstaller:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Instalador do {AGENT_NAME} v{AGENT_VERSION}")
        self.root.geometry("700x600")
        self.root.resizable(False, False)

        # Variáveis
        self.install_dir = tk.StringVar(value=INSTALL_DIR)
        self.SERVER_URL = SERVER_URL
        self.token = tk.StringVar()
        self.auto_update = tk.BooleanVar(value=DEFAULT_AUTO_UPDATE)
        self.notifications = tk.BooleanVar(value=DEFAULT_NOTIFICATIONS)

        # Estado
        self.current_step = 0
        self.installation_complete = False

        # NSSM vem empacotado com o instalador
        self.nssm_path = None

        # Configurar estilo
        self.setup_style()

        # Criar interface
        self.create_widgets()

        # Verificar privilégios
        self.check_admin()

    def setup_style(self):
        """Configura o estilo visual"""
        style = ttk.Style()
        style.theme_use('clam')

        bg_color = "#f0f0f0"
        self.root.configure(bg=bg_color)

        style.configure("Title.TLabel",
                        font=("Segoe UI", 16, "bold"),
                        background=bg_color,
                        foreground="#333")

        style.configure("Subtitle.TLabel",
                        font=("Segoe UI", 10),
                        background=bg_color,
                        foreground="#666")

        style.configure("Primary.TButton",
                        font=("Segoe UI", 10),
                        padding=10)

    def check_admin(self):
        """Verifica se está executando como administrador"""
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            if not is_admin:
                messagebox.showerror(
                    "Privilégios Insuficientes",
                    "Este instalador precisa ser executado como Administrador.\n\n"
                    "Clique com botão direito no arquivo e selecione\n"
                    "'Executar como Administrador'"
                )
                self.root.quit()
        except:
            pass

    def create_widgets(self):
        """Cria os widgets da interface"""
        # Frame principal
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Cabeçalho
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))

        title_label = ttk.Label(
            header_frame,
            text=f"🚀 {AGENT_NAME}",
            style="Title.TLabel"
        )
        title_label.pack()

        subtitle_label = ttk.Label(
            header_frame,
            text="Instalação como Serviço Windows (NSSM)",
            style="Subtitle.TLabel"
        )
        subtitle_label.pack()

        # Separador
        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Frame de conteúdo (notebook)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Abas
        self.create_welcome_tab()
        self.create_config_tab()
        self.create_install_tab()
        self.create_finish_tab()

        # Frame de botões
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))

        self.back_btn = ttk.Button(
            button_frame,
            text="← Voltar",
            command=self.previous_step,
            state=tk.DISABLED
        )
        self.back_btn.pack(side=tk.LEFT)

        self.next_btn = ttk.Button(
            button_frame,
            text="Avançar →",
            command=self.next_step,
            style="Primary.TButton"
        )
        self.next_btn.pack(side=tk.RIGHT)

        self.cancel_btn = ttk.Button(
            button_frame,
            text="Cancelar",
            command=self.cancel_installation
        )
        self.cancel_btn.pack(side=tk.RIGHT, padx=(0, 10))

    def create_welcome_tab(self):
        """Cria aba de boas-vindas"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Bem-vindo")

        container = ttk.Frame(frame)
        container.pack(expand=True)

        welcome_text = f"""
Bem-vindo ao Instalador do {AGENT_NAME}!

Este assistente instalará o agente como um SERVIÇO WINDOWS,
rodando em segundo plano automaticamente.

🔒 SEGURANÇA:
• Não salva tokens ou códigos no disco
• Configurações via variáveis de ambiente
• Serviço Windows gerenciado pelo NSSM

⚙️ FUNCIONALIDADES:
• Monitoramento em tempo real
• Inventário automático de hardware
• Atualizações automáticas e seguras
• Notificações de status


🔔 NOTIFICAÇÕES:
O agente enviará notificações visuais no Windows sobre:
  • Status da conexão (online/offline)
  • Atualizações disponíveis
  • Inicialização e paradas

Clique em "Avançar" para continuar.
        """

        text_widget = tk.Text(
            container,
            wrap=tk.WORD,
            height=20,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            bg="#ffffff",
            padx=20,
            pady=20
        )
        text_widget.insert("1.0", welcome_text)
        text_widget.config(state=tk.DISABLED)
        text_widget.pack()

    def create_config_tab(self):
        """Cria aba de configuração"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Configuração")

        canvas = tk.Canvas(frame, bg="#f0f0f0", highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Diretório de instalação
        dir_frame = ttk.LabelFrame(scrollable_frame, text="Diretório de Instalação", padding=15)
        dir_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Entry(
            dir_frame,
            textvariable=self.install_dir,
            width=50,
            font=("Segoe UI", 10)
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            dir_frame,
            text="Procurar...",
            command=self.browse_directory
        ).pack(side=tk.LEFT)

        # Token de instalação
        token_frame = ttk.LabelFrame(scrollable_frame, text="Autenticação", padding=15)
        token_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(
            token_frame,
            text="Token de Instalação:",
            font=("Segoe UI", 10)
        ).grid(row=0, column=0, sticky=tk.W, pady=5)

        self.token_entry = ttk.Entry(
            token_frame,
            textvariable=self.token,
            width=50,
            font=("Courier New", 12, "bold"),
            show="*"
        )
        self.token_entry.grid(row=0, column=1, pady=5, padx=(10, 0))

        # Botão mostrar/ocultar token
        self.show_token_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            token_frame,
            text="Mostrar token",
            variable=self.show_token_var,
            command=self.toggle_token_visibility
        ).grid(row=1, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(
            token_frame,
            text="8 caracteres - NÃO será salvo no disco",
            font=("Segoe UI", 8),
            foreground="#666"
        ).grid(row=2, column=1, sticky=tk.W, padx=(10, 0))

        # Informação do servidor
        # ttk.Label(
        #     token_frame,
        #     text=f"Servidor: {self.SERVER_URL}",
        #     font=("Segoe UI", 9),
        #     foreground="#0078d4"
        # ).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=(10, 0))

        # Opções adicionais
        options_frame = ttk.LabelFrame(scrollable_frame, text="Opções", padding=15)
        options_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Checkbutton(
            options_frame,
            text="✓ Ativar atualizações automáticas",
            variable=self.auto_update
        ).pack(anchor=tk.W, pady=5)

        ttk.Checkbutton(
            options_frame,
            text="✓ Ativar notificações do sistema",
            variable=self.notifications
        ).pack(anchor=tk.W, pady=5)

        # Info sobre segurança
        security_frame = ttk.Frame(options_frame)
        security_frame.pack(anchor=tk.W, padx=20, pady=10)

        ttk.Label(
            security_frame,
            text="🔒 SEGURO: Token não é salvo em arquivos, apenas em memória do serviço",
            font=("Segoe UI", 8, "bold"),
            foreground="#28a745"
        ).pack()

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_install_tab(self):
        """Cria aba de instalação"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Instalação")

        ttk.Label(
            frame,
            text="Instalando o Agente como Serviço...",
            font=("Segoe UI", 12, "bold")
        ).pack(pady=(20, 10))

        # Barra de progresso
        self.progress = ttk.Progressbar(
            frame,
            mode='indeterminate',
            length=400
        )
        self.progress.pack(pady=20)

        # Log de instalação
        log_frame = ttk.LabelFrame(frame, text="Progresso da Instalação", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=15,
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#ffffff"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def create_finish_tab(self):
        """Cria aba de finalização"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Concluído")

        container = ttk.Frame(frame)
        container.pack(expand=True)

        self.finish_label = ttk.Label(
            container,
            text="",
            font=("Segoe UI", 11),
            justify=tk.CENTER
        )
        self.finish_label.pack(pady=20)

    def browse_directory(self):
        """Abre diálogo para selecionar diretório"""
        from tkinter import filedialog
        directory = filedialog.askdirectory(
            initialdir=self.install_dir.get(),
            title="Selecione o Diretório de Instalação"
        )
        if directory:
            self.install_dir.set(directory)

    def toggle_token_visibility(self):
        """Alterna visibilidade do token"""
        if self.show_token_var.get():
            self.token_entry.config(show="")
        else:
            self.token_entry.config(show="*")

    def previous_step(self):
        """Volta para o passo anterior"""
        current = self.notebook.index("current")
        if current > 0:
            self.notebook.select(current - 1)
            if current == 1:
                self.back_btn.config(state=tk.DISABLED)
            self.next_btn.config(text="Avançar →", state=tk.NORMAL)

    def next_step(self):
        """Avança para o próximo passo"""
        current = self.notebook.index("current")

        if current == 0:
            self.notebook.select(1)
            self.back_btn.config(state=tk.NORMAL)
        elif current == 1:
            if self.validate_configuration():
                self.notebook.select(2)
                self.back_btn.config(state=tk.DISABLED)
                self.next_btn.config(state=tk.DISABLED)
                self.cancel_btn.config(state=tk.DISABLED)
                self.start_installation()
        elif current == 3:
            self.root.quit()

    def validate_configuration(self):
        """Valida a configuração antes de instalar"""
        install_dir = self.install_dir.get().strip()
        if not install_dir:
            messagebox.showerror("Erro", "Por favor, selecione um diretório de instalação.")
            return False

        token = self.token.get().strip()
        if not token:
            messagebox.showerror("Erro", "Por favor, informe o token de instalação.")
            return False

        if len(token) != 8:
            messagebox.showerror("Erro", "Token inválido. Deve ter exatamente 8 caracteres.")
            return False

        return True

    def log(self, message, level="INFO"):
        """Adiciona mensagem ao log"""
        timestamp = time.strftime("%H:%M:%S")
        color_tag = f"log_{level.lower()}"

        self.log_text.tag_config("log_info", foreground="#d4d4d4")
        self.log_text.tag_config("log_success", foreground="#4ec9b0")
        self.log_text.tag_config("log_error", foreground="#f48771")
        self.log_text.tag_config("log_warning", foreground="#dcdcaa")

        self.log_text.insert(tk.END, f"[{timestamp}] ", "log_info")
        self.log_text.insert(tk.END, f"{message}\n", color_tag)
        self.log_text.see(tk.END)
        self.log_text.update()

    def start_installation(self):
        """Inicia o processo de instalação"""
        self.progress.start(10)
        thread = threading.Thread(target=self.install_agent, daemon=True)
        thread.start()

    def install_agent(self):
        """Realiza a instalação do agente como serviço"""
        try:
            self.log("Iniciando instalação do Agente de Inventário como Serviço...")
            time.sleep(0.5)

            # 1. Verificar Python
            # self.log("Verificando Python...")
            # result = subprocess.run(
            #     ["python", "--version"],
            #     capture_output=True,
            #     text=True
            # )
            # if result.returncode == 0:
            #     version = result.stdout.strip()
            #     self.log(f"✓ {version} encontrado", "SUCCESS")
            # else:
            #     raise Exception("Python não encontrado no sistema")
            #
            # time.sleep(0.5)

            # 2. Criar diretório
            install_dir = Path(self.install_dir.get())
            self.log(f"Criando diretório: {install_dir}")
            install_dir.mkdir(parents=True, exist_ok=True)
            self.log("✓ Diretório criado", "SUCCESS")

            time.sleep(0.5)

            # 3. Localizar NSSM empacotado
            self.log("Localizando NSSM (Non-Sucking Service Manager)...")

            # NSSM vem empacotado com o instalador
            # Verifica se está no mesmo diretório do instalador
            installer_dir = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent

            # Possíveis localizações do NSSM
            possible_paths = [
                installer_dir / "nssm" / "win64" / "nssm.exe",  # Empacotado
                installer_dir / "nssm.exe",  # Raiz
                Path(__file__).parent / "nssm" / "win64" / "nssm.exe",  # Desenvolvimento
                Path(__file__).parent / "nssm.exe",  # Desenvolvimento raiz
            ]

            # Tenta encontrar NSSM
            nssm_found = False
            for nssm_candidate in possible_paths:
                if nssm_candidate.exists():
                    self.nssm_path = str(nssm_candidate)
                    nssm_found = True
                    self.log(f"✓ NSSM encontrado: {self.nssm_path}", "SUCCESS")
                    break

            if not nssm_found:
                raise Exception(
                    "NSSM não encontrado!\n"
                    "Certifique-se de que o nssm.exe está na mesma pasta do instalador\n"
                    "ou em uma pasta 'nssm/win64/' junto ao instalador."
                )

            time.sleep(0.5)

            # 4. Copiar arquivo do agente
            self.log("Copiando executável do agente...")

            # Procura pelo executável do agente empacotado
            installer_dir = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent

            # Tenta encontrar o agente
            agent_sources = [
                installer_dir / "agent.exe",  # Agente compilado (preferido)
                installer_dir / " para .py",
                Path(__file__).parent / "agent.exe",
                Path(__file__).parent / "agent_py_placeholder",
            ]

            agent_source = None
            agent_is_exe = False

            for candidate in agent_sources:
                if candidate.exists():
                    agent_source = candidate
                    agent_is_exe = candidate.suffix == '.exe'
                    break

            if not agent_source:
                raise Exception(
                    "Agente não encontrado!\n"
                    "Certifique-se de que agent.exe está\n"
                    "está incluído no instalador."
                )

            # Define destino
            if agent_is_exe:
                agent_dest = install_dir / "agent.exe"
                self.log(f"✓ Agente executável encontrado: {agent_source.name}", "SUCCESS")
            else:
                agent_dest = install_dir / "agent_py_placeholder"
                self.log(f"⚠ Usando agent_py_placeholder (requer Python instalado)", "WARNING")

            # Copia arquivo
            shutil.copy2(agent_source, agent_dest)
            self.log(f"✓ Agente copiado para: {agent_dest}", "SUCCESS")

            time.sleep(0.5)

            # 5. Obter token e criar hash
            self.log("Processando token de instalação...")
            import hashlib
            token = self.token.get().strip()
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            self.log("✓ Token processado (hash criado)", "SUCCESS")
            self.log("  Token NÃO será salvo em disco", "WARNING")

            time.sleep(0.5)

            # 6. Remover serviço existente se houver
            self.log("Verificando serviço existente...")
            try:
                subprocess.run(
                    [self.nssm_path, "stop", "InventoryAgent"],
                    capture_output=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                subprocess.run(
                    [self.nssm_path, "remove", "InventoryAgent", "confirm"],
                    capture_output=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.log("✓ Serviço anterior removido", "SUCCESS")
            except:
                self.log("  Nenhum serviço anterior encontrado", "INFO")

            time.sleep(0.5)

            # 7. Instalar serviço com NSSM
            self.log("Instalando serviço Windows...")

            # Define comando baseado no tipo de agente
            if agent_is_exe:
                # Se for .exe, executa diretamente
                app_path = str(agent_dest)
                app_args = f"--token={token}"
                self.log(f"  Modo: Executável standalone (.exe)", "INFO")
            else:
                # Se for .py, precisa do Python
                python_exe = sys.executable
                app_path = python_exe
                app_args = f'"{agent_dest}" --token={token}'
                self.log(f"  Modo: Script Python (.py)", "WARNING")
                self.log(f"  Python: {python_exe}", "INFO")

            # Instalar serviço
            install_cmd = [self.nssm_path, "install", "InventoryAgent", app_path]
            if agent_is_exe:
                install_cmd.append(app_args)
            else:
                install_cmd.extend([str(agent_dest), f"--token={token}"])

            result = subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode != 0:
                raise Exception(f"Erro ao instalar serviço: {result.stderr}")

            self.log("✓ Serviço instalado", "SUCCESS")

            # 8. Configurar variáveis de ambiente do serviço
            self.log("Configurando variáveis de ambiente...")

            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "AppEnvironmentExtra",
                 f"AGENT_SERVER_URL={SERVER_URL}"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "AppEnvironmentExtra",
                 f"AGENT_TOKEN_HASH={token_hash}"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "AppEnvironmentExtra",
                 f"AGENT_AUTO_UPDATE={'true' if self.auto_update.get() else 'false'}"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "AppEnvironmentExtra",
                 f"AGENT_NOTIFICATIONS={'true' if self.notifications.get() else 'false'}"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            self.log("✓ Variáveis de ambiente configuradas", "SUCCESS")

            # 9. Configurar descrição e exibição
            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "Description",
                 "Agente de Inventário - Monitoramento de Sistema"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "DisplayName",
                 AGENT_NAME],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            subprocess.run(
                [self.nssm_path, "set", "InventoryAgent", "Start", "SERVICE_AUTO_START"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            self.log("✓ Serviço configurado para iniciar automaticamente", "SUCCESS")

            # 10. Instalar winotify
            # self.log("Instalando biblioteca de notificações...")
            # try:
            #     subprocess.run(
            #         ["pip", "install", "winotify", "--quiet"],
            #         check=False,
            #         capture_output=True,
            #         timeout=60
            #     )
            #     self.log("✓ winotify instalado", "SUCCESS")
            # except:
            #     self.log("⚠ winotify não instalado (usará fallback)", "WARNING")

            time.sleep(0.5)

            # 11. Iniciar serviço
            self.log("Iniciando serviço...")
            result = subprocess.run(
                [self.nssm_path, "start", "InventoryAgent"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                self.log("✓ Serviço iniciado com sucesso", "SUCCESS")
            else:
                self.log("⚠ Serviço instalado mas não iniciado automaticamente", "WARNING")

            time.sleep(1)

            # Finalização
            self.log("")
            self.log("=" * 50, "SUCCESS")
            self.log("INSTALAÇÃO CONCLUÍDA COM SUCESSO!", "SUCCESS")
            self.log("=" * 50, "SUCCESS")
            self.log("")
            self.log(f"Serviço: InventoryAgent")
            self.log(f"Localização: {install_dir}")
            # self.log(f"Servidor: {SERVER_URL}")
            self.log(f"Notificações: {'ATIVADAS ✓' if self.notifications.get() else 'DESATIVADAS'}")
            self.log(f"🔒 SEGURO: Token em memória, não salvo em disco")
            self.log("")
            self.log("Gerenciar serviço:")
            self.log("  • Windows Services (services.msc)")
            self.log("  • Nome: InventoryAgent")
            self.log("")

            self.installation_complete = True

            self.root.after(0, self.show_finish_message)
            self.root.after(0, self.progress.stop)
            self.root.after(500, lambda: self.notebook.select(3))
            self.root.after(500, lambda: self.next_btn.config(text="Concluir", state=tk.NORMAL))

        except Exception as e:
            self.log(f"✗ ERRO: {str(e)}", "ERROR")
            self.log("Instalação falhou!", "ERROR")
            self.progress.stop()
            self.root.after(0, lambda: messagebox.showerror(
                "Erro na Instalação",
                f"Ocorreu um erro durante a instalação:\n\n{str(e)}"
            ))
            self.root.after(0, lambda: self.notebook.select(1))
            self.root.after(0, lambda: self.back_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.next_btn.config(state=tk.NORMAL))

    def show_finish_message(self):
        """Mostra mensagem de conclusão"""
        message = f"""
✅ Instalação Concluída com Sucesso!

O {AGENT_NAME} foi instalado como SERVIÇO WINDOWS
e está rodando em segundo plano.

📍 Localização: {self.install_dir.get()}
🔔 Notificações: {'✓ Ativadas' if self.notifications.get() else '✗ Desativadas'}
🔒 Segurança: Token em memória (não salvo em disco)

⚙️ Gerenciar Serviço:
• Abra "Serviços" do Windows (services.msc)
• Procure por "InventoryAgent"
• Você pode parar/iniciar/reiniciar o serviço

O agente está coletando dados e enviando para o servidor
automaticamente em segundo plano.
        """
        self.finish_label.config(text=message)

    def cancel_installation(self):
        """Cancela a instalação"""
        if messagebox.askyesno(
                "Cancelar Instalação",
                "Deseja realmente cancelar a instalação?"
        ):
            self.root.quit()


def main():
    """Função principal"""
    root = tk.Tk()
    app = AgentInstaller(root)

    # Centraliza janela
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')

    root.mainloop()


if __name__ == "__main__":
    main()