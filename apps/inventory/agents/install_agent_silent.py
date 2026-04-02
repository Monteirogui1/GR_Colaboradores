"""
install_agent_silent.py — Instalador 100% Silencioso
══════════════════════════════════════════════════════
  • SEM janela  • SEM prompt  • SEM interação do usuário
  • Token fixo embutido no código
  • Instala agent_service.exe como Serviço Windows (NSSM)
  • Registra agent_tray.exe em HKLM\\Run → todos os usuários
  • Cria atalho "Chamados.lnk" no Desktop Público (todos os usuários)
  • Grava log em: C:\\Windows\\Temp\\install_agent_silent.log

  ┌─────────────────────────────────────────────────────┐
  │  EDITE AS CONSTANTES ABAIXO ANTES DE DISTRIBUIR     │
  └─────────────────────────────────────────────────────┘
"""

import os
import sys
import shutil
import hashlib
import logging
import subprocess
import ctypes
import ctypes.wintypes
import winreg
from pathlib import Path

# ═══════════════════════════════════════════════════════
#    CONFIGURAÇÕES — EDITE ANTES DE DISTRIBUIR
# ═══════════════════════════════════════════════════════

EMBEDDED_TOKEN   = ""
SERVER_URL       = "http://192.168.100.247:5002"
INSTALL_DIR      = r"C:\Program Files\InventoryAgent"
AGENT_NAME       = "Inventory Agent"
AGENT_VERSION    = "3.3.1"
AUTO_UPDATE      = True
NOTIFICATIONS    = True
INSTALL_TRAY     = True
DESKTOP_SHORTCUT = True
IPC_PORT         = 7070

# ═══════════════════════════════════════════════════════
#  ▲▲▲  FIM DAS CONFIGURAÇÕES  ▲▲▲
# ═══════════════════════════════════════════════════════

SERVICE_NAME = "InventoryAgent"

# ── HKLM → executa para TODOS os usuários ao logar ──────────────────────────
# HKCU só registraria para o usuário atual — com UAC elevado seria o admin,
# não os usuários AD. HKLM resolve para qualquer usuário que logar.
TRAY_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
TRAY_REG_VAL = "InventoryAgentTray"

LOG_FILE = r"C:\Windows\Temp\install_agent_silent.log"


# ───────────────────────────────────────────────────────
# Logger
# ───────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
log = logging.getLogger("silent_installer")


# ───────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────

def _installer_dir() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent


def _find_nssm(base: Path) -> str:
    candidates = [
        base / "nssm" / "win64" / "nssm.exe",
        base / "nssm.exe",
        Path(__file__).parent / "nssm" / "win64" / "nssm.exe",
        Path(__file__).parent / "nssm.exe",
    ]
    for p in candidates:
        if p.exists():
            log.debug(f"NSSM encontrado: {p}")
            return str(p)
    raise FileNotFoundError(
        "nssm.exe não encontrado. Coloque-o em nssm/win64/ ou na mesma pasta do instalador."
    )


def _copy_agent(src_dir: Path, dst_dir: Path, name: str) -> Path:
    for src in [src_dir / f"{name}.exe", Path(__file__).parent / f"{name}.exe"]:
        if src.exists():
            dst = dst_dir / src.name
            shutil.copy2(src, dst)
            log.info(f"Copiado: {src.name} → {dst}")
            return dst
    raise FileNotFoundError(f"{name}.exe não encontrado.")


