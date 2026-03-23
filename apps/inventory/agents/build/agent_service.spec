# -*- mode: python ; coding: utf-8 -*-
# agent_service.spec — gerado por build.py
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

a = Analysis(
    [r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\agent_service.py'],
    pathex=[r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents'],
    binaries=[],
    datas=[
        # av (PyAV) precisa de DLLs de codec empacotadas como data
        *collect_data_files('av'),
    ],
    hiddenimports=[
        # ── HTTP / requests ──────────────────────────────────────
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.cookies',
        'requests.exceptions',
        'requests.models',
        'requests.sessions',
        'requests.structures',
        # ── urllib3 ──────────────────────────────────────────────
        'urllib3',
        'urllib3.util',
        'urllib3.util.retry',
        'urllib3.util.ssl_',
        'urllib3.contrib',
        'urllib3.packages',
        'urllib3.packages.six',
        'urllib3.packages.six.moves',
        # ── deps do requests ─────────────────────────────────────
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
        # ── mss (captura de tela) ────────────────────────────────
        'mss',
        'mss.windows',
        # ── numpy ────────────────────────────────────────────────
        'numpy',
        'numpy.core',
        'numpy.core._multiarray_umath',
        # ── aiortc + dependências ────────────────────────────────
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
        # ── Win32 (mouse/teclado/shell) ──────────────────────────
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        'pywintypes',
        # ── ctypes (SHGetKnownFolderPath, windll) ───────────────
        'ctypes',
        'ctypes.wintypes',
        # ── stdlib dinâmico ──────────────────────────────────────
        'http.server',
        'socketserver',
        'logging.handlers',
        'ipaddress',
        'uuid',
        'socket',
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
        'tkinter', '_tkinter',
        'PIL', 'pystray',
        'matplotlib', 'scipy',
        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'windows_toasts', 'win11toast',
        'IPython', 'jupyter',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='agent_service',
    debug=False, strip=False, upx=True,
    upx_exclude=['vcruntime140.dll', '_ssl.pyd'],
    console=True,   # NSSM precisa capturar stdout/stderr
    runtime_tmpdir=None,
)