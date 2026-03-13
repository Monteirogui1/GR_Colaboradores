"""
build.py — Build completo com .spec para cada executável
Controla hidden imports, collect_data, binaries e excludes por executável.

Uso:
    python build.py              # compila tudo
    python build.py service      # só agent_service
    python build.py tray         # só agent_tray
    python build.py installer    # só install_agent
"""

import sys
import os
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
DIST = BASE / "dist"
BUILD = BASE / "build"


def run_pyinstaller(spec_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_path)],
        cwd=BASE,
    )
    if result.returncode != 0:
        print(f"\n  ERRO ao compilar {spec_path.name}")
        sys.exit(1)
    print(f"  OK: {spec_path.stem}.exe gerado em dist/")


def write_spec(path: Path, content: str):
    path.write_text(content, encoding="utf-8")
    print(f"  Spec: {path.name}")


def _pkg_installed(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def collect_ico_datas() -> str:
    lines = []
    for ico in BASE.glob("icon_*.ico"):
        lines.append(f"    (r'{ico}', '.'),")
    return "\n".join(lines) if lines else "    # nenhum .ico encontrado"


# ─────────────────────────────────────────────────────────────────────────────
# agent_service.spec — sem UI, minimal
# ─────────────────────────────────────────────────────────────────────────────

def build_service():
    print("\n" + "="*60)
    print("  Compilando agent_service.exe")
    print("="*60)

    spec = r"""
# agent_service.spec
block_cipher = None

a = Analysis(
    [r'""" + str(BASE / "agent_service.py") + r"""'],
    pathex=[r'""" + str(BASE) + r"""'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # requests
        'requests', 'requests.adapters', 'requests.auth',
        'requests.cookies', 'requests.exceptions',
        'requests.models', 'requests.sessions', 'requests.structures',
        # urllib3
        'urllib3', 'urllib3.util', 'urllib3.util.retry',
        'urllib3.contrib', 'urllib3.packages',
        # deps do requests
        'charset_normalizer', 'charset_normalizer.md__mypyc',
        'certifi', 'idna',
        # stdlib
        'http.server', 'socketserver', 'logging.handlers',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'PIL', 'pystray', 'matplotlib', 'numpy',
        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'windows_toasts', 'win11toast',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='agent_service',
    debug=False, strip=False, upx=True,
    console=True,   # NSSM precisa capturar stdout
    runtime_tmpdir=None,
)
"""
    spec_file = BUILD / "agent_service.spec"
    spec_file.write_text(
        "# -*- mode: python ; coding: utf-8 -*-\nblock_cipher = None\n\n"
        "from PyInstaller.utils.hooks import collect_data_files\n\n"
        f"a = Analysis(\n"
        f"    [r'{BASE / 'agent_service.py'}'],\n"
        f"    pathex=[r'{BASE}'],\n"
        "    binaries=[],\n"
        "    datas=[],\n"
        "    hiddenimports=[\n"
        "        'requests', 'requests.adapters', 'requests.auth',\n"
        "        'requests.cookies', 'requests.exceptions',\n"
        "        'requests.models', 'requests.sessions', 'requests.structures',\n"
        "        'urllib3', 'urllib3.util', 'urllib3.util.retry',\n"
        "        'urllib3.contrib', 'urllib3.packages',\n"
        "        'charset_normalizer', 'charset_normalizer.md__mypyc',\n"
        "        'certifi', 'idna',\n"
        "        'http.server', 'socketserver', 'logging.handlers',\n"
        "    ],\n"
        "    hookspath=[],\n"
        "    runtime_hooks=[],\n"
        "    excludes=[\n"
        "        'tkinter', 'PIL', 'pystray', 'matplotlib', 'numpy',\n"
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',\n"
        "        'windows_toasts', 'win11toast',\n"
        "    ],\n"
        "    cipher=block_cipher,\n"
        ")\n\n"
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)\n\n"
        "exe = EXE(\n"
        "    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],\n"
        "    name='agent_service',\n"
        "    debug=False, strip=False, upx=True,\n"
        "    console=True,\n"
        "    runtime_tmpdir=None,\n"
        ")\n",
        encoding="utf-8"
    )
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# agent_tray.spec — com pystray, PIL, tkinter, notificações
# ─────────────────────────────────────────────────────────────────────────────