def _run(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _remove_service(nssm: str):
    log.info("Removendo serviço anterior (se existir)…")
    _run([nssm, "stop",   SERVICE_NAME], timeout=15)
    _run([nssm, "remove", SERVICE_NAME, "confirm"], timeout=15)


def _install_service(nssm: str, svc_exe: Path, token: str):
    log.info(f"Instalando serviço: {SERVICE_NAME}")
    r = _run([nssm, "install", SERVICE_NAME, str(svc_exe), f"--token={token}"])
    if r.returncode != 0:
        raise RuntimeError(f"Falha ao instalar serviço: {r.stderr.strip()}")
    for args in [
        ["set", SERVICE_NAME, "DisplayName",  AGENT_NAME],
        ["set", SERVICE_NAME, "Description",
         "Agente de Inventário — coleta hardware e envia ao servidor"],
        ["set", SERVICE_NAME, "Start",        "SERVICE_AUTO_START"],
        ["set", SERVICE_NAME, "AppNoConsole", "1"],
    ]:
        _run([nssm] + args)
    log.info(f"Serviço '{SERVICE_NAME}' registrado.")


def _set_service_envs(nssm: str, token_hash: str):
    log.info("Configurando variáveis de ambiente…")
    envs = {
        "AGENT_SERVER_URL":    SERVER_URL,
        "AGENT_TOKEN_HASH":    token_hash,
        "AGENT_AUTO_UPDATE":   "true" if AUTO_UPDATE   else "false",
        "AGENT_NOTIFICATIONS": "true" if NOTIFICATIONS else "false",
    }
    for k, v in envs.items():
        _run([nssm, "set", SERVICE_NAME, "AppEnvironmentExtra", f"{k}={v}"])
    log.info("Variáveis configuradas.")


def _register_tray_autorun(tray_exe: Path):
    """
    Registra agent_tray.exe em HKLM\\...\\Run.

    HKLM (não HKCU) garante que o tray sobe para TODOS os usuários
    que logarem nesta máquina, incluindo usuários de domínio AD que
    nunca logaram antes.

    Requer que o processo esteja elevado (admin) — garantido pelo
    _require_admin() chamado no início.
    """
    value = str(tray_exe)
    log.info(f"Registrando autorun em HKLM\\Run: {value}")

    # Método 1: winreg direto (privilegiado)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            TRAY_REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, TRAY_REG_VAL, 0, winreg.REG_SZ, value)
        log.info("Autorun registrado via winreg HKLM.")
        return
    except Exception as e:
        log.warning(f"winreg HKLM falhou: {e} — tentando reg.exe")

    # Método 2: reg.exe (fallback)
    r = _run([
        "reg", "add",
        rf"HKLM\{TRAY_REG_KEY}",
        "/v", TRAY_REG_VAL,
        "/t", "REG_SZ",
        "/d", value,
        "/f",
    ], timeout=15)

    if r.returncode == 0:
        log.info("Autorun registrado via reg.exe HKLM.")
    else:
        log.error(f"Falha ao registrar autorun: {r.stderr.strip()}")
        raise RuntimeError("Não foi possível registrar o autorun em HKLM\\Run.")


def _get_public_desktop() -> Path:
    """
    Retorna C:\\Users\\Public\\Desktop — visível para todos os usuários.
    """
    # Via variável de ambiente PUBLIC
    public = os.environ.get("PUBLIC", r"C:\Users\Public")
    desktop = Path(public) / "Desktop"
    if desktop.exists():
        return desktop

    # Fallback via CSIDL_COMMON_DESKTOPDIRECTORY (0x0019)
    try:
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0019, None, 0, buf)
        path = Path(buf.value)
        if path.exists():
            return path
    except Exception:
        pass

    return Path(r"C:\Users\Public\Desktop")


def _create_desktop_shortcut(tray_exe: Path):
    """
    Cria Chamados.lnk no Desktop Público — visível para todos os usuários.
    win32com → PowerShell (fallback).
    """
    desktop       = _get_public_desktop()
    shortcut_path = desktop / "Chamados.lnk"
    log.info(f"Criando atalho em: {shortcut_path}")

    # Método 1: win32com / pythoncom
    try:
        import pythoncom
        from win32com.shell import shell as w32shell

        pythoncom.CoInitialize()
        lnk = pythoncom.CoCreateInstance(
            w32shell.CLSID_ShellLink, None,
            pythoncom.CLSCTX_INPROC_SERVER, w32shell.IID_IShellLink,
        )
        lnk.SetPath(str(tray_exe))
        lnk.SetArguments("--chamados")
        lnk.SetDescription("Abrir painel de Chamados")
        lnk.SetWorkingDirectory(str(tray_exe.parent))
        lnk.SetIconLocation(str(tray_exe), 0)
        lnk.QueryInterface(pythoncom.IID_IPersistFile).Save(str(shortcut_path), 0)
        pythoncom.CoUninitialize()
        log.info("Atalho criado via win32com.")
        return

    except ImportError:
        pass  # pywin32 não disponível
    except Exception as e:
        log.debug(f"win32com: {e}")

    # Método 2: PowerShell WScript.Shell
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
    r = _run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps],
        timeout=15,
    )
    if r.returncode == 0:
        log.info("Atalho criado via PowerShell.")
    else:
        log.warning(f"Atalho não criado: {r.stderr.strip()}")


