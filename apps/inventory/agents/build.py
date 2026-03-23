"""
build.py — Build completo para Inventory Agent
Compila: agent_service.exe | agent_tray.exe | install_agent_silent.exe | install_agent_service.exe

Uso:
    python build.py                     # tudo
    python build.py service             # só agent_service
    python build.py tray                # só agent_tray
    python build.py installer           # só install_agent
    python build.py installer_service   # só install_agent_service
"""

import sys
import os
import subprocess
from pathlib import Path

BASE  = Path(__file__).parent
DIST  = BASE / "dist"
BUILD = BASE / "build"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def run_pyinstaller(spec_path: Path):
    # --onefile é controlado pelo spec: sem bloco COLLECT = onefile automático.
    # O EXE recebe a.binaries + a.zipfiles + a.datas diretamente.
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_path)],
        cwd=BASE,
    )
    if result.returncode != 0:
        print(f"\n  ERRO ao compilar {spec_path.name}")
        sys.exit(1)
    print(f"  OK: {spec_path.stem}.exe gerado em dist/")


def _pkg_installed(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def collect_ico_datas() -> list[str]:
    lines = []
    for ico in BASE.glob("icon_*.ico"):
        lines.append(f"    (r'{ico}', '.'),")
    return lines or ["    # nenhum .ico encontrado"]


def _icon_val(name: str) -> str:
    p = BASE / name
    return f"r'{p}'" if p.exists() else "None"


# ─────────────────────────────────────────────────────────────────────────────
# agent_service.exe
# Roda em Session 0 (Windows Service via NSSM).
# Precisa: requests, urllib3, aiortc, av, mss, numpy, win32api/win32con,
#          ctypes, socket, http.server, logging.handlers
# NÃO precisa: tkinter, pystray, PIL, notification backends
# ─────────────────────────────────────────────────────────────────────────────

def build_service():
    print("\n" + "=" * 60)
    print("  Compilando agent_service.exe")
    print("=" * 60)

    lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# agent_service.spec — gerado por build.py",
        "from PyInstaller.utils.hooks import collect_data_files, collect_submodules",
        "",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    [r'{BASE / 'agent_service.py'}'],",
        f"    pathex=[r'{BASE}'],",
        "    binaries=[],",
        "    datas=[",
        "        # av (PyAV) precisa de DLLs de codec empacotadas como data",
        "        *collect_data_files('av'),",
        "    ],",
        "    hiddenimports=[",
        "        # ── HTTP / requests ──────────────────────────────────────",
        "        'requests',",
        "        'requests.adapters',",
        "        'requests.auth',",
        "        'requests.cookies',",
        "        'requests.exceptions',",
        "        'requests.models',",
        "        'requests.sessions',",
        "        'requests.structures',",
        "        # ── urllib3 ──────────────────────────────────────────────",
        "        'urllib3',",
        "        'urllib3.util',",
        "        'urllib3.util.retry',",
        "        'urllib3.util.ssl_',",
        "        'urllib3.contrib',",
        "        'urllib3.packages',",
        "        'urllib3.packages.six',",
        "        'urllib3.packages.six.moves',",
        "        # ── deps do requests ─────────────────────────────────────",
        "        'charset_normalizer',",
        "        'charset_normalizer.md__mypyc',",
        "        'certifi',",
        "        'idna',",
        "        # ── av / PyAV ────────────────────────────────────────────",
        "        'av',",
        "        'av.audio',",
        "        'av.video',",
        "        'av.codec',",
        "        'av.container',",
        "        'av.format',",
        "        # ── mss (captura de tela) ────────────────────────────────",
        "        'mss',",
        "        'mss.windows',",
        "        # ── numpy ────────────────────────────────────────────────",
        "        'numpy',",
        "        'numpy.core',",
        "        'numpy.core._multiarray_umath',",
        "        # ── aiortc + dependências ────────────────────────────────",
        "        'aiortc',",
        "        'aiortc.mediastreams',",
        "        'aiortc.rtcdatachannel',",
        "        'aiortc.rtcpeerconnection',",
        "        'aiortc.rtcsessiondescription',",
        "        'aiortc.rtp',",
        "        'aioice',",
        "        'aioice.ice',",
        "        'cryptography',",
        "        'cryptography.hazmat',",
        "        'cryptography.hazmat.primitives',",
        "        'cryptography.hazmat.backends',",
        "        'cryptography.hazmat.backends.openssl',",
        "        'pyee',",
        "        'pyee.base',",
        "        # ── Win32 (mouse/teclado/shell) ──────────────────────────",
        "        'win32api',",
        "        'win32con',",
        "        'win32gui',",
        "        'win32process',",
        "        'pywintypes',",
        "        # ── ctypes (SHGetKnownFolderPath, windll) ───────────────",
        "        'ctypes',",
        "        'ctypes.wintypes',",
        "        # ── stdlib dinâmico ──────────────────────────────────────",
        "        'http.server',",
        "        'socketserver',",
        "        'logging.handlers',",
        "        'ipaddress',",
        "        'uuid',",
        "        'socket',",
        "        'hashlib',",
        "        'asyncio',",
        "        'asyncio.events',",
        "        'asyncio.base_events',",
        "        'asyncio.futures',",
        "        'asyncio.queues',",
        "    ],",
        "    hookspath=[],",
        "    runtime_hooks=[],",
        "    excludes=[",
        "        'tkinter', '_tkinter',",
        "        'PIL', 'pystray',",
        "        'matplotlib', 'scipy',",
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',",
        "        'windows_toasts', 'win11toast',",
        "        'IPython', 'jupyter',",
        "    ],",
        "    cipher=block_cipher,",
        ")",
        "",
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)",
        "",
        "exe = EXE(",
        "    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],",
        "    name='agent_service',",
        "    debug=False, strip=False, upx=True,",
        "    upx_exclude=['vcruntime140.dll', '_ssl.pyd'],",
        "    console=True,   # NSSM precisa capturar stdout/stderr",
        "    runtime_tmpdir=None,",
        ")",
    ]

    spec_file = BUILD / "agent_service.spec"
    spec_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# agent_tray.exe
