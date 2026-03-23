# -*- mode: python ; coding: utf-8 -*-
# install_agent_silent.spec — gerado por build.py
block_cipher = None

a = Analysis(
    [r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents\install_agent_silent.py'],
    pathex=[r'C:\Guilherme\GR-Colaboradores\apps\inventory\agents'],
    binaries=[
        # se NSSM for embutido no pacote, inclua aqui:
        (r'C:\Apps\TI-Agent
ssm.exe', '.'),
    ],
    datas=[],
    hiddenimports=[
        # ── tkinter ──────────────────────────────────────────────
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.font',
        '_tkinter',
        # ── Win32 / registro ─────────────────────────────────────
        'winreg',
        'ctypes',
        'ctypes.wintypes',
        # ── stdlib ───────────────────────────────────────────────
        'hashlib',
        'shutil',
        'threading',
        'subprocess',
        'pathlib',
        'logging.handlers',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'PIL', 'pystray',
        'requests', 'urllib3',
        'matplotlib', 'numpy', 'scipy',
        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'windows_toasts', 'win11toast', 'winsdk',
        'aiortc', 'av', 'mss',
        'IPython', 'jupyter',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='install_agent_silent',
    debug=False, strip=False, upx=True,
    console=False,
    uac_admin=True,   # solicita elevação UAC
    icon=None,
    runtime_tmpdir=None,
)