def _require_admin():
    """Re-executa como Administrador de forma invisível se necessário."""
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            exe    = sys.executable
            script = str(Path(__file__).resolve()) if not getattr(sys, "frozen", False) else ""
            params = f'"{script}"' if script else ""
            # SW_HIDE = 0
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 0)
            sys.exit(0)
    except Exception:
        pass


# ───────────────────────────────────────────────────────
# Instalação principal
# ───────────────────────────────────────────────────────

def install():
    log.info("=" * 56)
    log.info(f"  {AGENT_NAME} v{AGENT_VERSION} — Instalador Silencioso")
    log.info("=" * 56)

    token      = EMBEDDED_TOKEN.strip()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    inst_dir   = Path(INSTALL_DIR)
    base_dir   = _installer_dir()

    # 1. Criar diretório
    log.info(f"Criando diretório: {inst_dir}")
    inst_dir.mkdir(parents=True, exist_ok=True)

    # 2. NSSM
    nssm = _find_nssm(base_dir)

    # 3. agent_service.exe
    svc_dst = _copy_agent(base_dir, inst_dir, "agent_service")

    # 4. agent_tray.exe
    tray_dst = None
    if INSTALL_TRAY:
        try:
            tray_dst = _copy_agent(base_dir, inst_dir, "agent_tray")
        except FileNotFoundError as e:
            log.warning(str(e))

    # 5. Remover serviço anterior
    _remove_service(nssm)

    # 6. Instalar serviço
    _install_service(nssm, svc_dst, token)

    # 7. Variáveis de ambiente
    _set_service_envs(nssm, token_hash)

    # 8. Autorun HKLM — todos os usuários
    if tray_dst and INSTALL_TRAY:
        _register_tray_autorun(tray_dst)

    # 9. Atalho no Desktop Público — todos os usuários
    # if tray_dst and DESKTOP_SHORTCUT:
    #     _create_desktop_shortcut(tray_dst)

    # 10. Iniciar serviço
    log.info("Iniciando serviço…")
    r = _run([nssm, "start", SERVICE_NAME], timeout=30)
    if r.returncode == 0:
        log.info("agent_service iniciado com sucesso.")
    else:
        log.warning(f"Serviço instalado mas não iniciou: {r.stderr.strip()}")

    # 11. Iniciar Tray App imediatamente para o usuário atual
    if tray_dst and INSTALL_TRAY:
        subprocess.Popen([str(tray_dst)],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        log.info("agent_tray iniciado.")

    log.info("=" * 56)
    log.info("  INSTALAÇÃO CONCLUÍDA COM SUCESSO!")
    log.info(f"  Serviço:   {SERVICE_NAME}")
    log.info(f"  Autorun:   HKLM\\{TRAY_REG_KEY}\\{TRAY_REG_VAL}")
    log.info(f"  Desktop:   {_get_public_desktop()}\\Chamados.lnk")
    log.info(f"  Diretório: {inst_dir}")
    log.info(f"  IPC:       127.0.0.1:{IPC_PORT}")
    log.info(f"  Log:       {LOG_FILE}")
    log.info("=" * 56)


# ───────────────────────────────────────────────────────
# Entry point
# ───────────────────────────────────────────────────────

if __name__ == "__main__":
    _require_admin()
    try:
        install()
    except Exception as exc:
        log.exception(f"ERRO FATAL: {exc}")
        sys.exit(1)