# Roda na sessão do usuário (autorun HKCU).
# Precisa: tudo do service + pystray, PIL, tkinter, notification.py,
#          chamados.py, ToastNotification backend (windows_toasts ou win11toast)
# ─────────────────────────────────────────────────────────────────────────────

def build_tray():
    print("\n" + "=" * 60)
    print("  Compilando agent_tray.exe")
    print("=" * 60)

    windows_toasts = _pkg_installed("windows_toasts")
    win11toast     = _pkg_installed("win11toast")

    if windows_toasts: print("  + windows-toasts detectado")
    if win11toast:     print("  + win11toast detectado")
    if not windows_toasts and not win11toast:
        print("  ! AVISO: nenhum backend nativo — notificações usarão fallback tkinter")

    notif_hidden = []
    notif_datas  = []
    notif_excl   = []

    if windows_toasts:
        notif_hidden += [
            "        # ── windows-toasts (WinRT) ──────────────────────────",
            "        'windows_toasts',",
            "        'windows_toasts.toasters',",
            "        'windows_toasts.wrappers',",
            "        'windows_toasts.wrappers.types',",
            "        'windows_toasts.wrappers.results',",
            "        # winsdk — runtime WinRT exigido pelo windows-toasts",
            "        'winsdk',",
            "        'winsdk.windows',",
            "        'winsdk.windows.ui',",
            "        'winsdk.windows.ui.notifications',",
            "        'winsdk.windows.data',",
            "        'winsdk.windows.data.xml',",
            "        'winsdk.windows.data.xml.dom',",
            "        'winsdk.windows.foundation',",
            "        'winsdk.windows.foundation.collections',",
        ]
        notif_datas.append("        *collect_data_files('windows_toasts'),")
    else:
        notif_excl.append("        'windows_toasts', 'winsdk',")

    if win11toast:
        notif_hidden += [
            "        'win11toast',",
        ]
    else:
        notif_excl.append("        'win11toast',")

    ico_datas = collect_ico_datas()
    icon_val  = _icon_val("icon_info.ico")

    # notification.py e chamados.py são módulos locais (não são pacotes instalados).
    # No onefile, pathex não é suficiente — precisam entrar em datas como scripts
    # e ser referenciados em hiddenimports para que o PyInstaller os compile junto.
    local_scripts = []
    for script in ["notification.py", "chamados.py"]:
        if (BASE / script).exists():
            local_scripts.append(f"        (r'{BASE / script}', '.'),")
        else:
            print(f"  AVISO: {script} não encontrado em {BASE}")

    lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# agent_tray.spec — gerado por build.py",
        "from PyInstaller.utils.hooks import collect_data_files, collect_submodules",
        "",
        "block_cipher = None",
        "",
        "a = Analysis(",
        # Inclui agent_tray.py + notification.py + chamados.py como scripts de entrada
        f"    [r'{BASE / 'agent_tray.py'}',",
        f"     r'{BASE / 'notification.py'}',",
        f"     r'{BASE / 'chamados.py'}'],",
        f"    pathex=[r'{BASE}'],",
        "    binaries=[],",
        "    datas=[",
        *ico_datas,
        *local_scripts,                                    # copia .py locais para raiz do bundle
        "        *collect_data_files('PIL'),           # plugins Pillow",
        "        *collect_data_files('av'),             # DLLs PyAV",
        *notif_datas,
        "    ],",
        "    hiddenimports=[",
        "        # ── módulos locais (notification.py + chamados.py) ──────────",
        "        'notification',",
        "        'chamados',",
        "        # ── pystray ─────────────────────────────────────────────",
        "        'pystray',",
        "        'pystray._win32',",
        "        # ── PIL / Pillow ─────────────────────────────────────────",
        "        'PIL',",
        "        'PIL.Image',",
        "        'PIL.ImageDraw',",
        "        'PIL.ImageFont',",
        "        'PIL.ImageFilter',",
        "        'PIL.PngImagePlugin',",
        "        'PIL.BmpImagePlugin',",
        "        'PIL.IcoImagePlugin',",
        "        'PIL.JpegImagePlugin',",
        "        'PIL.GifImagePlugin',",
        "        # ── tkinter (fallback popup + chamados UI) ───────────────",
        "        'tkinter',",
        "        'tkinter.ttk',",
        "        'tkinter.font',",
        "        'tkinter.scrolledtext',",
        "        'tkinter.messagebox',",
        "        'tkinter.filedialog',",
        "        '_tkinter',",
        "        # ── requests + urllib3 ───────────────────────────────────",
        "        'requests',",
        "        'requests.adapters',",
        "        'requests.auth',",
        "        'requests.cookies',",
        "        'requests.exceptions',",
        "        'requests.models',",
        "        'requests.sessions',",
        "        'requests.structures',",
        "        'urllib3',",
        "        'urllib3.util',",
        "        'urllib3.util.retry',",
        "        'urllib3.util.ssl_',",
        "        'charset_normalizer',",
        "        'charset_normalizer.md__mypyc',",
        "        'certifi',",
        "        'idna',",
        "        # ── av / PyAV ────────────────────────────────────────────",
        "        'av',",
        "        'av.audio',",
        "        'av.video',",
        "        'av.codec',",
        "        'av.container',",
        "        'av.format',",
        "        # ── mss ──────────────────────────────────────────────────",
        "        'mss',",
        "        'mss.windows',",
        "        # ── numpy ────────────────────────────────────────────────",
        "        'numpy',",
        "        'numpy.core',",
        "        'numpy.core._multiarray_umath',",
        "        # ── aiortc ───────────────────────────────────────────────",
        "        'aiortc',",
        "        'aiortc.mediastreams',",
        "        'aiortc.rtcdatachannel',",
        "        'aiortc.rtcpeerconnection',",
        "        'aiortc.rtcsessiondescription',",
        "        'aiortc.rtp',",
        "        'aioice',",
        "        'aioice.ice',",
        "        'cryptography',",
        "        'cryptography.hazmat',",
        "        'cryptography.hazmat.primitives',",
        "        'cryptography.hazmat.backends',",
        "        'cryptography.hazmat.backends.openssl',",
        "        'pyee',",
        "        'pyee.base',",
        "        # ── Win32 ────────────────────────────────────────────────",
        "        'win32api',",
        "        'win32con',",
        "        'win32gui',",
        "        'win32process',",
        "        'pywintypes',",
        "        # ── ctypes ───────────────────────────────────────────────",
        "        'ctypes',",
        "        'ctypes.wintypes',",
        *notif_hidden,
        "        # ── stdlib ───────────────────────────────────────────────",
        "        'http.server',",
        "        'socketserver',",
        "        'logging.handlers',",
        "        'winreg',",
        "        'ipaddress',",
        "        'uuid',",
        "        'hashlib',",
        "        'asyncio',",
        "        'asyncio.events',",
        "        'asyncio.base_events',",
        "        'asyncio.futures',",
        "        'asyncio.queues',",
        "    ],",
        "    hookspath=[],",
        "    runtime_hooks=[],",
        "    excludes=[",
        "        'matplotlib', 'scipy',",
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',",
        "        'IPython', 'jupyter',",
        *notif_excl,
        "    ],",
        "    cipher=block_cipher,",
        ")",
        "",
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)",
        "",
        "exe = EXE(",
        "    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],",
        "    name='agent_tray',",
        "    debug=False, strip=False, upx=True,",
        "    upx_exclude=['vcruntime140.dll', '_ssl.pyd', '_tkinter.pyd'],",
        "    console=False,   # tray app — sem janela de console",
        f"    icon={icon_val},",
        "    runtime_tmpdir=None,",
        ")",
    ]

    spec_file = BUILD / "agent_tray.spec"
    spec_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# install_agent_silent.exe   (instalador simples — sem NSSM logic)