def build_tray():
    print("\n" + "="*60)
    print("  Compilando agent_tray.exe")
    print("="*60)

    windows_toasts = _pkg_installed("windows_toasts")
    win11toast     = _pkg_installed("win11toast")

    if windows_toasts: print("  + windows-toasts detectado")
    if win11toast:     print("  + win11toast detectado")
    if not windows_toasts and not win11toast:
        print("  ! nenhum backend nativo — só fallback tkinter")

    notif_hidden = []
    notif_datas  = []
    notif_excl   = []

    if windows_toasts:
        notif_hidden += [
            "        'windows_toasts',",
            "        'windows_toasts.toasters',",
            "        'windows_toasts.wrappers',",
            "        'windows_toasts.wrappers.types',",
            # winsdk é a dep WinRT do windows-toasts
            "        'winsdk',",
            "        'winsdk.windows.ui.notifications',",
            "        'winsdk.windows.data.xml.dom',",
            "        'winsdk.windows.foundation',",
        ]
        notif_datas.append("        *collect_data_files('windows_toasts'),")
    else:
        notif_excl.append("        'windows_toasts',")

    if win11toast:
        notif_hidden.append("        'win11toast',")
    else:
        notif_excl.append("        'win11toast',")

    ico_datas = collect_ico_datas()
    icon_path = str(BASE / "icon_info.ico") if (BASE / "icon_info.ico").exists() else "None"
    icon_val  = f"r'{icon_path}'" if icon_path != "None" else "None"

    lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# agent_tray.spec",
        "from PyInstaller.utils.hooks import collect_data_files, collect_submodules",
        "",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    [r'{BASE / 'agent_tray.py'}'],",
        f"    pathex=[r'{BASE}'],",
        "    binaries=[],",
        "    datas=[",
        ico_datas,
        "        *collect_data_files('PIL'),   # plugins Pillow",
    ] + notif_datas + [
        "    ],",
        "    hiddenimports=[",
        "        # pystray",
        "        'pystray', 'pystray._win32',",
        "        # PIL / Pillow",
        "        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',",
        "        'PIL.ImageFilter', 'PIL.PngImagePlugin', 'PIL.BmpImagePlugin',",
        "        'PIL.IcoImagePlugin', 'PIL.JpegImagePlugin', 'PIL.GifImagePlugin',",
        "        # requests + urllib3",
        "        'requests', 'requests.adapters', 'requests.auth',",
        "        'requests.cookies', 'requests.exceptions',",
        "        'requests.models', 'requests.sessions',",
        "        'urllib3', 'urllib3.util', 'urllib3.util.retry',",
        "        'charset_normalizer', 'certifi', 'idna',",
        "        # notificações",
    ] + notif_hidden + [
        "        # tkinter (fallback popup)",
        "        'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext', '_tkinter',",
        "        # stdlib dinâmico",
        "        'winreg', 'ctypes', 'ctypes.wintypes', 'logging.handlers',",
        "    ],",
        "    hookspath=[],",
        "    runtime_hooks=[],",
        "    excludes=[",
        "        'matplotlib', 'numpy', 'scipy',",
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',",
        "        'IPython', 'jupyter',",
    ] + notif_excl + [
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
        "    upx_exclude=['vcruntime140.dll'],",
        "    console=False,",  # sem console — tray app
        f"    icon={icon_val},",
        "    runtime_tmpdir=None,",
        ")",
    ]

    spec_file = BUILD / "agent_tray.spec"
    spec_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# install_agent.spec — GUI instalador, mínimo
# ─────────────────────────────────────────────────────────────────────────────

def build_installer():
    print("\n" + "="*60)
    print("  Compilando install_agent.exe")
    print("="*60)

    icon_path = str(BASE / "icon_info.ico") if (BASE / "icon_info.ico").exists() else "None"
    icon_val  = f"r'{icon_path}'" if icon_path != "None" else "None"

    content = "\n".join([
        "# -*- mode: python ; coding: utf-8 -*-",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    [r'{BASE / 'install_agent.py'}'],",
        f"    pathex=[r'{BASE}'],",
        "    binaries=[],",
        "    datas=[],",
        "    hiddenimports=[",
        "        'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext',",
        "        'tkinter.filedialog', 'tkinter.messagebox', '_tkinter',",
        "        'winreg', 'ctypes', 'ctypes.wintypes',",
        "        'hashlib', 'shutil', 'threading', 'subprocess',",
        "        'logging.handlers',",
        "    ],",
        "    hookspath=[],",
        "    runtime_hooks=[],",
        "    excludes=[",
        "        'PIL', 'pystray', 'requests', 'matplotlib', 'numpy',",
        "        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',",
        "        'windows_toasts', 'win11toast',",
        "    ],",
        "    cipher=block_cipher,",
        ")",
        "",
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)",
        "",
        "exe = EXE(",
        "    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],",
        "    name='install_agent',",
        "    debug=False, strip=False, upx=True,",
        "    console=False,",
        "    uac_admin=True,",  # solicita elevação UAC
        f"    icon={icon_val},",
        "    runtime_tmpdir=None,",
        ")",
    ])

    spec_file = BUILD / "install_agent.spec"
    spec_file.write_text(content, encoding="utf-8")
    print(f"  Spec: {spec_file.name}")
    run_pyinstaller(spec_file)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "="*60)
    print("  BUILD CONCLUÍDO")
    print("="*60)
    for exe in ["agent_service.exe", "agent_tray.exe", "install_agent.exe"]:
        path = DIST / exe
        if path.exists():
            size = f"{path.stat().st_size / 1024 / 1024:.1f} MB"
            print(f"  OK  dist/{exe}  ({size})")
        else:
            print(f"  --  dist/{exe}  (não gerado)")

    print("""
  Pacote de distribuição (copiar para ZIP):
    install_agent.exe
    agent_service.exe
    agent_tray.exe
    nssm/win64/nssm.exe
    icon_*.ico  (opcional)
""")


def main():
    targets = sys.argv[1:] or ["service", "tray", "installer"]

    print(f"Inventory Agent — Build")
    print(f"Python {sys.version.split()[0]} | Base: {BASE}")

    if not _pkg_installed("PyInstaller"):
        print("\nERRO: pip install pyinstaller")
        sys.exit(1)

    for pkg, tip in [
        ("pystray",       "pip install pystray"),
        ("PIL",           "pip install pillow"),
        ("requests",      "pip install requests"),
    ]:
        if not _pkg_installed(pkg):
            print(f"AVISO: {pkg} ausente — {tip}")

    if not (_pkg_installed("windows_toasts") or _pkg_installed("win11toast")):
        print("AVISO: nenhum backend de notificação. pip install windows-toasts")

    DIST.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)

    if "service"   in targets: build_service()
    if "tray"      in targets: build_tray()
    if "installer" in targets: build_installer()

    print_summary()


if __name__ == "__main__":
    main()