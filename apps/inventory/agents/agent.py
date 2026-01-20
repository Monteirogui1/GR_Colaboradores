import requests
import socket
import time
import os
import threading
import logging
import colorlog
import psutil
import wmi
from win10toast import ToastNotifier
import win32serviceutil
import win32service
import win32event
import getpass
import platform
import subprocess

# ---- CONFIG ----
API_BASE = "http://192.168.1.54:5001/api"
HOSTNAME = socket.gethostname()
CHECKIN_INTERVAL = 300  # 5 minutos
LOG_PATH = "C:\\Apps\\TI-Agent\\ti_agent.log"
AGENT_PATH = "C:\\Apps\\TI-Agent\\ti_agent.py"
CURRENT_VERSION = "2.2"  # Atualize conforme necessário

notifier = ToastNotifier()

# ---- SETUP LOGGING ----
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
handler = colorlog.FileHandler(LOG_PATH, encoding='utf-8')
formatter = colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s %(levelname)s:%(name)s: %(message)s')
handler.setFormatter(formatter)
logger = colorlog.getLogger('TI-Agent')
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def collect_info():
    info = {}
    try:
        c = wmi.WMI()

        # Informações do sistema
        os_info = c.Win32_OperatingSystem()[0]
        bios = c.Win32_BIOS()[0]
        cs = c.Win32_ComputerSystem()[0]
        cpu = c.Win32_Processor()[0]
        gpu = c.Win32_VideoController()[0]

        # Host e dados básicos
        info['hostname'] = platform.node()
        info['manufacturer'] = cs.Manufacturer
        info['model'] = cs.Model
        info['serial_number'] = bios.SerialNumber
        info['bios_version'] = bios.SMBIOSBIOSVersion
        info['bios_release'] = bios.ReleaseDate

        # Sistema operacional
        info['os_caption'] = os_info.Caption
        info['os_architecture'] = os_info.OSArchitecture
        info['os_build'] = os_info.BuildNumber
        info['install_date'] = os_info.InstallDate
        info['last_boot'] = os_info.LastBootUpTime
        info['uptime_days'] = round((time.time() - psutil.boot_time()) / 86400, 2)

        # CPU e RAM
        info['cpu'] = cpu.Name
        info['ram_gb'] = round(float(cs.TotalPhysicalMemory) / (1024 ** 3), 2)

        # MEMÓRIA: slots e módulos
        mem_arrays = c.Win32_PhysicalMemoryArray()
        total_slots = sum(a.MemoryDevices for a in mem_arrays) if mem_arrays else None
        modules = []
        for m in c.Win32_PhysicalMemory():
            modules.append({
                "bank_label": m.BankLabel,
                "capacity_gb": round(float(m.Capacity) / (1024 ** 3), 2),
                "speed_mhz": m.Speed,
                "manufacturer": m.Manufacturer,
                "part_number": m.PartNumber,
                "serial_number": m.SerialNumber
            })
        info['total_memory_slots'] = total_slots
        info['populated_memory_slots'] = len(modules)
        info['memory_modules'] = modules

        # Disco: soma todos os drives lógicos do tipo 3
        disks = c.Win32_LogicalDisk(DriveType=3)
        total_space = sum(float(d.Size) for d in disks if d.Size) / (1024 ** 3)
        free_space = sum(float(d.FreeSpace) for d in disks if d.FreeSpace) / (1024 ** 3)
        info['disk_space_gb'] = round(total_space, 2)
        info['disk_free_gb'] = round(free_space, 2)

        # GPU
        info['gpu_name'] = gpu.Name
        info['gpu_driver'] = gpu.DriverVersion

        # ANTIVÍRUS via WMI SecurityCenter2
        try:
            sec = wmi.WMI(namespace=r"root\SecurityCenter2")
            avprods = sec.AntiVirusProduct()
            # escolhe primeiro não Defender
            av = next((a for a in avprods if 'defender' not in a.displayName.lower()), avprods[0]) if avprods else None
            info['antivirus_name'] = av.displayName if av else ""
            info['av_state'] = getattr(av, 'productState', "")
        except Exception:
            info['antivirus_name'] = ""
            info['av_state'] = ""

        # Adaptadores de rede
        net = []
        for iface in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
            net.append({
                "description": iface.Description,
                "mac": iface.MACAddress,
                "ip": iface.IPAddress[0] if iface.IPAddress else "",
                "gateway": iface.DefaultIPGateway[0] if iface.DefaultIPGateway else "",
                "dns": iface.DNSServerSearchOrder or [],
                "dhcp": iface.DHCPEnabled
            })
        info['network_adapters'] = net

        # Usuários logados
        try:
            users = [u.UserName for u in c.Win32_ComputerSystem()]
            info['logged_users'] = users
        except:
            info['logged_users'] = [getpass.getuser()]

        # Impressoras
        pris = []
        for pr in c.Win32_Printer():
            pris.append({
                "name": pr.Name,
                "default": pr.Default,
                "status": pr.Status
            })
        info['printers'] = pris

        # Processos
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'memory_info']):
            try:
                procs.append(p.info)
            except:
                pass
        info['processes'] = procs

        # Software instalado
        sw = []
        for s in c.Win32_Product():
            sw.append({
                "name": s.Name,
                "version": s.Version,
                "vendor": s.Vendor
            })
        info['installed_software'] = sw

        # Patches
        patches = []
        for p in c.Win32_QuickFixEngineering():
            patches.append({
                "id": p.HotFixID,
                "desc": p.Description,
                "installed_on": p.InstalledOn
            })
        info['patches'] = patches

        # Serviços críticos
        services_to_check = ['wuauserv', 'WinDefend', 'bits']
        svc_status = {}
        for s in services_to_check:
            try:
                svc = psutil.win_service_get(s)
                svc_status[s] = svc.status()
            except:
                svc_status[s] = "not found"
        info['critical_services'] = svc_status

        # Bitlocker
        try:
            out = subprocess.check_output(
                ['manage-bde', '-status', 'C:'], shell=True,
                universal_newlines=True, stderr=subprocess.DEVNULL)
            info['bitlocker'] = out
        except:
            info['bitlocker'] = "unavailable"

        # Eventos recentes
        try:
            import win32evtlog
            h = win32evtlog.OpenEventLog(None, "System")
            flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
            evts = win32evtlog.ReadEventLog(h, flags, 0)
            logs = []
            for i, ev in enumerate(evts):
                if i >= 10: break
                logs.append({
                    "event_id": ev.EventID,
                    "source": ev.SourceName,
                    "category": ev.EventCategory,
                    "time": str(ev.TimeGenerated),
                    "message": ev.StringInserts
                })
            info['recent_events'] = logs
        except:
            info['recent_events'] = []

        info['agent_version'] = CURRENT_VERSION

    except Exception as e:
        info['collect_error'] = str(e)

    return info