# Precisa: tkinter, hashlib, winreg, subprocess, shutil, pathlib
# NÃO precisa: requests, aiortc, av, mss, pystray, PIL
# ─────────────────────────────────────────────────────────────────────────────

def build_installer():
    print("\n" + "=" * 60)
    print("  Compilando install_agent_silent.exe")
    print("=" * 60)

    icon_val = _icon_val("icon_info.ico")

    lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# install_agent_silent.spec — gerado por build.py",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    [r'{BASE / 'install_agent_silent.py'}'],",
        f"    pathex=[r'{BASE}'],",
        "    binaries=[",
        "        # se NSSM for embutido no pacote, inclua aqui:",
        "        (r'C:\Apps\TI-Agent\nssm.exe', '.'),",
        "    ],",
        "    datas=[],",
        "    hiddenimports=[",
        "        # ── tkinter ──────────────────────────────────────────────",
        "        'tkinter',",
        "        'tkinter.ttk',",
        "        'tkinter.scrolledtext',",
        "        'tkinter.filedialog',",
        "        'tkinter.messagebox',",
        "        'tkinter.font',",
        "        '_tkinter',",
        "        # ── Win32 / registro ─────────────────────────────────────",
        "        'winreg',",
        "        'ctypes',",
        "        'ctypes.wintypes',",
        "        # ── stdlib ───────────────────────────────────────────────",
        "        'hashlib',",
        "        'shutil',",
        "        'threading',",
        "        'subprocess',",
        "        'pathlib',",
        "        'logging.handlers',",
        "    ],",
        "    hookspath=[],",
        "    runtime_hooks=[],",
        "    excludes=[",
        "        'PIL', 'pystray',",
        "        'requests', 'urllib3',",
        "        'matplotlib', 'numpy', 'scipy',",
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',",
        "        'windows_toasts', 'win11toast', 'winsdk',",
        "        'aiortc', 'av', 'mss',",
        "        'IPython', 'jupyter',",
        "    ],",
        "    cipher=block_cipher,",
        ")",
        "",
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)",
        "",
        "exe = EXE(",
        "    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],",
        "    name='install_agent_silent',",
        "    debug=False, strip=False, upx=True,",
        "    console=False,",
        "    uac_admin=True,   # solicita elevação UAC",
        f"    icon={icon_val},",
        "    runtime_tmpdir=None,",
        ")",
    ]

    spec_file = BUILD / "install_agent_silent.spec"
    spec_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# install_agent_service.exe   (instalador com NSSM — UI mais completa)
