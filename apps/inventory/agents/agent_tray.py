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
import tkinter as tk
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional
from pathlib import Path
from threading import Thread
import psutil
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

# Configurações do Agente
VERSION = "2.3.0"  # Versão atualizada com system tray
UPDATE_CHECK_INTERVAL = 3600
HEARTBEAT_INTERVAL = 60
OFFLINE_CHECK_INTERVAL = 60

# Configurar logging
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger('InventoryAgent')
logger.setLevel(logging.INFO)

logging.basicConfig(
    filename=os.path.join(LOG_DIR, 'agent.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

handler = RotatingFileHandler(
    os.path.join(LOG_DIR, 'agent.log'),
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=3
)
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(handler)

# Desabilitar warnings de SSL
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AgentConfig:
    """Gerenciador de configurações do agente via ambiente/argumentos"""

    def __init__(self):
        self.config = self.load_config()

    def load_config(self):
        """Carrega configurações de variáveis de ambiente"""
        return {
            "server_url": os.environ.get("AGENT_SERVER_URL", "http://192.168.1.54:5001"),
            "token_hash": os.environ.get("AGENT_TOKEN_HASH", ""),
            "machine_name": socket.gethostname(),
            "version": VERSION,
            "auto_update": os.environ.get("AGENT_AUTO_UPDATE", "true").lower() == "true",
            "notifications": os.environ.get("AGENT_NOTIFICATIONS", "true").lower() == "true",
            "check_interval": int(os.environ.get("AGENT_CHECK_INTERVAL", HEARTBEAT_INTERVAL)),
            "endpoint_validate": "/api/inventario/agent/validate/",
            "endpoint_checkin": "/api/inventario/checkin/",
            "endpoint_update": "/api/inventario/agent/update/",
            "endpoint_health": "/api/inventario/health/",
            "endpoint_notifications": "/api/notifications/",
        }

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value


class RequestsSession:
    """Gerenciador de sessão HTTP com retry"""

    _session = None

    @classmethod
    def get_session(cls):
        if cls._session is None:
            cls._session = requests.Session()

            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )

            adapter = HTTPAdapter(max_retries=retry_strategy)
            cls._session.mount("http://", adapter)
            cls._session.mount("https://", adapter)

        return cls._session


class TokenValidator:
    """Validador de token de instalação"""

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def validate_with_server(server_url, token_hash, machine_name):
        try:
            url = f"{server_url}/api/inventario/agent/validate/"

            payload = {
                'token': token_hash,
                'machine_name': machine_name
            }

            session = RequestsSession.get_session()
            response = session.post(
                url,
                json=payload,
                verify=False,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                is_valid = result.get('valid', False)
                if is_valid:
                    logger.info("Token validado com sucesso")
                else:
                    logger.error(f"Token inválido: {result.get('message')}")
                return is_valid

            logger.error(f"Erro ao validar token: HTTP {response.status_code}")
            return False

        except Exception as e:
            logger.error(f"Erro ao validar token: {e}")
            return False


class NetworkMonitor:
    """Monitor de conectividade de rede"""

    def __init__(self, config):
        self.config = config
        self.is_online = False
        self.last_check = None

    def check_connectivity(self):
        try:
            url = self.config.get('server_url') + self.config.get('endpoint_health')

            session = RequestsSession.get_session()
            response = session.get(url, verify=False, timeout=5)

            self.is_online = response.status_code == 200
            self.last_check = datetime.now()

            return self.is_online

        except requests.exceptions.RequestException:
            self.is_online = False
            self.last_check = datetime.now()
            return False


class AutoUpdater:
    """Gerenciador de atualizações automáticas"""

    def __init__(self, config):
        self.config = config

    def check_for_updates(self):
        try:
            url = self.config.get('server_url') + self.config.get('endpoint_update')

            payload = {
                'current_version': self.config.get('version'),
                'machine_name': self.config.get('machine_name')
            }

            session = RequestsSession.get_session()
            response = session.post(url, json=payload, verify=False, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get('update_available'):
                    logger.info(f"Atualização disponível: {data.get('version')}")
                    return data

            return None

        except Exception as e:
            logger.error(f"Erro ao verificar atualizações: {e}")
            return None

    def download_update(self, update_info):
        if not self.config.get('auto_update'):
            logger.info("Auto-update desativado")
            return

        try:
            download_url = update_info.get('download_url')

            logger.info(f"Baixando atualização {update_info.get('version')}")

            session = RequestsSession.get_session()
            response = session.get(download_url, verify=False, timeout=30)

            if response.status_code == 200:
                current_file = os.path.abspath(__file__)
                backup_file = current_file + '.bak'

                with open(backup_file, 'wb') as f:
                    with open(current_file, 'rb') as orig:
                        f.write(orig.read())

                with open(current_file, 'wb') as f:
                    f.write(response.content)

                logger.info("Atualização aplicada com sucesso")

                time.sleep(2)
                os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception as e:
            logger.error(f"Erro ao aplicar atualização: {e}")

            current_file = os.path.abspath(__file__)
            backup_file = current_file + '.bak'

            if os.path.exists(backup_file):
                with open(backup_file, 'rb') as b:
                    with open(current_file, 'wb') as f:
                        f.write(b.read())


class PowerShellCollector:
    """Coletor de informações via PowerShell - IGUAL AO AGENT.PS1"""

    POWERSHELL_SCRIPT = r'''
    $ErrorActionPreference = "SilentlyContinue"

    function Get-SystemInfo {
        # Usuário logado
        $loggedUser = ((Get-CimInstance Win32_ComputerSystem).UserName -split '\\')[-1]

        # MAC principal
        $primaryNet = Get-CimInstance Win32_NetworkAdapterConfiguration |
                      Where-Object { $_.IPEnabled } | Select-Object -First 1
        $macAddress = $primaryNet.MACAddress

        # Slots e módulos de RAM
        $arrays         = Get-CimInstance Win32_PhysicalMemoryArray
        $totalSlots     = ($arrays | Measure-Object -Property MemoryDevices -Sum).Sum
        $modules        = Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
            [pscustomobject]@{
                bank_label     = $_.BankLabel
                device_locator = $_.DeviceLocator
                capacity_gb    = [math]::Round($_.Capacity/1GB,2)
                speed_mhz      = $_.Speed
                manufacturer   = $_.Manufacturer
                part_number    = $_.PartNumber
                serial_number  = $_.SerialNumber
            }
        }
        $populatedSlots = $modules.Count

        # Antivírus: escolhe primeiro não Defender, senão o primeiro da lista
        $avList = Get-CimInstance -Namespace "root\SecurityCenter2" -ClassName AntiVirusProduct -ErrorAction SilentlyContinue
        $av = $avList | Where-Object { $_.displayName -notmatch "Defender" } | Select-Object -First 1
        if (-not $av) { $av = $avList | Select-Object -First 1 }

        # Outras infos
        $os    = Get-CimInstance Win32_OperatingSystem
        $cs    = Get-CimInstance Win32_ComputerSystem
        $bios  = Get-CimInstance Win32_BIOS
        $upt   = (Get-Date) - $os.LastBootUpTime
        $proc  = Get-CimInstance Win32_Processor
        $disk  = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
        $net   = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object IPEnabled
        $gpu   = Get-CimInstance Win32_VideoController | Select-Object -First 1

        # TPM
        try {
            $tpm = Get-Tpm
            $tpmInfo = [pscustomobject]@{
                present          = $tpm.TpmPresent
                ready            = $tpm.TpmReady
                enabled          = $tpm.TpmEnabled
                activated        = $tpm.TpmActivated
                spec_version     = $tpm.SpecVersion
                manufacturer     = $tpm.ManufacturerIdTxt
                manufacturer_ver = $tpm.ManufacturerVersion
            }
        } catch {
            $tpmInfo = [pscustomobject]@{
                present          = $false
                ready            = $false
                enabled          = $false
                activated        = $false
                spec_version     = $null
                manufacturer     = $null
                manufacturer_ver = $null
            }
        }

        # Converter datas para timestamp JSON
        $installDateJson = $null
        if ($os.InstallDate) {
            $installDateJson = "/Date($([Math]::Floor((Get-Date $os.InstallDate).ToUniversalTime().Subtract((Get-Date '1970-01-01')).TotalMilliseconds)))/"
        }

        $lastBootJson = $null
        if ($os.LastBootUpTime) {
            $lastBootJson = "/Date($([Math]::Floor((Get-Date $os.LastBootUpTime).ToUniversalTime().Subtract((Get-Date '1970-01-01')).TotalMilliseconds)))/"
        }

        $biosReleaseJson = $null
        if ($bios.ReleaseDate) {
            $biosReleaseJson = "/Date($([Math]::Floor((Get-Date $bios.ReleaseDate).ToUniversalTime().Subtract((Get-Date '1970-01-01')).TotalMilliseconds)))/"
        }

        # Espaço em disco usado
        $diskUsedGb = [math]::Round(($disk.Size - $disk.FreeSpace)/1GB, 2)

        # IP Address
        $ipAddress = if ($primaryNet.IPAddress) { $primaryNet.IPAddress[0] } else { "127.0.0.1" }

        $result = [pscustomobject]@{
            hostname               = $env:COMPUTERNAME
            ip_address             = $ipAddress
            logged_user            = $loggedUser

            manufacturer           = $cs.Manufacturer
            model                  = $cs.Model
            serial_number          = $bios.SerialNumber
            bios_version           = $bios.SMBIOSBIOSVersion
            bios_release           = $biosReleaseJson

            os_caption             = $os.Caption
            os_architecture        = $os.OSArchitecture
            os_build               = $os.BuildNumber
            install_date           = $os.InstallDate
            last_boot              = $os.LastBootUpTime
            uptime_days            = [math]::Round($upt.TotalDays,2)

            cpu                    = $proc.Name
            ram_gb                 = [math]::Round(($cs.TotalPhysicalMemory/1GB),2)
            disk_space_gb          = [math]::Round($disk.Size/1GB,2)
            disk_free_gb           = [math]::Round($disk.FreeSpace/1GB,2)
            disk_used_gb           = $diskUsedGb

            mac_address            = $macAddress
            total_memory_slots     = $totalSlots
            populated_memory_slots = $populatedSlots
            memory_modules         = @($modules)

            network_adapters       = @($net | ForEach-Object {
                [pscustomobject]@{
                    name    = $_.Description
                    mac     = $_.MACAddress
                    ip      = ($_.IPAddress -join ",")
                    gateway = ($_.DefaultIPGateway -join ",")
                    dns     = ($_.DNSServerSearchOrder -join ",")
                    dhcp    = $_.DHCPEnabled
                }
            })

            gpu_name               = $gpu.Name
            gpu_driver             = $gpu.DriverVersion

            antivirus_name         = $av.displayName
            av_state               = if ($av.productState) { $av.productState.ToString() } else { $null }

            tpm                    = $tpmInfo
        }

        return $result | ConvertTo-Json -Depth 10 -Compress
    }

    # Executar e retornar JSON
    Get-SystemInfo
    '''

    @staticmethod
    def get_system_info():
        """Executa PowerShell e retorna informações coletadas"""
        try:
            logger.info("Coletando informações via PowerShell...")

            # Executar PowerShell
            result = subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
                 PowerShellCollector.POWERSHELL_SCRIPT],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )

            if result.returncode != 0:
                logger.error(f"PowerShell erro: {result.stderr}")
                raise Exception(f"PowerShell retornou código {result.returncode}")

            # Parse do JSON retornado
            output = result.stdout.strip()

            if not output:
                raise Exception("PowerShell não retornou dados")

            data = json.loads(output)

            logger.info(f"Dados coletados com sucesso: {data.get('hostname')}")

            return data

        except subprocess.TimeoutExpired:
            logger.error("Timeout ao executar PowerShell")
            raise Exception("Timeout na coleta de dados")

        except json.JSONDecodeError as e:
            logger.error(f"Erro ao parsear JSON do PowerShell: {e}")
            logger.error(f"Output recebido: {result.stdout}")
            raise Exception("Dados inválidos retornados pelo PowerShell")

        except Exception as e:
            logger.error(f"Erro ao coletar informações via PowerShell: {e}")
            raise

    @staticmethod
    def send_data(config, data):
        """Envia dados para o servidor - FORMATO IGUAL AO POWERSHELL"""
        try:
            url = config.get('server_url') + config.get("endpoint_checkin")

            # FORMATO IDÊNTICO AO POWERSHELL
            payload = {
                "hostname": data["hostname"],
                "ip": data.get("ip_address", ""),
                "hardware": data,
                "token": config.get("token_hash")
            }

            logger.info(f"Enviando dados para {url}")
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

            session = RequestsSession.get_session()
            response = session.post(
                url,
                json=payload,
                verify=False,
                timeout=10
            )

            if response.status_code in [200, 201]:
                logger.info("Dados enviados com sucesso")
                return True
            else:
                logger.error(f"Erro HTTP {response.status_code}: {response.text}")
                return False

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Erro de conexão: {e}")
            return False
        except requests.exceptions.Timeout:
            logger.error("Timeout na requisição")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar dados: {e}")
            return False


class NotificationManager:
    """
    Gerenciador de notificações com popup customizado (tkinter).
    """

    NOTIFICATION_CHECK_INTERVAL = 120  # segundos (2 minutos)
    NOTIFICATION_DISPLAY_DELAY = 2  # segundos entre notificações

    def __init__(self, config):
        self.config = config
        self.server_url = config.get('server_url', 'http://192.168.1.54:5001')
        self.endpoint = config.get('endpoint_notifications', '/api/notifications/')
        self.machine_name = config.get('machine_name', '')
        self.notifications_enabled = config.get('notifications', True)

        # Arquivo de histórico
        self.history_file = Path("logs/notification_history.json")
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        # Carregar histórico
        self.shown_notifications = self._load_history()

        logger.info("NotificationManager inicializado (Tkinter)")

    def _load_history(self):
        """Carrega histórico de notificações exibidas"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(str(x) for x in data.get('shown_notifications', []))
            except Exception as e:
                logger.warning(f"Erro ao carregar histórico: {e}")
        return set()

    def _save_history(self):
        """Salva histórico de notificações exibidas"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'shown_notifications': list(self.shown_notifications),
                    'last_updated': datetime.now().isoformat()
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar histórico: {e}")

    def _show_popup(self, title, message, priority):
        """Exibe popup customizado usando tkinter"""

        popup_shown = threading.Event()
        popup_closed = threading.Event()

        def _run():
            try:
                root = tk.Tk()
                root.overrideredirect(True)
                root.attributes("-topmost", True)
                logger.debug("Janela tkinter criada")

                # Cores baseadas na prioridade
                colors = {
                    "info": "#1e1e1e",
                    "warning": "#7a5c00",
                    "high": "#8a3b00",
                    "critical": "#7a0000",
                }

                bg = colors.get(priority, "#1e1e1e")

                # Dimensões e posicionamento
                width = 420
                height = 180

                screen_w = root.winfo_screenwidth()
                screen_h = root.winfo_screenheight()

                x = int((screen_w / 2) - (width / 2))
                y = int((screen_h / 2) - (height / 2))

                root.geometry(f"{width}x{height}+{x}+{y}")
                root.configure(bg=bg)

                # Frame principal
                frame = tk.Frame(root, bg=bg, padx=20, pady=16)
                frame.pack(expand=True, fill="both")

                # Título
                lbl_title = tk.Label(
                    frame,
                    text=title,
                    fg="white",
                    bg=bg,
                    font=("Segoe UI", 12, "bold"),
                    anchor="w",
                )
                lbl_title.pack(fill="x")

                # Mensagem
                lbl_msg = tk.Label(
                    frame,
                    text=message,
                    fg="#e6e6e6",
                    bg=bg,
                    font=("Segoe UI", 10),
                    wraplength=380,
                    justify="left",
                    anchor="w",
                )
                lbl_msg.pack(fill="x", pady=(10, 16))

                # Função para fechar
                def close_popup():
                    root.destroy()
                    popup_closed.set()
                    logger.info("Popup fechado pelo usuário")

                # Botão OK
                btn_ok = tk.Button(
                    frame,
                    text="OK",
                    width=10,
                    font=("Segoe UI", 10, "bold"),
                    relief="flat",
                    bg="#ffffff",
                    fg="#000000",
                    command=close_popup,
                )
                btn_ok.pack(anchor="e")

                # Auto-fechar após 10 segundos
                def auto_close():
                    if root.winfo_exists():
                        logger.info("Auto-fechando popup após 10s")
                        close_popup()

                root.after(10000, auto_close)

                # Forçar exibição
                root.update()
                root.deiconify()
                root.focus_force()

                popup_shown.set()
                logger.info("Popup exibido - evento acionado")

                # Mainloop
                root.mainloop()

                if not popup_closed.is_set():
                    popup_closed.set()

                logger.info("Mainloop do popup finalizado")

            except Exception as e:
                logger.error(f"Erro ao exibir popup: {e}", exc_info=True)
                popup_shown.set()
                popup_closed.set()

        thread = Thread(target=_run, daemon=False)
        thread.start()
        logger.debug("Thread do popup iniciada")

        success = popup_shown.wait(timeout=5.0)

        if success:
            logger.info("Popup foi exibido com sucesso")
        else:
            logger.warning("Timeout aguardando exibição do popup")

        return success, popup_closed

    def send_notification(self, title, message, priority="normal", icon_type="info"):
        """Envia notificação local usando popup tkinter"""
        if not self.notifications_enabled:
            logger.debug("Notificações desabilitadas")
            return False, None

        try:
            # Adicionar emoji ao título baseado no tipo
            icon_map = {
                'info': 'ℹ️',
                'warning': '⚠️',
                'error': '❌',
                'success': '✅',
                'alert': '🔔',
                'critical': '🚨'
            }
            icon = icon_map.get(icon_type, 'ℹ️')
            full_title = f"{icon} {title}"

            # Mapear prioridade para cores
            priority_map = {
                'low': 'info',
                'normal': 'info',
                'high': 'high',
                'critical': 'critical'
            }
            popup_priority = priority_map.get(priority, 'info')

            success, closed_event = self._show_popup(full_title, message, popup_priority)

            if success:
                logger.info(f"Notificação exibida: {title}")
            else:
                logger.warning(f"Timeout ao exibir notificação: {title}")

            return success, closed_event

        except Exception as e:
            logger.error(f"Erro ao enviar notificação: {e}")
            return False, None

    def fetch_pending_notifications(self):
        """Busca notificações pendentes do servidor via GET"""
        if not self.notifications_enabled:
            return []

        try:
            session = RequestsSession.get_session()

            url = f"{self.server_url}{self.endpoint}?machine_name={self.machine_name}&status=pending&limit=20"

            params = {
                'machine_name': self.machine_name,
                'status': 'pending',
                'limit': 20
            }

            logger.debug(f"Buscando notificações via GET: {url}")
            logger.debug(f"Params: {params}")

            response = session.get(
                url,
                verify=False,
                timeout=10
            )

            logger.debug(f"Status Code: {response.status_code}")
            logger.debug(f"Response: {response.text[:200]}")

            if response.status_code == 200:
                data = response.json()

                if data.get('success'):
                    notifications = data.get('notifications', [])
                    logger.info(f"Notificações encontradas: {len(notifications)}")
                    return notifications
                else:
                    logger.warning(f"API retornou erro: {data.get('error')}")
                    return []
            else:
                logger.warning(f"Erro HTTP {response.status_code}: {response.text}")
                return []

        except Exception as e:
            logger.error(f"Erro ao buscar notificações: {e}")
            return []

    def mark_as_read(self, notification_id):
        """Marca notificação como lida no servidor"""
        try:
            session = RequestsSession.get_session()

            url = f"{self.server_url}{self.endpoint}"
            data = {'notification_id': notification_id}

            logger.debug(f"Marcando notificação {notification_id} como lida")
            logger.debug(f"URL: {url}")

            response = session.post(
                url,
                json=data,
                verify=False,
                timeout=10
            )

            logger.debug(f"Status: {response.status_code}")
            logger.debug(f"Response: {response.text[:200]}")

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    logger.info(f"Notificação {notification_id} marcada como lida")
                    return True

            logger.warning(f"Falha ao marcar notificação {notification_id}: HTTP {response.status_code}")
            logger.debug(f"Response completo: {response.text}")
            return False

        except Exception as e:
            logger.error(f"Erro ao marcar como lida: {e}")
            return False

    def process_pending_notifications(self):
        """Processa todas as notificações pendentes"""
        if not self.notifications_enabled:
            return

        logger.info("Verificando notificações do servidor...")

        notifications = self.fetch_pending_notifications()

        if not notifications:
            logger.debug("Nenhuma notificação pendente")
            return

        for notif in notifications:
            notif_id = notif.get('id')

            if notif_id in self.shown_notifications:
                logger.debug(f"Notificação {notif_id} já foi exibida")
                continue

            title = notif.get('title', 'Notificação')
            message = notif.get('message', '')
            notif_type = notif.get('type', 'info')
            priority = notif.get('priority', 'normal')

            logger.info(f"Exibindo notificação: {title}")

            success, closed_event = self.send_notification(
                title=title,
                message=message,
                priority=priority,
                icon_type=notif_type
            )

            if success and closed_event:
                logger.info(f"Aguardando usuário fechar notificação {notif_id}...")

                popup_was_closed = closed_event.wait(timeout=15.0)

                if popup_was_closed:
                    logger.info(f"Notificação {notif_id} foi vista pelo usuário")
                else:
                    logger.warning(f"Timeout aguardando fechamento da notificação {notif_id}")

                self.shown_notifications.add(notif_id)
                self._save_history()

                self.mark_as_read(notif_id)

                time.sleep(self.NOTIFICATION_DISPLAY_DELAY)


class SystemTrayIcon:
    """Gerenciador do ícone na bandeja do sistema"""

    def __init__(self, agent):
        self.agent = agent
        self.icon = None
        self.status_online = False

    def create_icon_image(self, color="green"):
        """Cria um ícone simples colorido"""
        # Criar imagem 64x64
        image = Image.new('RGB', (64, 64), color='white')
        draw = ImageDraw.Draw(image)

        # Desenhar círculo
        color_map = {
            'green': (0, 200, 0),
            'red': (200, 0, 0),
            'yellow': (200, 200, 0),
            'gray': (128, 128, 128)
        }

        fill_color = color_map.get(color, color_map['gray'])
        draw.ellipse([8, 8, 56, 56], fill=fill_color, outline='black', width=2)

        return image

    def update_icon(self, online=False):
        """Atualiza o ícone baseado no status"""
        if self.icon:
            color = "green" if online else "red"
            self.icon.icon = self.create_icon_image(color)
            self.status_online = online

    def show_about(self, icon, item):
        """Mostra janela About"""

        def _show():
            root = tk.Tk()
            root.title("Sobre - Inventory Agent")
            root.geometry("400x300")
            root.resizable(False, False)

            frame = tk.Frame(root, padx=20, pady=20)
            frame.pack(fill="both", expand=True)

            tk.Label(frame, text="Inventory Agent", font=("Arial", 16, "bold")).pack(pady=10)
            tk.Label(frame, text=f"Versão: {VERSION}", font=("Arial", 10)).pack()
            tk.Label(frame, text=f"Máquina: {self.agent.config.get('machine_name')}",
                     font=("Arial", 9)).pack(pady=5)
            tk.Label(frame, text=f"Servidor: {self.agent.config.get('server_url')}",
                     font=("Arial", 9)).pack()

            status_text = "🟢 Online" if self.status_online else "🔴 Offline"
            tk.Label(frame, text=f"Status: {status_text}", font=("Arial", 10, "bold")).pack(pady=10)

            tk.Label(frame, text="\nAgente de inventário em execução",
                     font=("Arial", 9)).pack(pady=5)

            tk.Button(frame, text="Fechar", command=root.destroy,
                      width=10).pack(pady=20)

            root.mainloop()

        Thread(target=_show, daemon=True).start()

    def show_logs(self, icon, item):
        """Abre a pasta de logs"""
        try:
            if platform.system() == "Windows":
                os.startfile(LOG_DIR)
            else:
                subprocess.run(['xdg-open', LOG_DIR])
        except Exception as e:
            logger.error(f"Erro ao abrir logs: {e}")

    def toggle_notifications(self, icon, item):
        """Liga/desliga notificações"""
        current = self.agent.config.get('notifications')
        self.agent.config.set('notifications', not current)
        self.agent.notification_manager.notifications_enabled = not current

        status = "ativadas" if not current else "desativadas"
        logger.info(f"Notificações {status}")

    def force_sync(self, icon, item):
        """Força sincronização imediata"""

        def _sync():
            try:
                logger.info("Sincronização manual iniciada")
                data = PowerShellCollector.get_system_info()
                PowerShellCollector.send_data(self.agent.config, data)
                logger.info("Sincronização manual concluída")
            except Exception as e:
                logger.error(f"Erro na sincronização manual: {e}")

        Thread(target=_sync, daemon=True).start()

    def quit_agent(self, icon, item):
        """Encerra o agente"""
        logger.info("Encerrando agente via system tray")
        self.agent.running = False
        icon.stop()

    def setup(self):
        """Configura o ícone da bandeja"""
        menu = pystray.Menu(
            item('Sobre', self.show_about),
            item('Forçar Sincronização', self.force_sync),
            item('Ver Logs', self.show_logs),
            item('Notificações', self.toggle_notifications,
                 checked=lambda item: self.agent.config.get('notifications')),
            pystray.Menu.SEPARATOR,
            item('Sair', self.quit_agent)
        )

        self.icon = pystray.Icon(
            "inventory_agent",
            self.create_icon_image("gray"),
            f"Inventory Agent v{VERSION}",
            menu
        )

    def run(self):
        """Inicia o ícone da bandeja"""
        if self.icon:
            logger.info("System tray iniciado")
            self.icon.run()


class InventoryAgent:
    """Agente principal de inventário"""

    def __init__(self, token=None):
        self.config = AgentConfig()

        if token:
            token_hash = TokenValidator.hash_token(token)
            self.config.set('token_hash', token_hash)

            if not TokenValidator.validate_with_server(
                    self.config.get('server_url'),
                    token_hash,
                    self.config.get('machine_name')
            ):
                raise ValueError("Token inválido ou expirado")

        elif not self.config.get('token_hash'):
            raise ValueError("Token não configurado")

        self.network = NetworkMonitor(self.config)
        self.updater = AutoUpdater(self.config)
        self.notification_manager = NotificationManager(self.config)
        self.running = False
        self.last_status = None

        # System Tray
        self.tray = SystemTrayIcon(self)
        self.tray.setup()

        logger.info(f"Agente iniciado - Versão {VERSION}")
        logger.info(f"Máquina: {self.config.get('machine_name')}")
        logger.info(f"Servidor: {self.config.get('server_url')}")
        logger.info("System Tray: Ativado")

    def start(self):
        """Inicia o agente"""
        self.running = True

        # Iniciar threads de monitoramento
        threading.Thread(target=self.network_monitor_loop, daemon=True).start()
        threading.Thread(target=self.data_sender_loop, daemon=True).start()
        threading.Thread(target=self.notification_checker_loop, daemon=True).start()

        if self.config.get('auto_update'):
            threading.Thread(target=self.update_checker_loop, daemon=True).start()

        logger.info("Threads iniciadas com sucesso")

        # Iniciar system tray (bloqueia até sair)
        try:
            self.tray.run()
        except KeyboardInterrupt:
            logger.info("Agente interrompido pelo usuário")
            self.running = False

    def network_monitor_loop(self):
        """Loop de monitoramento de rede"""
        while self.running:
            is_online = self.network.check_connectivity()

            # Atualizar ícone do tray
            self.tray.update_icon(online=is_online)

            if is_online:
                if self.last_status == "offline":
                    logger.info("Conexão restaurada")
            else:
                if self.last_status != "offline":
                    logger.warning("Servidor offline")

            self.last_status = "online" if is_online else "offline"
            time.sleep(OFFLINE_CHECK_INTERVAL)

    def data_sender_loop(self):
        """Loop de envio de dados usando PowerShell para coleta"""
        while self.running:
            is_online = self.network.check_connectivity()

            if is_online:
                try:
                    data = PowerShellCollector.get_system_info()
                    PowerShellCollector.send_data(self.config, data)

                except Exception as e:
                    logger.error(f"Erro no ciclo de envio: {e}")
            else:
                logger.debug("Servidor offline, aguardando reconexão")

            time.sleep(HEARTBEAT_INTERVAL)

    def update_checker_loop(self):
        """Loop de verificação de atualizações"""
        while self.running:
            if self.network.is_online:
                try:
                    update_info = self.updater.check_for_updates()
                    if update_info:
                        self.updater.download_update(update_info)
                except Exception as e:
                    logger.error(f"Erro ao verificar atualizações: {e}")

            time.sleep(UPDATE_CHECK_INTERVAL)

    def notification_checker_loop(self):
        """Loop de verificação de notificações"""
        time.sleep(30)
        while self.running:
            if self.network.is_online:
                try:
                    self.notification_manager.process_pending_notifications()
                except Exception as e:
                    logger.error(f"Erro ao verificar notificações: {e}")
            time.sleep(NotificationManager.NOTIFICATION_CHECK_INTERVAL)


def main():
    """Função principal"""

    token = None
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith('--token='):
                token = arg.split('=', 1)[1]
                break

    try:
        agent = InventoryAgent(token=token)
        agent.start()

    except ValueError as e:
        logger.error(f"Erro de configuração: {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Agente interrompido")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()