def send_checkin():
    info = collect_info()
    payload = {
        "hostname": HOSTNAME,
        "ip": info.get("network_adapters", [{}])[0].get("ip", ""),
        "hardware": info
    }
    try:
        resp = requests.post(f"{API_BASE}/checkin/", json=payload, timeout=15)
        logger.info(f"Checkin enviado: {resp.status_code}")
    except Exception as e:
        logger.error("Erro no checkin: %s", e)

def fetch_notifications():
    try:
        resp = requests.get(f"{API_BASE}/notifications/?host={HOSTNAME}", timeout=10)
        if resp.ok:
            for n in resp.json():
                notifier.show_toast(n.get("title"), n.get("message"), duration=8, threaded=True)
                logger.info(f"Notificação recebida: {n.get('title')}")
    except Exception as e:
        logger.error("Erro notificações: %s", e)

def update_blocked_sites():
    try:
        resp = requests.get(f"{API_BASE}/checkin/?host={HOSTNAME}", timeout=10)
        if resp.ok:
            blocked = resp.json()
            hosts_file = r"C:\Windows\System32\drivers\etc\hosts"
            with open(hosts_file, "r", encoding='utf-8') as f:
                lines = f.readlines()
            start = "# BLOQUEADOS PELO TI\n"
            end = "# FIM BLOQUEIO\n"
            in_block = False
            filtered = []
            for line in lines:
                if line == start:
                    in_block = True
                if not in_block:
                    filtered.append(line)
                if line == end:
                    in_block = False
            if blocked:
                filtered.append(start)
                for site in blocked:
                    filtered.append(f"127.0.0.1 {site}\n")
                filtered.append(end)
            with open(hosts_file, "w", encoding='utf-8') as f:
                f.writelines(filtered)
            logger.info(f"Arquivo hosts atualizado ({len(blocked)} sites)")
    except Exception as e:
        logger.error("Erro no bloqueio de sites: %s", e)

def update_agent():
    # Ponto para implementar auto-update se necessário
    pass

def main_loop():
    while True:
        send_checkin()
        update_blocked_sites()
        fetch_notifications()
        update_agent()
        time.sleep(CHECKIN_INTERVAL)

class TIAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "TIAgent"
    _svc_display_name_ = "TI-Agent Python"
    _svc_description_ = "Agente Python para gestão de TI, inventário e notificações"

    def __init__(self, args):
        super().__init__(args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.worker = threading.Thread(target=main_loop, daemon=True)

    def SvcDoRun(self):
        logger.info("Serviço iniciado")
        self.worker.start()
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

    def SvcStop(self):
        logger.info("Serviço finalizado")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1:
        main_loop()
    else:
        win32serviceutil.HandleCommandLine(TIAgentService)