# Precisa: mesma base do install_agent + subprocess avançado
# ─────────────────────────────────────────────────────────────────────────────

def build_installer_service():
    print("\n" + "=" * 60)
    print("  Compilando install_agent_service.exe")
    print("=" * 60)

    icon_val = _icon_val("icon_info.ico")

    lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# install_agent_service.spec — gerado por build.py",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    [r'{BASE / 'install_agent_service.py'}'],",
        f"    pathex=[r'{BASE}'],",
        "    binaries=[",
        "        # se NSSM for embutido no pacote, inclua aqui:",
        "        (r'C:\Apps\TI-Agent\nssm.exe', '.'),",
        "    ],",
        "    datas=[],",
        "    hiddenimports=[",
        "        # ── tkinter ──────────────────────────────────────────────",
        "        'tkinter',",
        "        'tkinter.ttk',",
        "        'tkinter.scrolledtext',",
        "        'tkinter.filedialog',",
        "        'tkinter.messagebox',",
        "        'tkinter.font',",
        "        '_tkinter',",
        "        # ── Win32 / COM (atalho .lnk via win32com) ───────────────",
        "        'winreg',",
        "        'win32com',",
        "        'win32com.client',",
        "        'win32com.shell',",
        "        'win32com.shell.shell',",
        "        'pywintypes',",
        "        # ── ctypes ───────────────────────────────────────────────",
        "        'ctypes',",
        "        'ctypes.wintypes',",
        "        # ── stdlib ───────────────────────────────────────────────",
        "        'hashlib',",
        "        'shutil',",
        "        'threading',",
        "        'subprocess',",
        "        'pathlib',",
        "        'logging.handlers',",
        "    ],",
        "    hookspath=[],",
        "    runtime_hooks=[],",
        "    excludes=[",
        "        'PIL', 'pystray',",
        "        'requests', 'urllib3',",
        "        'matplotlib', 'numpy', 'scipy',",
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',",
        "        'windows_toasts', 'win11toast', 'winsdk',",
        "        'aiortc', 'av', 'mss',",
        "        'IPython', 'jupyter',",
        "    ],",
        "    cipher=block_cipher,",
        ")",
        "",
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)",
        "",
        "exe = EXE(",
        "    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],",
        "    name='install_agent_service',",
        "    debug=False, strip=False, upx=True,",
        "    console=False,",
        "    uac_admin=True,   # NSSM exige privilégios de administrador",
        f"    icon={icon_val},",
        "    runtime_tmpdir=None,",
        ")",
    ]

    spec_file = BUILD / "install_agent_service.spec"
    spec_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# Resumo
