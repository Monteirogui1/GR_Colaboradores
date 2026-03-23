# -*- mode: python ; coding: utf-8 -*-
# agent_tray.spec — gerado por build.py
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

a = Analysis(
    [r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\agent_tray.py',
     r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\notification.py',
     r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\chamados.py'],
    pathex=[r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents'],
    binaries=[],
    datas=[
    # nenhum .ico encontrado
        (r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\notification.py', '.'),
        (r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\chamados.py', '.'),
        *collect_data_files('PIL'),           # plugins Pillow
        *collect_data_files('av'),             # DLLs PyAV
        *collect_data_files('windows_toasts'),
    ],
    hiddenimports=[
        # ── módulos locais (notification.py + chamados.py) ──────────
        'notification',
        'chamados',
        # ── pystray ─────────────────────────────────────────────
        'pystray',
        'pystray._win32',
        # ── PIL / Pillow ─────────────────────────────────────────
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageFilter',
        'PIL.PngImagePlugin',
        'PIL.BmpImagePlugin',
        'PIL.IcoImagePlugin',
        'PIL.JpegImagePlugin',
        'PIL.GifImagePlugin',
        # ── tkinter (fallback popup + chamados UI) ───────────────
        'tkinter',
        'tkinter.ttk',
        'tkinter.font',
        'tkinter.scrolledtext',
        'tkinter.messagebox',
        'tkinter.filedialog',
        '_tkinter',
        # ── requests + urllib3 ───────────────────────────────────
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.cookies',
        'requests.exceptions',
        'requests.models',
        'requests.sessions',
        'requests.structures',
        'urllib3',
        'urllib3.util',
        'urllib3.util.retry',
        'urllib3.util.ssl_',
        'charset_normalizer',
        'charset_normalizer.md__mypyc',
        'certifi',
        'idna',
        # ── av / PyAV ────────────────────────────────────────────
        'av',
        'av.audio',
        'av.video',
        'av.codec',
        'av.container',
        'av.format',
        # ── mss ──────────────────────────────────────────────────
        'mss',
        'mss.windows',
        # ── numpy ────────────────────────────────────────────────
        'numpy',
        'numpy.core',
        'numpy.core._multiarray_umath',
        # ── aiortc ───────────────────────────────────────────────
        'aiortc',
        'aiortc.mediastreams',
        'aiortc.rtcdatachannel',
        'aiortc.rtcpeerconnection',
        'aiortc.rtcsessiondescription',
        'aiortc.rtp',
        'aioice',
        'aioice.ice',
        'cryptography',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.openssl',
        'pyee',
        'pyee.base',
        # ── Win32 ────────────────────────────────────────────────
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        'pywintypes',
        # ── ctypes ───────────────────────────────────────────────
        'ctypes',
        'ctypes.wintypes',
        # ── windows-toasts (WinRT) ──────────────────────────
        'windows_toasts',
        'windows_toasts.toasters',
        'windows_toasts.wrappers',
        'windows_toasts.wrappers.types',
        'windows_toasts.wrappers.results',
        # winsdk — runtime WinRT exigido pelo windows-toasts
        'winsdk',
        'winsdk.windows',
        'winsdk.windows.ui',
        'winsdk.windows.ui.notifications',
        'winsdk.windows.data',
        'winsdk.windows.data.xml',
        'winsdk.windows.data.xml.dom',
        'winsdk.windows.foundation',
        'winsdk.windows.foundation.collections',
        # ── stdlib ───────────────────────────────────────────────
        'http.server',
        'socketserver',
        'logging.handlers',
        'winreg',
        'ipaddress',
        'uuid',
        'hashlib',
        'asyncio',
        'asyncio.events',
        'asyncio.base_events',
        'asyncio.futures',
        'asyncio.queues',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy',
        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'IPython', 'jupyter',
        'win11toast',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='agent_tray',
    debug=False, strip=False, upx=True,
    upx_exclude=['vcruntime140.dll', '_ssl.pyd', '_tkinter.pyd'],
    console=False,   # tray app — sem janela de console
    icon=None,
    runtime_tmpdir=None,
)