# ─────────────────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "=" * 60)
    print("  BUILD CONCLUÍDO")
    print("=" * 60)
    exes = [
        "agent_service.exe",
        "agent_tray.exe",
        "install_agent.exe",
        "install_agent_service.exe",
    ]
    for exe in exes:
        path = DIST / exe
        if path.exists():
            size = f"{path.stat().st_size / 1024 / 1024:.1f} MB"
            print(f"  OK   dist/{exe}  ({size})")
        else:
            print(f"  --   dist/{exe}  (não gerado)")

    print("""
  Pacote de distribuição (ZIP final):
    install_agent_service.exe
    agent_service.exe
    agent_tray.exe
    nssm/win64/nssm.exe
    icon_*.ico  (opcional)
""")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    targets = sys.argv[1:] or ["service", "tray", "installer", "installer_service"]

    print(f"Inventory Agent — Build")
    print(f"Python {sys.version.split()[0]} | Base: {BASE}")

    # Checagem de dependências obrigatórias
    if not _pkg_installed("PyInstaller"):
        print("\nERRO: pip install pyinstaller")
        sys.exit(1)

    required = [
        ("pystray",   "pip install pystray"),
        ("PIL",       "pip install pillow"),
        ("requests",  "pip install requests"),
        ("av",        "pip install av"),
        ("mss",       "pip install mss"),
        ("numpy",     "pip install numpy"),
        ("aiortc",    "pip install aiortc"),
        ("win32api",  "pip install pywin32"),
    ]
    for pkg, tip in required:
        if not _pkg_installed(pkg):
            print(f"  AVISO: {pkg} não instalado — {tip}")

    if not (_pkg_installed("windows_toasts") or _pkg_installed("win11toast")):
        print("  AVISO: nenhum backend de notificação nativo.")
        print("         pip install windows-toasts   (recomendado para Win10/11)")

    DIST.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)

    if "service"            in targets: build_service()
    if "tray"               in targets: build_tray()
    if "installer"          in targets: build_installer()
    if "installer_service"  in targets: build_installer_service()

    print_summary()


if __name__ == "__main__":
    main()