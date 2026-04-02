# agent_tray.py — v3.5.1
# Tray App: roda na sessão do usuário, recebe WebRTC do agent_service,
# exibe notificações nativas e gerencia chamados de suporte.
#
# CHANGELOG v3.5.3  (clipboard bridge Ctrl+C/V nativo)
# ─────────────────────────────────────────────────────────────────
# [NOVO]  CLIP-B1/B2/B3: bridge de clipboard Ctrl+C, Ctrl+V, Ctrl+X
#   Browser intercepta com e.preventDefault() antes do browser copiar/colar.
#   Ctrl+C: injeta na remota + pede clipboard de volta.
#   Ctrl+V: usa _remoteClipboard ou Clipboard API, envia paste ao agente.
# [NOVO]  CLIP-B4: ao entrar no foco do video, clipboard local e sincronizado
#   silenciosamente para o Windows via clipboard_set_silent.
# [NOVO]  clipboard_set_silent: define clipboard Windows sem colar.
# [MELHORIA] paste: pyperclip -> SetClipboardData -> Unicode (3 estrategias).
# [MELHORIA] _send_clipboard_to_browser: fallback GetClipboardData ctypes.
# ─────────────────────────────────────────────────────────────────
#
# CHANGELOG v3.5.2  (hotfix — clique não funcionava no acesso remoto)
# ─────────────────────────────────────────────────────────────────
# [CRÍTICO] A1 — pywin32 ausente bloqueava TODOS os eventos de input
#   Causa: guard "if not _WIN32_OK: return" descartava silenciosamente
#   qualquer md/mu/mc/kd/ku recebido. O log mostrava [ERROR] pywin32
#   não encontrado mas sem indicar que input estava completamente morto.
#   Fix: toda a lógica de mouse e teclado reescrita com ctypes puro via
#   SendInput — zero dependência de pywin32. SetCursorPos (mm) tem
#   fallback user32.SetCursorPos se win32api indisponível.
#
# [CRÍTICO] A2 — mouse_event() sem MOUSEEVENTF_ABSOLUTE
#   Causa: mouse_event(LEFTDOWN, x, y) interpreta x/y como delta relativo
#   (movimento desde posição atual), não coordenada absoluta. Resultado:
#   cliques chegavam ao agente mas aterrissavam na posição errada.
#   Fix: substituído por SendInput com MOUSEEVENTF_ABSOLUTE e coordenadas
#   normalizadas 0–65535 via SM_CXVIRTUALSCREEN/SM_CYVIRTUALSCREEN.
#   Suporta corretamente multi-monitor com monitores à esquerda/acima.
#
# [SÉRIO]   F1 (frontend) — canal DataChannel input sem retransmissão
#   Causa: ordered:false + maxRetransmits:0 fazia md/mu/mc serem UDP-like.
#   Um único pacote perdido deixava o botão preso (md sem mu) no agente.
#   Fix: ordered:true — cliques precisam ser confiáveis e ordenados.
#
# [SÉRIO]   F2 (frontend) — mouseup botão direito não enviava mu
#   Causa: button===2 no mouseup só enviava mc (right click), nunca mu
#   (rightup). O agente recebia RIGHTDOWN mas nunca RIGHTUP, deixando o
#   botão direito "preso" — qualquer mousemove seguinte arrastava.
#   Fix: send({t:'mu',b:'right'}) adicionado antes do mc no mouseup.
# ─────────────────────────────────────────────────────────────────
#
# CHANGELOG v3.5.1  (hotfix de produção — log 2026-03-30)
# ─────────────────────────────────────────────────────────────────
# [CRÍTICO] LOG-B2 — "Track already has a sender"
#   Causa: o objeto ScreenTrack sobrevivia ao RTCPeerConnection que falhou.
#   Na retentativa do browser, o mesmo track era passado para um novo pc,
#   que recusava porque o track já estava vinculado a um sender do pc anterior.
#   Fix: track criado DENTRO de negotiate() — cada coroutine instancia o seu.
#        Se addTrack também falhar, pc.close() é chamado e RuntimeError é
#        relançado para que o browser receba 500 e tente com nova oferta.
#
# [SÉRIO]   LOG-B1 — AttributeError: 'RTCRtpSender' has no 'getParameters'
#   Causa: versão do aiortc instalada não implementa getParameters/setParameters.
#   Fix 1: bloco getParameters/setParameters separado do addTransceiver em
#           try/except próprio — falha em setParameters não derruba o transceiver.
#   Fix 2: _apply_quality() com hasattr(sender, "getParameters") guard —
#           escala de qualidade (downscale) ainda é aplicada mesmo sem o método.
# ─────────────────────────────────────────────────────────────────
#
# CHANGELOG v3.5.0
# ─────────────────────────────────────────────────────────────────
# [CRÍTICO] P1 — _active_transceiver era variável local em negotiate()
# [CRÍTICO] P5 — RTCPeerConnection nunca fechava
# [CRÍTICO] P6 — Event loop orfão por sessão
# [SÉRIO]   P2 — setParameters sem encodings válidos
# [SÉRIO]   P3 — maxBitrate fixo travava REMB no perfil "auto"
# [SÉRIO]   P4 — Downscale por slicing NumPy sem interpolação
# [SÉRIO]   P8 — _handle_file_chunk sem identificador de arquivo
# [MENOR]   P7 — session_id por MD5 truncado
# [MENOR]   P11 — HTTPServer single-thread bloqueava durante negociação
# ─────────────────────────────────────────────────────────────────

import os
import sys
import re
import time
import json
import uuid
import asyncio
import threading
import platform
import tkinter as tk
import ctypes
import ctypes.wintypes
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler   # FIX P11
import logging
import requests
import av
import mss
import numpy as np

from notification import ToastNotification
from chamados import ChamadosManager

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
except ImportError:
    print("ERRO: pip install pystray pillow")
    sys.exit(1)

try:
    import win32api
    import win32con
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False

VERSION       = "3.5.3"
IPC_URL       = "http://127.0.0.1:7070"
WEBRTC_PORT   = 7071
POLL_INTERVAL = 8

LOG_DIR = Path(os.path.dirname(__file__)) / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "tray.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("AgentTray")


# ═════════════════════════════════════════════════════════════════════════════
# WebRTC — captura de tela (roda na sessão do usuário ✓)
# ═════════════════════════════════════════════════════════════════════════════

_webrtc_data_channels:  dict = {}
_webrtc_dc_lock               = threading.Lock()
_file_buffers:          dict = {}
_file_buffers_lock            = threading.Lock()

# FIX P1 — transceivers indexados por session_id (era variável local)
_active_transceivers:   dict = {}
_transceivers_lock            = threading.Lock()

# FIX P6 — loop global único; uma thread por processo, não por sessão
_global_webrtc_loop:   asyncio.AbstractEventLoop | None = None
_global_webrtc_thread: threading.Thread | None          = None
_global_loop_lock      = threading.Lock()


def _get_or_create_webrtc_loop() -> asyncio.AbstractEventLoop:
    """
    Retorna (ou cria) o event loop global para todas as sessões WebRTC.
    Antes: cada sessão criava seu próprio loop + thread → leak de recursos.
    Agora: um único loop compartilhado, thread daemon.
    """
    global _global_webrtc_loop, _global_webrtc_thread
    with _global_loop_lock:
        if _global_webrtc_loop and not _global_webrtc_loop.is_closed():
            return _global_webrtc_loop
        loop = asyncio.new_event_loop()
        t = threading.Thread(
            target=loop.run_forever,
            daemon=True,
            name="webrtc-main-loop",
        )
        t.start()
        _global_webrtc_loop = loop
        _global_webrtc_thread = t
        logger.info("WebRTC: loop global criado")
        return loop


def _even(n: int) -> int:
    """Garante valor par — requisito do codec YUV420p."""
    return n if n % 2 == 0 else n - 1

_QUALITY_PROFILES = {
    #         maxBitrate  maxFPS  downscale
    "auto":   (None,       30,    1.0),   # FIX P3: None = REMB livre, sem teto artificial
    "high":   (2_000_000,  30,    1.0),
    "medium": (  800_000,  20,    0.75),
    "low":    (  300_000,  15,    0.5),
}

# FIX P1 + P2: recebe session_id em vez do transceiver diretamente
def _apply_quality(session_id: str, quality: str):
    """
    Aplica perfil de qualidade no RTCRtpSender da sessão indicada.
    Chamada quando o frontend envia {"t": "set_quality", "quality": "low"}.

    FIX P1: transceiver buscado no dict global, não capturado em closure.
    FIX P2: guard para encodings vazio + suporte a setParameters coroutine.
    FIX P3: perfil "auto" não define maxBitrate — REMB corre livre.
    """
    with _transceivers_lock:
        transceiver = _active_transceivers.get(session_id)
    if not transceiver:
        logger.warning(f"set_quality: transceiver não encontrado para {session_id[:8]}")
        return

    profile = _QUALITY_PROFILES.get(quality, _QUALITY_PROFILES["auto"])
    max_bitrate, max_fps, scale = profile

    try:
        sender = transceiver.sender

        # Guard para versões antigas do aiortc sem getParameters/setParameters
        if not hasattr(sender, "getParameters"):
            logger.info(
                f"WebRTC: set_quality ignorado — aiortc sem getParameters "
                f"(qualidade visual aplicada via scale={scale})"
            )
            ScreenTrack._quality_scale = scale
            return

        params = sender.getParameters()

        # FIX P2: guard — encodings pode estar vazio antes do ICE completar
        if not params.encodings:
            logger.warning(f"set_quality: encodings vazio para {session_id[:8]} — ICE pendente?")
            ScreenTrack._quality_scale = scale
            return

        for enc in params.encodings:
            # FIX P3: "auto" não define teto de bitrate
            if max_bitrate is not None:
                enc.maxBitrate = max_bitrate
            enc.maxFramerate = max_fps

        result = sender.setParameters(params)

        # FIX P2: aiortc >= 1.6 pode retornar coroutine
        if asyncio.iscoroutine(result):
            loop = _get_or_create_webrtc_loop()
            asyncio.run_coroutine_threadsafe(result, loop)

        logger.info(
            f"WebRTC: qualidade={quality} | "
            f"bitrate={'REMB livre' if max_bitrate is None else f'{max_bitrate//1000}kbps'} | "
            f"fps={max_fps} | scale={scale} | session={session_id[:8]}"
        )
    except Exception as e:
        logger.warning(f"WebRTC: setParameters falhou ({e}) | session={session_id[:8]}")

    ScreenTrack._quality_scale = scale


# ─────────────────────────────────────────────────────────────────────────────
# GDI capture — WDDM 1.x (E5400, i3-2xxx/3xxx/4xxx)
# ─────────────────────────────────────────────────────────────────────────────

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          ctypes.c_uint32),
        ("biWidth",         ctypes.c_int32),
        ("biHeight",        ctypes.c_int32),   # negativo = top-down, zero stride
        ("biPlanes",        ctypes.c_uint16),
        ("biBitCount",      ctypes.c_uint16),
        ("biCompression",   ctypes.c_uint32),
        ("biSizeImage",     ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed",       ctypes.c_uint32),
        ("biClrImportant",  ctypes.c_uint32),
    ]


class _GDICapture:
    """
    Captura de tela via GDI BitBlt + GetDIBits.
    Recursos GDI alocados uma vez por monitor — sem alloc/free por frame.
    biHeight negativo garante layout top-down e zero stride padding.
    """

    def __init__(self):
        self._gdi32      = ctypes.windll.gdi32
        self._user32     = ctypes.windll.user32
        self._lock       = threading.Lock()
        self._hdc_screen = None
        self._hdc_mem    = None
        self._hbmp       = None
        self._buf        = None
        self._bmi        = None
        self._last_mon   = None

    def _setup(self, left: int, top: int, width: int, height: int):
        mon_key = (left, top, width, height)
        if self._last_mon == mon_key:
            return
        self._release()
        self._hdc_screen = self._user32.GetDC(0)
        self._hdc_mem    = self._gdi32.CreateCompatibleDC(self._hdc_screen)
        self._hbmp       = self._gdi32.CreateCompatibleBitmap(self._hdc_screen, width, height)
        self._gdi32.SelectObject(self._hdc_mem, self._hbmp)
        self._buf        = (ctypes.c_uint8 * (width * height * 4))()
        bmi              = _BITMAPINFOHEADER()
        bmi.biSize       = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth      = width
        bmi.biHeight     = -height  # CRÍTICO: negativo = top-down + zero stride
        bmi.biPlanes     = 1
        bmi.biBitCount   = 32       # BGRA 32bpp
        bmi.biCompression = 0       # BI_RGB
        self._bmi        = bmi
        self._last_mon   = mon_key

    def _release(self):
        try:
            if self._hbmp:       self._gdi32.DeleteObject(self._hbmp)
            if self._hdc_mem:    self._gdi32.DeleteDC(self._hdc_mem)
            if self._hdc_screen: self._user32.ReleaseDC(0, self._hdc_screen)
        except Exception:
            pass
        self._hdc_screen = self._hdc_mem = self._hbmp = None
        self._buf = self._bmi = self._last_mon = None

    def grab(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        with self._lock:
            self._setup(left, top, width, height)
            # SRCCOPY = 0x00CC0020
            self._gdi32.BitBlt(
                self._hdc_mem, 0, 0, width, height,
                self._hdc_screen, left, top, 0x00CC0020,
            )
            # DIB_RGB_COLORS = 0
            self._gdi32.GetDIBits(
                self._hdc_mem, self._hbmp, 0, height,
                self._buf, ctypes.byref(self._bmi), 0,
            )
            return np.frombuffer(self._buf, dtype=np.uint8).reshape(
                (height, width, 4)
            ).copy()

    def __del__(self):
        self._release()


# ─────────────────────────────────────────────────────────────────────────────
# BT.601 LUT — pré-calculada na importação, reutilizada em todos os frames
# ─────────────────────────────────────────────────────────────────────────────

def _build_bt601_lut() -> dict:
    v = np.arange(256, dtype=np.float32)
    return {
        "Yr":  (0.257 * v).astype(np.float32),
        "Yg":  (0.504 * v).astype(np.float32),
        "Yb":  (0.098 * v).astype(np.float32),
        "Cbr": (0.148 * v).astype(np.float32),
        "Cbg": (0.291 * v).astype(np.float32),
        "Cbb": (0.439 * v).astype(np.float32),
        "Crr": (0.439 * v).astype(np.float32),
        "Crg": (0.368 * v).astype(np.float32),
        "Crb": (0.071 * v).astype(np.float32),
    }

_BT601_LUT = _build_bt601_lut()


def _bgra_to_yuv420p_frame(arr: np.ndarray, pts: int, time_base) -> "av.VideoFrame":
    """
    Converte array BGRA (H, W, 4) → av.VideoFrame yuv420p.
    Corrige alinhamento de stride para larguras não múltiplas de 32.
    """
    h, w = arr.shape[:2]
    h2   = h // 2
    w2   = w // 2
    lut  = _BT601_LUT

    B = arr[:, :, 0]
    G = arr[:, :, 1]
    R = arr[:, :, 2]

    Y  = ( lut["Yr"][R]  + lut["Yg"][G]  + lut["Yb"][B]  + 16 ).clip(0, 255).astype(np.uint8)
    Cb = (-lut["Cbr"][R] - lut["Cbg"][G] + lut["Cbb"][B] + 128).clip(0, 255).astype(np.uint8)
    Cr = ( lut["Crr"][R] - lut["Crg"][G] - lut["Crb"][B] + 128).clip(0, 255).astype(np.uint8)

    Cb_sub = Cb[0::2, 0::2]
    Cr_sub = Cr[0::2, 0::2]

    frame = av.VideoFrame(width=w, height=h, format="yuv420p")

    y_stride  = frame.planes[0].line_size
    uv_stride = frame.planes[1].line_size

    # Plano Y
    if y_stride == w:
        frame.planes[0].update(Y.tobytes())
    else:
        y_buf = np.zeros((h, y_stride), dtype=np.uint8)
        y_buf[:, :w] = Y
        frame.planes[0].update(y_buf.tobytes())

    # Plano Cb
    if uv_stride == w2:
        frame.planes[1].update(Cb_sub.tobytes())
    else:
        cb_buf = np.zeros((h2, uv_stride), dtype=np.uint8)
        cb_buf[:, :w2] = Cb_sub
        frame.planes[1].update(cb_buf.tobytes())

    # Plano Cr
    if uv_stride == w2:
        frame.planes[2].update(Cr_sub.tobytes())
    else:
        cr_buf = np.zeros((h2, uv_stride), dtype=np.uint8)
        cr_buf[:, :w2] = Cr_sub
        frame.planes[2].update(cr_buf.tobytes())

    frame.pts       = pts
    frame.time_base = time_base
    return frame


# ─────────────────────────────────────────────────────────────────────────────
# Downscale com interpolação — FIX P4
# ─────────────────────────────────────────────────────────────────────────────

def _downscale_arr(arr: np.ndarray, scale: float) -> np.ndarray:
    """
    FIX P4: downscale com INTER_AREA (cv2) ou média em blocos.
    O slicing puro arr[::step, ::step] descartava pixels sem filtro,
    causando aliasing severo em movimento (scroll, arrastar janelas).

    Hierarquia de qualidade:
      1. cv2.INTER_AREA — melhor para downscale, sem aliasing
      2. média em blocos NumPy — aceitável, sem dependência externa
    """
    if scale >= 1.0:
        return arr
    h, w = arr.shape[:2]
    new_w = max(2, int(w * scale) & ~1)  # garante par
    new_h = max(2, int(h * scale) & ~1)
    try:
        import cv2
        return cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    except ImportError:
        pass
    # Fallback: média em blocos
    step_x = max(1, w // new_w)
    step_y = max(1, h // new_h)
    sampled = arr[::step_y, ::step_x, :]
    return sampled[:new_h, :new_w, :]


# ─────────────────────────────────────────────────────────────────────────────
# Detecção de método de captura
# ─────────────────────────────────────────────────────────────────────────────

def _detect_capture_method() -> str:
    """
    'dxgi' se WDDM 2.x disponível (mss via __array_interface__).
    'gdi'  se apenas WDDM 1.x disponível (GDI BitBlt via ctypes).
    """
    try:
        with mss.mss() as sct:
            if len(sct.monitors) < 2:
                return "gdi"
            mon = sct.monitors[1]
            img = sct.grab(mon)
            arr = np.array(img)
            if arr.shape == (mon["height"], mon["width"], 4):
                return "dxgi"
    except Exception:
        pass
    return "gdi"


# ─────────────────────────────────────────────────────────────────────────────
# ScreenTrack — captura híbrida GDI + DXGI
# ─────────────────────────────────────────────────────────────────────────────

class ScreenTrack:
    _monitor_index = 1
    _quality_scale = 1.0
    _switch_lock   = threading.Lock()
    _aiortc_base   = None

    @classmethod
    def _get_base(cls):
        if cls._aiortc_base is None:
            from aiortc.mediastreams import VideoStreamTrack
            cls._aiortc_base = VideoStreamTrack
        return cls._aiortc_base

    def __new__(cls, *args, **kwargs):
        base     = cls._get_base()
        DynTrack = type("DynScreenTrack", (base,), {
            "kind":     "video",
            "recv":     cls._recv_impl,
            "__init__": cls._init_impl,
        })
        return object.__new__(DynTrack)

    @staticmethod
    def _init_impl(self):
        from aiortc.mediastreams import VideoStreamTrack
        VideoStreamTrack.__init__(self)
        self._sct            = None
        self._gdi            = None
        self._monitor        = None
        self._current_idx    = None
        self._capture_method = None
        self._logged_first   = False

    @staticmethod
    async def _recv_impl(self):

        # ── Inicialização lazy ────────────────────────────────────────────────
        if self._capture_method is None:
            self._capture_method = _detect_capture_method()
            logger.info(f"ScreenTrack: método de captura detectado = {self._capture_method}")
            if self._capture_method == "dxgi":
                self._sct = mss.mss()
            else:
                self._gdi = _GDICapture()

        # ── Troca de monitor ──────────────────────────────────────────────────
        target_idx = ScreenTrack._monitor_index
        if self._current_idx != target_idx:
            if self._capture_method == "dxgi":
                monitors = self._sct.monitors
                idx = target_idx if 1 <= target_idx < len(monitors) else 1
                self._monitor = monitors[idx]
            else:
                user32   = ctypes.windll.user32
                monitors = []
                MONITORENUMPROC = ctypes.WINFUNCTYPE(
                    ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                    ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double,
                )
                def _cb(hMon, hdcMon, lpRect, dwData):
                    r = lpRect.contents
                    monitors.append({
                        "left": r.left, "top": r.top,
                        "width": r.right - r.left, "height": r.bottom - r.top,
                    })
                    return 1
                user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
                if not monitors:
                    w = user32.GetSystemMetrics(0)
                    h = user32.GetSystemMetrics(1)
                    monitors = [{"left": 0, "top": 0, "width": w, "height": h}]
                idx = (target_idx - 1) if target_idx - 1 < len(monitors) else 0
                self._monitor = monitors[idx]
            self._current_idx = target_idx

        pts, time_base = await self.next_timestamp()

        # ── Captura ───────────────────────────────────────────────────────────
        arr = None
        try:
            if self._capture_method == "dxgi":
                img = self._sct.grab(self._monitor)
                arr = np.array(img)
                if arr.shape != (self._monitor["height"], self._monitor["width"], 4):
                    raise ValueError(f"mss shape inesperado: {arr.shape}")
            else:
                mon = self._monitor
                arr = self._gdi.grab(mon["left"], mon["top"], mon["width"], mon["height"])
        except Exception as e:
            logger.error(f"ScreenTrack: captura falhou ({e}), tentando GDI fallback")
            try:
                if self._gdi is None:
                    self._gdi = _GDICapture()
                mon = self._monitor or {"left": 0, "top": 0, "width": 1920, "height": 1080}
                arr = self._gdi.grab(
                    mon.get("left", 0), mon.get("top", 0),
                    mon.get("width", 1920), mon.get("height", 1080),
                )
                self._capture_method = "gdi"
                logger.warning("ScreenTrack: fallback permanente para GDI ativado")
            except Exception as e2:
                logger.error(f"ScreenTrack: GDI fallback também falhou ({e2})")

        # Frame preto de emergência
        if arr is None:
            mon = self._monitor or {}
            w_s = max(2, (mon.get("width",  1920) // 2) * 2)
            h_s = max(2, (mon.get("height", 1080) // 2) * 2)
            frame = av.VideoFrame(width=w_s, height=h_s, format="yuv420p")
            frame.pts = pts
            frame.time_base = time_base
            return frame

        # ── Cap resolução ─────────────────────────────────────────────────────
        h, w = arr.shape[:2]
        MAX_W, MAX_H = 3840, 2160
        if w > MAX_W or h > MAX_H:
            scale  = min(MAX_W / w, MAX_H / h)
            step_x = max(1, int(1 / scale))
            step_y = max(1, int(1 / scale))
            arr    = arr[::step_y, ::step_x]
            h, w   = arr.shape[:2]

        # ── FIX P4: Downscale com interpolação ───────────────────────────────
        q_scale = ScreenTrack._quality_scale
        if q_scale < 1.0:
            arr  = _downscale_arr(arr, q_scale)
            h, w = arr.shape[:2]

        # ── Garante dimensões pares ───────────────────────────────────────────
        h_e = max(2, (h // 2) * 2)
        w_e = max(2, (w // 2) * 2)
        if h_e > h or w_e > w:
            padded = np.zeros((h_e, w_e, 4), dtype=np.uint8)
            padded[:h, :w] = arr
            arr = padded
        else:
            arr = arr[:h_e, :w_e]

        # ── Conversão YUV + montagem do frame ─────────────────────────────────
        try:
            frame = _bgra_to_yuv420p_frame(arr, pts, time_base)
        except Exception as e:
            logger.error(f"ScreenTrack: YUV falhou ({e}) — frame preto")
            frame = av.VideoFrame(width=w_e, height=h_e, format="yuv420p")
            frame.pts = pts
            frame.time_base = time_base

        if not self._logged_first:
            self._logged_first = True
            logger.info(
                f"ScreenTrack first frame OK | "
                f"method={self._capture_method} | "
                f"raw=({w}x{h}) | "
                f"encoded=({frame.width}x{frame.height}) | "
                f"monitor={self._monitor}"
            )

        return frame


# ═════════════════════════════════════════════════════════════════════════════
# Screen Lock
# ═════════════════════════════════════════════════════════════════════════════

_lock_windows:   list                    = []
_lock_tk_root:   tk.Tk | None           = None
_lock_thread:    threading.Thread | None = None
_lock_state_lock = threading.Lock()


def _get_all_monitors() -> list[dict]:
    monitors = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double,
    )
    def _cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
        r = lprcMonitor.contents
        monitors.append({
            "left":   r.left,
            "top":    r.top,
            "width":  r.right  - r.left,
            "height": r.bottom - r.top,
        })
        return 1
    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    except Exception as e:
        logger.warning(f"EnumDisplayMonitors falhou: {e}")
    if not monitors:
        try:
            with mss.mss() as sct:
                monitors = [
                    {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}
                    for m in sct.monitors[1:]
                ]
        except Exception as e:
            logger.warning(f"mss monitor fallback falhou: {e}")
    if not monitors:
        user32 = ctypes.windll.user32
        monitors = [{"left": 0, "top": 0, "width": user32.GetSystemMetrics(0), "height": user32.GetSystemMetrics(1)}]
    return monitors


def _screen_lock_thread(session_id: str):
    global _lock_windows, _lock_tk_root
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        logger.error(f"Screen lock: falha ao criar Tk root — {e}")
        return
    with _lock_state_lock:
        _lock_tk_root = root
        _lock_windows = []
    monitors = _get_all_monitors()
    logger.info(f"Screen lock: cobrindo {len(monitors)} monitor(es)")
    block = lambda e: "break"
    for i, mon in enumerate(monitors):
        try:
            win = tk.Toplevel(root)
            win.configure(bg="black")
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.attributes("-alpha", 1.0)
            win.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
            for seq in ("<Key>", "<KeyPress>", "<KeyRelease>",
                        "<Button>", "<ButtonPress>", "<ButtonRelease>",
                        "<Motion>", "<MouseWheel>", "<Enter>", "<Leave>"):
                win.bind(seq, block)
            if i == len(monitors) - 1:
                win.grab_set()
                win.focus_force()
            with _lock_state_lock:
                _lock_windows.append(win)
        except Exception as e:
            logger.error(f"Screen lock: erro no monitor {mon} — {e}")
    _send_to_session(session_id, {"t": "screen_locked"})
    logger.info("Screen lock: ativo")
    try:
        root.mainloop()
    except Exception as e:
        logger.error(f"Screen lock: mainloop encerrado com erro — {e}")
    logger.info("Screen lock: thread encerrada")


def _do_screen_lock(session_id: str):
    global _lock_thread
    with _lock_state_lock:
        if _lock_thread and _lock_thread.is_alive():
            logger.warning("Screen lock: já ativo, ignorando duplicata")
            _send_to_session(session_id, {"t": "screen_locked"})
            return
    _lock_thread = threading.Thread(
        target=_screen_lock_thread, args=(session_id,), daemon=True, name="ScreenLock",
    )
    _lock_thread.start()


def _do_screen_unlock(session_id: str):
    global _lock_windows, _lock_tk_root

    def _destroy_all():
        global _lock_windows, _lock_tk_root
        for win in list(_lock_windows):
            try:
                win.grab_release()
                win.destroy()
            except Exception:
                pass
        with _lock_state_lock:
            _lock_windows.clear()
        root = _lock_tk_root
        if root:
            try:
                root.quit()
                root.destroy()
            except Exception:
                pass
            with _lock_state_lock:
                _lock_tk_root = None
        logger.info("Screen lock: janelas destruídas com sucesso")

    root = None
    with _lock_state_lock:
        root = _lock_tk_root
    if root:
        try:
            root.after(0, _destroy_all)
        except Exception:
            _destroy_all()
    else:
        with _lock_state_lock:
            _lock_windows.clear()
    _send_to_session(session_id, {"t": "screen_unlocked"})
    logger.info("Screen lock: desbloqueado")


def _send_to_session(session_id: str, msg: dict):
    try:
        payload = json.dumps(msg)
        with _webrtc_dc_lock:
            queue = _webrtc_data_channels.get(session_id)
        if queue:
            queue.put_nowait(payload)
    except Exception as e:
        logger.warning(f"_send_to_session falhou: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# Input handler
# ═════════════════════════════════════════════════════════════════════════════

def _get_active_monitor_dims() -> tuple[int, int]:
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = ScreenTrack._monitor_index
            if 1 <= idx < len(monitors):
                m = monitors[idx]
                return m["width"], m["height"]
    except Exception:
        pass
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ─────────────────────────────────────────────────────────────────────────────
# SendInput — implementação via ctypes pura (fallback quando pywin32 ausente)
# FIX A2: mouse_event() ignora x,y sem MOUSEEVENTF_ABSOLUTE, causando cliques
# na posição errada. SendInput com coordenadas normalizadas 0–65535 é a API
# correta para injeção absoluta de eventos de mouse.
# FIX A1: toda a lógica de input agora funciona sem pywin32. Quando _WIN32_OK
# é False, o agente ainda processa todos os eventos usando ctypes puro.
# ─────────────────────────────────────────────────────────────────────────────

# Estruturas para SendInput
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_", _INPUT_UNION)]

_INPUT_MOUSE    = 0
_INPUT_KEYBOARD = 1

# Flags de mouse
_MOUSEEVENTF_MOVE        = 0x0001
_MOUSEEVENTF_LEFTDOWN    = 0x0002
_MOUSEEVENTF_LEFTUP      = 0x0004
_MOUSEEVENTF_RIGHTDOWN   = 0x0008
_MOUSEEVENTF_RIGHTUP     = 0x0010
_MOUSEEVENTF_MIDDLEDOWN  = 0x0020
_MOUSEEVENTF_MIDDLEUP    = 0x0040
_MOUSEEVENTF_WHEEL       = 0x0800
_MOUSEEVENTF_HWHEEL      = 0x1000
_MOUSEEVENTF_ABSOLUTE    = 0x8000  # coordenadas normalizadas 0–65535

# Flags de teclado
_KEYEVENTF_KEYUP         = 0x0002
_KEYEVENTF_UNICODE       = 0x0004


def _send_mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0):
    """
    Injeta evento de mouse via SendInput — API correta para input absoluto.
    FIX A2: usa MOUSEEVENTF_ABSOLUTE com coords normalizadas.
    Não depende de pywin32.
    """
    inp = _INPUT()
    inp.type       = _INPUT_MOUSE
    inp._.mi.dx    = dx
    inp._.mi.dy    = dy
    inp._.mi.mouseData = data
    inp._.mi.dwFlags   = flags
    inp._.mi.time      = 0
    inp._.mi.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_key_input(vk: int, flags: int = 0):
    """Injeta evento de teclado via SendInput. Não depende de pywin32."""
    inp = _INPUT()
    inp.type      = _INPUT_KEYBOARD
    inp._.ki.wVk  = vk
    inp._.ki.wScan = 0
    inp._.ki.dwFlags = flags
    inp._.ki.time    = 0
    inp._.ki.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_unicode_input(char: str, key_up: bool = False):
    """Injeta caractere Unicode via SendInput KEYEVENTF_UNICODE."""
    flags = _KEYEVENTF_UNICODE | (_KEYEVENTF_KEYUP if key_up else 0)
    inp = _INPUT()
    inp.type       = _INPUT_KEYBOARD
    inp._.ki.wVk   = 0
    inp._.ki.wScan = ord(char)
    inp._.ki.dwFlags = flags
    inp._.ki.time    = 0
    inp._.ki.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _norm(px: int, total: int) -> int:
    """
    Converte pixel absoluto para coordenada normalizada SendInput (0–65535).
    FIX A2: mouse_event(x, y) sem ABSOLUTE interpreta x/y como delta relativo.
    SendInput com ABSOLUTE requer normalização: val = (px * 65536) // total.
    """
    return max(0, min(65535, (px * 65536) // max(1, total)))


def _handle_input_event(event: dict, session_id: str = ""):
    t = event.get("t")

    # Screen lock/unlock — não precisam de pywin32
    if t == "screen_lock":
        _do_screen_lock(session_id)
        return
    if t == "screen_unlock":
        _do_screen_unlock(session_id)
        return

    # FIX A1: não retorna mais quando _WIN32_OK é False.
    # A maioria dos eventos usa ctypes puro via SendInput.
    # pywin32 só é necessário para SetCursorPos (mm) — que tem fallback.

    try:
        user32 = ctypes.windll.user32

        # Dimensões e offset do monitor ativo
        sw, sh = _get_active_monitor_dims()
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                idx = ScreenTrack._monitor_index
                if 1 <= idx < len(monitors):
                    m     = monitors[idx]
                    off_x = m["left"]
                    off_y = m["top"]
                    mon_w = m["width"]
                    mon_h = m["height"]
                else:
                    off_x = off_y = 0
                    mon_w, mon_h = sw, sh
        except Exception:
            off_x = off_y = 0
            mon_w, mon_h = sw, sh

        # Dimensões virtuais totais (multi-monitor) para normalização absoluta
        virt_w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        virt_h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        virt_x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN (origin pode ser negativo)
        virt_y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        if virt_w <= 0: virt_w = sw
        if virt_h <= 0: virt_h = sh

        def abs_xy(e):
            """Pixel absoluto dentro do monitor ativo."""
            lx = max(0, min(mon_w - 1, int(e.get("x", 0) * mon_w))) + off_x
            ly = max(0, min(mon_h - 1, int(e.get("y", 0) * mon_h))) + off_y
            return lx, ly

        def norm_xy(e):
            """
            FIX A2: coordenadas normalizadas para SendInput ABSOLUTE.
            Subtrai a origem virtual para suportar monitores à esquerda/acima do primário.
            """
            lx, ly = abs_xy(e)
            return _norm(lx - virt_x, virt_w), _norm(ly - virt_y, virt_h)

        if t == "mm":
            # SetCursorPos posiciona o cursor visualmente (não injeta evento)
            lx, ly = abs_xy(event)
            if _WIN32_OK:
                win32api.SetCursorPos((lx, ly))
            else:
                user32.SetCursorPos(lx, ly)

        elif t == "mc":
            # FIX A2: move absoluto + click via SendInput com ABSOLUTE
            nx, ny = norm_xy(event)
            b = event.get("b", "left")
            _send_mouse_input(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, nx, ny)
            if b == "left":
                _send_mouse_input(_MOUSEEVENTF_LEFTDOWN  | _MOUSEEVENTF_ABSOLUTE, nx, ny)
                _send_mouse_input(_MOUSEEVENTF_LEFTUP    | _MOUSEEVENTF_ABSOLUTE, nx, ny)
            elif b == "right":
                _send_mouse_input(_MOUSEEVENTF_RIGHTDOWN | _MOUSEEVENTF_ABSOLUTE, nx, ny)
                _send_mouse_input(_MOUSEEVENTF_RIGHTUP   | _MOUSEEVENTF_ABSOLUTE, nx, ny)

        elif t == "mdc":
            nx, ny = norm_xy(event)
            _send_mouse_input(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, nx, ny)
            for _ in range(2):
                _send_mouse_input(_MOUSEEVENTF_LEFTDOWN | _MOUSEEVENTF_ABSOLUTE, nx, ny)
                _send_mouse_input(_MOUSEEVENTF_LEFTUP   | _MOUSEEVENTF_ABSOLUTE, nx, ny)

        elif t == "md":
            nx, ny = norm_xy(event)
            _send_mouse_input(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, nx, ny)
            b = event.get("b")
            if b == "left":
                _send_mouse_input(_MOUSEEVENTF_LEFTDOWN  | _MOUSEEVENTF_ABSOLUTE, nx, ny)
            elif b == "right":
                _send_mouse_input(_MOUSEEVENTF_RIGHTDOWN | _MOUSEEVENTF_ABSOLUTE, nx, ny)

        elif t == "mu":
            nx, ny = norm_xy(event)
            b = event.get("b")
            if b == "left":
                _send_mouse_input(_MOUSEEVENTF_LEFTUP  | _MOUSEEVENTF_ABSOLUTE, nx, ny)
            elif b == "right":
                # FIX F2 (agente): rightup agora tratado explicitamente
                _send_mouse_input(_MOUSEEVENTF_RIGHTUP | _MOUSEEVENTF_ABSOLUTE, nx, ny)

        elif t == "mw":
            delta = int(event.get("delta", 0) * 120)
            _send_mouse_input(_MOUSEEVENTF_WHEEL, data=delta & 0xFFFFFFFF)

        elif t == "mb":
            if event.get("d"):
                _send_mouse_input(_MOUSEEVENTF_MIDDLEDOWN)
            else:
                _send_mouse_input(_MOUSEEVENTF_MIDDLEUP)

        elif t == "ms":
            d = int(event.get("d", 0))
            _send_mouse_input(_MOUSEEVENTF_WHEEL,  data=(d * 120) & 0xFFFFFFFF)

        elif t == "msh":
            d = int(event.get("d", 0))
            _send_mouse_input(_MOUSEEVENTF_HWHEEL, data=(d * 120) & 0xFFFFFFFF)

        elif t == "kd":
            vk = event.get("vk")
            if vk:
                _send_key_input(vk, 0)

        elif t == "ku":
            vk = event.get("vk")
            if vk:
                _send_key_input(vk, _KEYEVENTF_KEYUP)

        elif t == "kt":
            # FIX A1: digita via SendInput Unicode — não depende de pyautogui
            char = event.get("k", "")
            for c in char:
                _send_unicode_input(c, key_up=False)
                _send_unicode_input(c, key_up=True)

        elif t == "kp":
            # Teclas especiais mapeadas para VK
            _VK_MAP = {
                "enter": 0x0D, "backspace": 0x08, "tab": 0x09, "escape": 0x1B,
                "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
                "pageup": 0x21, "pagedown": 0x22, "space": 0x20,
                "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
                "capslock": 0x14, "printscreen": 0x2C, "scrolllock": 0x91,
                "pause": 0x13, "numlock": 0x90,
                "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
                "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
                "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
            }
            key = event.get("k", "").lower()
            vk = _VK_MAP.get(key)
            if vk:
                _send_key_input(vk, 0)
                _send_key_input(vk, _KEYEVENTF_KEYUP)
            elif _WIN32_OK:
                try:
                    import pyautogui
                    pyautogui.press(key)
                except Exception:
                    pass

        elif t == "kc":
            # Combinações com modificadores
            _MOD_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "winleft": 0x5B}
            mods = event.get("mods", [])
            key  = event.get("k", "").lower()
            _VK_MAP2 = {
                "enter": 0x0D, "backspace": 0x08, "tab": 0x09, "escape": 0x1B,
                "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
                "pageup": 0x21, "pagedown": 0x22, "space": 0x20,
                "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
                "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
                "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
                "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
                "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
                "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
                "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
                "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
                "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
                "z": 0x5A,
                "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
                "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
            }
            mod_vks = [_MOD_VK[m] for m in mods if m in _MOD_VK]
            key_vk  = _VK_MAP2.get(key)
            if key_vk:
                for mv in mod_vks:  _send_key_input(mv, 0)
                _send_key_input(key_vk, 0)
                _send_key_input(key_vk, _KEYEVENTF_KEYUP)
                for mv in reversed(mod_vks): _send_key_input(mv, _KEYEVENTF_KEYUP)
            elif _WIN32_OK:
                try:
                    import pyautogui
                    pyautogui.hotkey(*[("winleft" if m == "win" else m) for m in mods], key)
                except Exception:
                    pass

        elif t == "paste":
            # CLIP-B2: cola texto recebido do bridge Ctrl+V do browser.
            # Hierarquia: pyperclip + SendInput → SetClipboardData → Unicode.
            text = event.get("text", "")
            if not text:
                return
            pasted = False
            try:
                import pyperclip
                pyperclip.copy(text)
                import time as _time; _time.sleep(0.05)
                _send_key_input(0x11, 0)
                _send_key_input(0x56, 0)
                _send_key_input(0x56, _KEYEVENTF_KEYUP)
                _send_key_input(0x11, _KEYEVENTF_KEYUP)
                pasted = True
            except Exception:
                pass
            if not pasted:
                try:
                    import time as _time
                    kernel32 = ctypes.windll.kernel32
                    user32   = ctypes.windll.user32
                    encoded  = (text + chr(0)).encode("utf-16-le")
                    h_mem = kernel32.GlobalAlloc(0x0002, len(encoded))
                    p_mem = kernel32.GlobalLock(h_mem)
                    ctypes.memmove(p_mem, encoded, len(encoded))
                    kernel32.GlobalUnlock(h_mem)
                    if user32.OpenClipboard(None):
                        user32.EmptyClipboard()
                        user32.SetClipboardData(13, h_mem)
                        user32.CloseClipboard()
                    _time.sleep(0.05)
                    _send_key_input(0x11, 0)
                    _send_key_input(0x56, 0)
                    _send_key_input(0x56, _KEYEVENTF_KEYUP)
                    _send_key_input(0x11, _KEYEVENTF_KEYUP)
                    pasted = True
                except Exception:
                    pass
            if not pasted:
                for c in text:
                    _send_unicode_input(c, key_up=False)
                    _send_unicode_input(c, key_up=True)

        elif t == "clipboard_req":
            # CLIP-B1: browser pediu clipboard apos Ctrl+C injetado
            _send_clipboard_to_browser(session_id)

        elif t == "clipboard_set_silent":
            # CLIP-B4: sincroniza clipboard do browser → Windows sem colar
            text = event.get("text", "")
            if text:
                try:
                    import pyperclip
                    pyperclip.copy(text)
                except Exception:
                    try:
                        kernel32 = ctypes.windll.kernel32
                        user32   = ctypes.windll.user32
                        encoded  = (text + chr(0)).encode("utf-16-le")
                        h_mem = kernel32.GlobalAlloc(0x0002, len(encoded))
                        p_mem = kernel32.GlobalLock(h_mem)
                        ctypes.memmove(p_mem, encoded, len(encoded))
                        kernel32.GlobalUnlock(h_mem)
                        if user32.OpenClipboard(None):
                            user32.EmptyClipboard()
                            user32.SetClipboardData(13, h_mem)
                            user32.CloseClipboard()
                    except Exception as e_cs:
                        logger.warning(f"clipboard_set_silent falhou: {e_cs}")

        elif t == "cad":
            try:
                sas = ctypes.WinDLL("sas.dll")
                sas.SendSAS(0)
                logger.info("CAD enviado via SendSAS")
            except Exception as cad_err:
                logger.warning(f"SendSAS falhou ({cad_err}), tentando Shell.WindowsSecurity...")
                try:
                    import subprocess
                    subprocess.run(
                        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                         "(New-Object -ComObject Shell.Application).WindowsSecurity()"],
                        timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except Exception as e2:
                    logger.error(f"CAD fallback falhou: {e2}")

    except Exception as e:
        logger.error(f"Input event error (t={t}): {e}")


def _send_clipboard_to_browser(session_id: str):
    # CLIP-B1: lê clipboard Windows e envia ao browser.
    # Hierarquia: pyperclip → GetClipboardData ctypes.
    text = ""
    try:
        import pyperclip
        text = pyperclip.paste() or ""
    except Exception:
        pass
    if not text:
        try:
            user32   = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if user32.OpenClipboard(None):
                h_mem = user32.GetClipboardData(13)   # CF_UNICODETEXT = 13
                if h_mem:
                    p_mem = kernel32.GlobalLock(h_mem)
                    if p_mem:
                        text = ctypes.wstring_at(p_mem)
                        kernel32.GlobalUnlock(h_mem)
                user32.CloseClipboard()
        except Exception as e_gc:
            logger.debug(f"GetClipboardData falhou: {e_gc}")
    if not text:
        return
    try:
        msg = json.dumps({"t": "clipboard", "text": text})
        with _webrtc_dc_lock:
            queue = _webrtc_data_channels.get(session_id)
        if queue:
            queue.put_nowait(msg)
    except Exception as e:
        logger.warning(f"_send_clipboard_to_browser falhou: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# File transfer
# ═════════════════════════════════════════════════════════════════════════════

def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or "arquivo_recebido"


def _resolve_dest_dir_tray(dest_key: str) -> Path:
    home  = Path.home()
    known = {"downloads": home / "Downloads", "desktop": home / "Desktop", "documents": home / "Documents"}
    if dest_key in known:
        return known[dest_key]
    if dest_key == "explorer":
        try:
            resp = requests.get("http://127.0.0.1:7070/explorer/path", timeout=3)
            if resp.ok:
                raw = resp.json().get("path", "")
                if raw and raw not in known:
                    p = Path(raw)
                    if p.is_absolute():
                        return p
                elif raw in known:
                    return known[raw]
        except Exception:
            pass
        return known["downloads"]
    if dest_key and (os.sep in dest_key or (len(dest_key) >= 3 and dest_key[1:3] == ":\\")):
        return Path(dest_key)
    return known["downloads"]


def _handle_file_chunk(data: bytes):
    """
    FIX P8: protocolo binário com prefixo de identificação.
    Formato: [2 bytes big-endian = len(fid)] [fid em UTF-8] [payload do chunk]

    Antes: iterava todos os buffers e jogava no primeiro ativo — com múltiplas
    sessões simultâneas, chunks de arquivos diferentes se misturavam.
    Agora: cada chunk carrega seu próprio fid, roteamento determinístico.
    """
    if len(data) < 3:
        logger.warning(f"file_chunk muito curto ({len(data)} bytes), ignorado")
        return
    fid_len = int.from_bytes(data[:2], "big")
    if len(data) < 2 + fid_len:
        logger.warning(f"file_chunk truncado (fid_len={fid_len}, total={len(data)}), ignorado")
        return
    fid   = data[2:2 + fid_len].decode("utf-8", errors="replace")
    chunk = data[2 + fid_len:]
    with _file_buffers_lock:
        buf = _file_buffers.get(fid)
        if buf and not buf.get("done"):
            buf["chunks"].append(chunk)
            buf["received"] = buf.get("received", 0) + len(chunk)
        else:
            logger.warning(f"file_chunk: fid '{fid}' não encontrado ou já finalizado")


def _handle_file_message(msg: dict, session_id: str):
    t = msg.get("t")
    if t == "file_start":
        fid = msg.get("id")
        if not fid: return
        with _file_buffers_lock:
            _file_buffers[fid] = {"meta": msg, "chunks": [], "received": 0, "done": False}
        logger.info(f"WebRTC file: iniciando '{msg.get('name')}' dest='{msg.get('dest', 'downloads')}'")
        return
    if t == "file_end":
        fid = msg.get("id")
        if not fid: return
        with _file_buffers_lock:
            buf = _file_buffers.get(fid)
            if not buf:
                logger.warning(f"WebRTC file: file_end para fid desconhecido '{fid}'")
                return
            buf["done"] = True
            data      = b"".join(buf["chunks"])
            file_name = buf["meta"].get("name", f"arquivo_{fid[:8]}")
            dest_key  = buf["meta"].get("dest", "downloads")
            _file_buffers.pop(fid, None)
        try:
            dest_dir  = _resolve_dest_dir_tray(dest_key)
            dest_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _sanitize_filename(file_name)
            dest_path = dest_dir / safe_name
            if dest_path.exists():
                stem, suffix = dest_path.stem, dest_path.suffix
                counter = 1
                while dest_path.exists():
                    dest_path = dest_dir / f"{stem} ({counter}){suffix}"
                    counter += 1
            dest_path.write_bytes(data)
            logger.info(f"WebRTC file: '{file_name}' salvo em '{dest_path}'")
            ack = json.dumps({"t": "file_done", "id": fid, "name": file_name, "path": str(dest_path)})
        except Exception as e:
            logger.error(f"WebRTC file erro ao salvar '{file_name}': {e}")
            ack = json.dumps({"t": "file_err", "id": fid, "reason": str(e)})
        with _webrtc_dc_lock:
            queue = _webrtc_data_channels.get(session_id)
        if queue:
            try: queue.put_nowait(ack)
            except Exception: pass


# ═════════════════════════════════════════════════════════════════════════════
# WebRTC offer handler
# ═════════════════════════════════════════════════════════════════════════════

def _rank_codecs(caps) -> list:
    def safe(codecs, keyword):
        return [c for c in codecs if c.mimeType and keyword in c.mimeType.lower()]
    vp8  = safe(caps.codecs, "vp8")
    vp9  = safe(caps.codecs, "vp9")
    h264 = safe(caps.codecs, "h264")
    ranked = vp8 + vp9 + h264
    logger.info(f"WebRTC codecs: VP8={len(vp8)} VP9={len(vp9)} H264={len(h264)} | usando: {ranked[0].mimeType if ranked else 'NENHUM'}")
    return ranked


def _fetch_ice_config() -> "RTCConfiguration":
    from aiortc import RTCConfiguration, RTCIceServer
    url = None
    try:
        resp = requests.get("http://127.0.0.1:7070/status", timeout=3)
        if resp.ok:
            url = resp.json().get("server_url", "").rstrip("/") + "/api/rdp/config/"
    except Exception:
        pass
    ice_servers = []
    if url:
        try:
            resp = requests.get(url, timeout=5, verify=False)
            if resp.ok:
                for srv in resp.json().get("ice_servers", []):
                    urls       = srv.get("urls", "")
                    if isinstance(urls, str): urls = [urls]
                    username   = srv.get("username")
                    credential = srv.get("credential")
                    if username and credential:
                        ice_servers.append(RTCIceServer(urls=urls, username=username, credential=credential))
                    else:
                        ice_servers.append(RTCIceServer(urls=urls))
                logger.info(f"WebRTC ICE: {len(ice_servers)} servidor(es) carregados de {url}")
        except Exception as e:
            logger.warning(f"WebRTC ICE: falha ao buscar config ({e}), sem ICE servers")
    return RTCConfiguration(iceServers=ice_servers) if ice_servers else RTCConfiguration()


def _handle_webrtc_offer(body: dict) -> dict:
    """
    Processa SDP offer e retorna SDP answer.

    FIX P6: usa loop global único (_get_or_create_webrtc_loop) em vez de
            criar um novo loop + thread por sessão.
    FIX P7: session_id gerado com uuid4() — sem risco de colisão por MD5.
    FIX P1: transceiver registrado em _active_transceivers[session_id].
    FIX P5: pc.close() chamado em on_state() ao desconectar.
    FIX P3: perfil "auto" sem maxBitrate — REMB livre.
    """
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription, RTCRtpSender
    except ImportError:
        raise RuntimeError("aiortc não instalado")

    sdp_str  = body.get("sdp", "")
    sdp_type = body.get("type", "offer")
    if not sdp_str or sdp_type != "offer":
        raise ValueError("SDP offer ausente ou tipo inválido")

    # FIX P7: uuid4 elimina colisão por MD5 de SDPs similares
    session_id = uuid.uuid4().hex[:16]

    async def negotiate() -> dict:
        pc    = RTCPeerConnection(configuration=_fetch_ice_config())

        # FIX LOG-B2: track criado DENTRO de negotiate, nunca reutilizado entre
        # tentativas. Se addTransceiver falha e pc fica em estado inconsistente,
        # a próxima chamada a negotiate() cria um pc E um track novos — o erro
        # "Track already has a sender" ocorria porque o track sobrevivia ao pc
        # que falhou e era passado para um novo pc na retentativa.
        track = ScreenTrack()
        track.__init__()

        @pc.on("icegatheringstatechange")
        async def on_ice_gathering():
            logger.info(f"WebRTC ICE gathering: {pc.iceGatheringState}")

        @pc.on("iceconnectionstatechange")
        async def on_ice_connection():
            logger.info(f"WebRTC ICE connection: {pc.iceConnectionState}")

        transceiver = None
        try:
            caps   = RTCRtpSender.getCapabilities("video")
            ranked = _rank_codecs(caps)
            transceiver = pc.addTransceiver(track, direction="sendonly")
            if ranked:
                transceiver.setCodecPreferences(ranked)

            # FIX LOG-B1: getParameters()/setParameters() não existe em versões
            # antigas do aiortc (< 1.5). Envolto em try separado para não
            # derrubar o addTransceiver que já foi bem-sucedido.
            # O REMB continua funcionando sem esses parâmetros iniciais.
            try:
                sender = transceiver.sender
                params = sender.getParameters()
                if params.encodings:
                    for enc in params.encodings:
                        enc.maxFramerate = 30   # sem maxBitrate → REMB livre
                    sender.setParameters(params)
            except AttributeError:
                logger.info("WebRTC: getParameters indisponível nesta versão do aiortc — REMB operando sem teto inicial")
            except Exception as ep:
                logger.warning(f"WebRTC: setParameters ignorado ({ep})")

        except Exception as e:
            logger.warning(f"WebRTC: addTransceiver falhou ({e}), tentando addTrack")
            try:
                pc.addTrack(track)
            except Exception as e2:
                # FIX LOG-B2: se addTrack também falhar (track com sender de pc
                # anterior), fecha o pc atual e relança para que run_coroutine_threadsafe
                # propague o erro ao caller — que devolve 500 ao browser.
                # O browser vai retentar com uma nova oferta SDP, que criará
                # um negotiate() completamente novo com track e pc frescos.
                logger.error(f"WebRTC: addTrack também falhou ({e2}) — pc descartado")
                try:
                    await pc.close()
                except Exception:
                    pass
                raise RuntimeError(f"Não foi possível adicionar track ao pc: {e2}") from e2

        # FIX P1: registra transceiver no dict global indexado por session_id
        if transceiver is not None:
            with _transceivers_lock:
                _active_transceivers[session_id] = transceiver
            logger.info(f"WebRTC: transceiver registrado para {session_id[:8]}")

        send_queue: asyncio.Queue = asyncio.Queue()
        with _webrtc_dc_lock:
            _webrtc_data_channels[session_id] = send_queue

        @pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"WebRTC: canal '{channel.label}' ({session_id[:8]}…)")

            @channel.on("message")
            def on_message(message):
                if channel.label == "input":
                    if isinstance(message, str):
                        try:
                            evt = json.loads(message)
                            if evt.get("t") == "list_monitors":
                                import mss as _mss
                                with _mss.mss() as sct:
                                    monitors = [
                                        {"id": i, "w": m["width"], "h": m["height"], "x": m["left"], "y": m["top"]}
                                        for i, m in enumerate(sct.monitors) if i > 0
                                    ]
                                channel.send(json.dumps({"t": "monitors_list", "monitors": monitors, "current": ScreenTrack._monitor_index}))
                                return
                            elif evt.get("t") == "switch_monitor":
                                idx = int(evt.get("index", 1))
                                import mss as _mss
                                with _mss.mss() as sct:
                                    count = len(sct.monitors) - 1
                                if 1 <= idx <= count:
                                    ScreenTrack._monitor_index = idx
                                    channel.send(json.dumps({"t": "monitor_switched", "index": idx}))
                                return
                            elif evt.get("t") == "set_quality":
                                quality = evt.get("quality", "auto")
                                # FIX P1: passa session_id, não transceiver
                                _apply_quality(session_id, quality)
                                channel.send(json.dumps({"t": "quality_applied", "quality": quality}))
                                return
                            threading.Thread(target=_handle_input_event, args=(evt, session_id), daemon=True).start()
                        except Exception:
                            pass
                elif channel.label == "files":
                    if isinstance(message, bytes):
                        # FIX P8: chunk com prefixo fid
                        _handle_file_chunk(message)
                    elif isinstance(message, str):
                        try:
                            threading.Thread(target=_handle_file_message, args=(json.loads(message), session_id), daemon=True).start()
                        except Exception:
                            pass

            async def drain_queue():
                while True:
                    try:
                        msg = await asyncio.wait_for(send_queue.get(), timeout=30)
                        if channel.readyState == "open":
                            channel.send(msg)
                    except asyncio.TimeoutError:
                        if channel.readyState == "open":
                            channel.send(json.dumps({"t": "ping", "ts": time.time()}))
                    except Exception:
                        break
            asyncio.ensure_future(drain_queue())

        # FIX P5: pc.close() ao desconectar — libera tracks, ICE, DTLS, GDI
        @pc.on("connectionstatechange")
        async def on_state():
            state = pc.connectionState
            logger.info(f"WebRTC: {session_id[:8]}… → {state}")
            if state in ("failed", "closed", "disconnected"):
                with _webrtc_dc_lock:
                    _webrtc_data_channels.pop(session_id, None)
                with _transceivers_lock:
                    _active_transceivers.pop(session_id, None)
                try:
                    await pc.close()
                    logger.info(f"WebRTC: pc fechado ({session_id[:8]})")
                except Exception as e:
                    logger.warning(f"WebRTC: pc.close() falhou ({e})")

        offer  = RTCSessionDescription(sdp=sdp_str, type=sdp_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        logger.info(f"WebRTC: SDP answer gerado ({session_id[:8]}…)")
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    # FIX P6: loop global compartilhado, não um loop por sessão
    loop = _get_or_create_webrtc_loop()
    future = asyncio.run_coroutine_threadsafe(negotiate(), loop)
    try:
        result = future.result(timeout=20)
    except Exception as e:
        logger.error(f"WebRTC negotiate falhou: {e}")
        raise
    return result


# ─────────────────────────────────────────────
# Servidor WebRTC local — 127.0.0.1:7071
# FIX P11: ThreadingHTTPServer em vez de HTTPServer
# ─────────────────────────────────────────────

class WebRTCLocalHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        logger.debug(f"WebRTC-local {fmt % args}")

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "version": VERSION})

        elif self.path == "/explorer/path":
            try:
                import subprocess
                ps = (
                    "try { $sh = New-Object -ComObject Shell.Application; "
                    "$w = $sh.Windows() | Where-Object { $_.Name -eq 'File Explorer' } | Select-Object -First 1; "
                    "if ($w) { $w.Document.Folder.Self.Path } else { '' } } catch { '' }"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                path = result.stdout.strip()
                self._send_json(200, {"path": path or "downloads"})
            except Exception:
                self._send_json(200, {"path": "downloads"})

        elif self.path == "/diag/mss":
            try:
                import mss as _mss
                import numpy as _np
                with _mss.mss() as sct:
                    mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    img = sct.grab(mon)
                    exp = img.width * img.height * 4
                    act = len(img.bgra)
                    try:
                        arr_np   = _np.array(img)
                        np_shape = list(arr_np.shape)
                        np_ok    = arr_np.shape == (img.height, img.width, 4)
                    except Exception as e:
                        arr_np = None; np_shape = str(e); np_ok = False
                    try:
                        arr_fb   = _np.frombuffer(img.bgra, dtype=_np.uint8).reshape(img.height, img.width, 4)
                        fb_ok    = True
                        fb_equal = _np.array_equal(arr_np, arr_fb) if np_ok else False
                    except Exception:
                        fb_ok = False; fb_equal = False
                    attrs = {}
                    for a in ["bgra", "pixels", "raw", "rgb", "rgba", "data"]:
                        if hasattr(img, a):
                            try:
                                v = getattr(img, a)
                                attrs[a] = len(v) if hasattr(v, "__len__") else str(v)
                            except Exception as e:
                                attrs[a] = f"erro: {e}"
                        else:
                            attrs[a] = "AUSENTE"
                    try:
                        import subprocess as _sp
                        r = _sp.run(
                            ["powershell", "-NoProfile", "-Command",
                             "(Get-CimInstance Win32_VideoController).DriverVersion"],
                            capture_output=True, text=True, timeout=5,
                            creationflags=_sp.CREATE_NO_WINDOW,
                        )
                        driver_ver = r.stdout.strip()
                    except Exception:
                        driver_ver = "indisponível"
                    self._send_json(200, {
                        "mss_version":          _mss.__version__,
                        "numpy_version":        _np.__version__,
                        "capture_method":       _detect_capture_method(),
                        "monitor":              mon,
                        "width":                img.width,
                        "height":               img.height,
                        "bgra_actual":          act,
                        "bgra_expected":        exp,
                        "stride_diff_bytes":    act - exp,
                        "stride_pad_per_line":  (act - exp) // img.height if act != exp else 0,
                        "np_array_shape":       np_shape,
                        "np_array_shape_ok":    np_ok,
                        "frombuffer_ok":        fb_ok,
                        "np_equals_frombuffer": fb_equal,
                        "attrs":                attrs,
                        "gpu_driver_version":   driver_ver,
                        "platform":             platform.platform(),
                        "active_sessions":      list(_webrtc_data_channels.keys()),
                        "active_transceivers":  list(_active_transceivers.keys()),
                        "diagnostico": (
                            "OK: np.array seguro"
                            if np_ok and fb_equal else
                            "STRIDE: np.array correto, frombuffer corrompido"
                            if np_ok and not fb_equal else
                            "CRITICO: np.array falhou, verificar fallbacks"
                        ),
                    })
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/webrtc/offer":
            body = self._read_json()
            try:
                result = _handle_webrtc_offer(body)
                self._send_json(200, result)
            except Exception as e:
                logger.exception(f"WebRTC offer error: {e}")
                self._send_json(500, {"error": str(e)})

        elif self.path == "/webrtc/close":
            body       = self._read_json()
            session_id = body.get("session_id", "")
            if session_id:
                with _webrtc_dc_lock:
                    _webrtc_data_channels.pop(session_id, None)
                with _transceivers_lock:
                    _active_transceivers.pop(session_id, None)
            self._send_json(200, {"ok": True})

        elif self.path == "/screen":
            body       = self._read_json()
            t          = body.get("t", "")
            session_id = body.get("session_id", "")
            if t == "screen_lock":
                threading.Thread(target=_do_screen_lock, args=(session_id,), daemon=True).start()
                self._send_json(200, {"ok": True})
            elif t == "screen_unlock":
                threading.Thread(target=_do_screen_unlock, args=(session_id,), daemon=True).start()
                self._send_json(200, {"ok": True})
            else:
                self._send_json(400, {"error": f"t inválido: {t}"})

        else:
            self._send_json(404, {"error": "not found"})


def start_webrtc_local_server():
    # FIX P11: ThreadingHTTPServer — /health responde durante SDP negotiation
    server = ThreadingHTTPServer(("127.0.0.1", WEBRTC_PORT), WebRTCLocalHandler)
    logger.info(f"WebRTC local server (threaded) listening on 127.0.0.1:{WEBRTC_PORT}")
    server.serve_forever()


# ─────────────────────────────────────────────
# Cliente IPC
# ─────────────────────────────────────────────

class IPCClient:
    _session = requests.Session()

    @classmethod
    def _get(cls, path, timeout=3):
        try:
            r = cls._session.get(f"{IPC_URL}{path}", timeout=timeout)
            return r.json() if r.ok else None
        except Exception:
            return None

    @classmethod
    def _post(cls, path, body=None, timeout=5):
        try:
            r = cls._session.post(f"{IPC_URL}{path}", json=body or {}, timeout=timeout)
            return r.json() if r.ok else None
        except Exception:
            return None

    @classmethod
    def get_status(cls):       return cls._get("/status")

    @classmethod
    def get_notifications(cls):
        data = cls._get("/notifications")
        return data.get("notifications", []) if data else []

    @classmethod
    def ack_notification(cls, notif_id): cls._post("/notifications/ack", {"id": notif_id})

    @classmethod
    def force_sync(cls):
        result = cls._post("/sync")
        return bool(result and result.get("ok"))

    @classmethod
    def is_service_running(cls): return cls._get("/ping", timeout=2) is not None

    @classmethod
    def run_command(cls, cmd_type, script, timeout=30):
        return cls._post("/command", {"type": cmd_type, "script": script, "timeout": timeout})


# ─────────────────────────────────────────────
# Janela de Status
# ─────────────────────────────────────────────

class StatusWindow:
    _instance = None

    @classmethod
    def open(cls, tray_app):
        if cls._instance and cls._instance.alive:
            cls._instance.window.lift()
            return
        cls._instance = cls(tray_app)

    def __init__(self, tray_app):
        self.tray_app = tray_app
        self.alive    = True
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        self.window = tk.Tk()
        self.window.title("Inventory Agent — Status")
        self.window.geometry("440x360")
        self.window.resizable(False, False)
        self.window.configure(bg="#0f172a")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        header = tk.Frame(self.window, bg="#1e293b", pady=16, padx=20)
        header.pack(fill=tk.X)
        tk.Label(header, text="Inventory Agent", fg="white", bg="#1e293b", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        tk.Label(header, text=f"v{VERSION}", fg="#64748b", bg="#1e293b", font=("Segoe UI", 9)).pack(side=tk.RIGHT)
        body = tk.Frame(self.window, bg="#0f172a", padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)
        def row(label, default="—"):
            f = tk.Frame(body, bg="#0f172a")
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, fg="#64748b", bg="#0f172a", font=("Segoe UI", 9), width=18, anchor="w").pack(side=tk.LEFT)
            val = tk.Label(f, text=default, fg="#e2e8f0", bg="#0f172a", font=("Segoe UI", 9, "bold"), anchor="w")
            val.pack(side=tk.LEFT)
            return val
        self.lbl_status  = row("Status serviço")
        self.lbl_machine = row("Máquina")
        self.lbl_checkin = row("Último check-in")
        self.lbl_notif   = row("Notif. pendentes")
        self.lbl_webrtc  = row("Sessões WebRTC")
        self.lbl_version = row("Versão")
        self.lbl_error   = row("Último erro")
        btn_frame = tk.Frame(self.window, bg="#1e293b", pady=12, padx=20)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        def btn(parent, text, cmd, accent="#334155"):
            b = tk.Button(parent, text=text, command=cmd, bg=accent, fg="white", relief="flat", font=("Segoe UI", 9), padx=12, pady=6)
            b.pack(side=tk.LEFT, padx=4)
            return b
        btn(btn_frame, "⚡ Sync agora", self._sync, "#0369a1")
        btn(btn_frame, "📄 Logs",       self._open_logs)
        self._refresh()
        self.window.mainloop()

    def _refresh(self):
        if not self.alive: return
        status = IPCClient.get_status()
        if status:
            online = status.get("online", False)
            self.lbl_status.config(text="🟢 Online" if online else "🔴 Offline", fg="#4ade80" if online else "#f87171")
            self.lbl_machine.config(text=status.get("machine", "—"))
            checkin = status.get("last_checkin")
            self.lbl_checkin.config(text=checkin[:19].replace("T", " ") if checkin else "—")
            self.lbl_notif.config(text=str(status.get("pending_notifications", 0)))
            self.lbl_version.config(text=status.get("version", VERSION))
            err = status.get("last_error", "")
            self.lbl_error.config(text=(err[:40] + "…") if len(err) > 40 else (err or "Nenhum"), fg="#f87171" if err else "#4ade80")
            self.lbl_webrtc.config(text=str(len(_webrtc_data_channels)), fg="#4ade80" if _webrtc_data_channels else "#64748b")
        else:
            self.lbl_status.config(text="⚫ Serviço offline", fg="#94a3b8")
        self.window.after(5000, self._refresh)

    def _sync(self):
        ok = IPCClient.force_sync()
        ToastNotification.show(title="Sync", message="Sincronização iniciada!" if ok else "Serviço não respondeu.", notif_type="success" if ok else "error", duration=5)

    def _open_logs(self):
        try:
            if platform.system() == "Windows": os.startfile(str(LOG_DIR))
        except Exception as e:
            logger.error(e)

    def _on_close(self):
        self.alive = False
        StatusWindow._instance = None
        self.window.destroy()


# ─────────────────────────────────────────────
# Janela de Chamados
# ─────────────────────────────────────────────

class ChamadosWindow:
    _instance = None

    @classmethod
    def open(cls, server_url, token_hash):
        if cls._instance and cls._instance.alive:
            cls._instance.window.lift()
            return
        cls._instance = cls(server_url, token_hash)

    def __init__(self, server_url, token_hash):
        self.server_url = server_url.rstrip("/")
        self.token_hash = token_hash
        self.alive      = True
        self._tickets   = []
        self._selected  = None
        self._historico = []
        self._email     = os.environ.get("AGENT_USER_EMAIL", "")
        threading.Thread(target=self._build, daemon=True).start()

    def _headers(self):
        return {"Authorization": f"Bearer {self.token_hash}", "Content-Type": "application/json"}

    def _api_get(self, path, params=None):
        r = requests.get(f"{self.server_url}{path}", headers=self._headers(), params=params, timeout=10, verify=False)
        r.raise_for_status()
        return r.json()

    def _api_post(self, path, body):
        r = requests.post(f"{self.server_url}{path}", headers=self._headers(), json=body, timeout=10, verify=False)
        r.raise_for_status()
        return r.json()

    def _build(self):
        win = tk.Tk()
        self.window = win
        win.title("Meus Chamados")
        win.geometry("980x640")
        win.minsize(800, 520)
        win.configure(bg="#f1f5f9")
        win.protocol("WM_DELETE_WINDOW", self._on_close)
        main    = tk.Frame(win, bg="#f1f5f9")
        main.pack(fill=tk.BOTH, expand=True)
        sidebar = tk.Frame(main, bg="#1e293b", width=290)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        hdr = tk.Frame(sidebar, bg="#0f172a", pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="🎫  Chamados", font=("Segoe UI", 12, "bold"), bg="#0f172a", fg="#f8fafc").pack(side=tk.LEFT, padx=14)
        tk.Button(hdr, text="+ Novo", font=("Segoe UI", 9, "bold"), bg="#1a73e8", fg="white", relief=tk.FLAT, padx=10, pady=4, cursor="hand2", command=self._abrir_novo_ticket).pack(side=tk.RIGHT, padx=10)
        email_frm = tk.Frame(sidebar, bg="#1e293b", pady=6, padx=10)
        email_frm.pack(fill=tk.X)
        tk.Label(email_frm, text="Seu e-mail:", font=("Segoe UI", 8), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.email_var = tk.StringVar(value=self._email)
        tk.Entry(email_frm, textvariable=self.email_var, font=("Segoe UI", 9), bg="#334155", fg="white", insertbackground="white", relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#475569").pack(fill=tk.X, pady=(2, 4))
        tk.Button(email_frm, text="🔄  Carregar chamados", font=("Segoe UI", 8), bg="#334155", fg="#94a3b8", relief=tk.FLAT, pady=4, cursor="hand2", command=self._carregar_tickets).pack(fill=tk.X)
        lista_frm = tk.Frame(sidebar, bg="#1e293b")
        lista_frm.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        sb = tk.Scrollbar(lista_frm, orient=tk.VERTICAL, bg="#334155", troughcolor="#1e293b", bd=0)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lista_canvas = tk.Canvas(lista_frm, bg="#1e293b", bd=0, highlightthickness=0, yscrollcommand=sb.set)
        self.lista_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lista_canvas.yview)
        self.lista_inner = tk.Frame(self.lista_canvas, bg="#1e293b")
        self.lista_canvas.create_window((0, 0), window=self.lista_inner, anchor="nw")
        self.lista_inner.bind("<Configure>", lambda e: self.lista_canvas.configure(scrollregion=self.lista_canvas.bbox("all")))
        content = tk.Frame(main, bg="#f1f5f9")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.ticket_hdr = tk.Frame(content, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0")
        self.ticket_hdr.pack(fill=tk.X)
        self.lbl_assunto = tk.Label(self.ticket_hdr, text="← Selecione um chamado na lista", font=("Segoe UI", 12, "bold"), bg="#ffffff", fg="#1e293b", pady=14, padx=20, anchor="w")
        self.lbl_assunto.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_status_ticket = tk.Label(self.ticket_hdr, text="", font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#64748b", padx=16)
        self.lbl_status_ticket.pack(side=tk.RIGHT)
        hist_wrap = tk.Frame(content, bg="#f1f5f9")
        hist_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(10, 0))
        hist_sb = tk.Scrollbar(hist_wrap, orient=tk.VERTICAL)
        hist_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.hist_canvas = tk.Canvas(hist_wrap, bg="#f1f5f9", bd=0, highlightthickness=0, yscrollcommand=hist_sb.set)
        self.hist_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_sb.config(command=self.hist_canvas.yview)
        self.hist_inner = tk.Frame(self.hist_canvas, bg="#f1f5f9")
        self.hist_canvas.create_window((0, 0), window=self.hist_inner, anchor="nw")
        self.hist_inner.bind("<Configure>", lambda e: self.hist_canvas.configure(scrollregion=self.hist_canvas.bbox("all")))
        reply_frm = tk.Frame(content, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0")
        reply_frm.pack(fill=tk.X, padx=14, pady=10)
        tk.Label(reply_frm, text="Responder:", font=("Segoe UI", 9, "bold"), bg="#ffffff", fg="#374151").pack(anchor="w", padx=12, pady=(8, 2))
        self.reply_text = tk.Text(reply_frm, height=4, font=("Segoe UI", 10), relief=tk.FLAT, bg="#f8fafc", bd=0, highlightthickness=1, highlightbackground="#e2e8f0", padx=10, pady=8)
        self.reply_text.pack(fill=tk.X, padx=12, pady=(0, 6))
        self._placeholder_text = "Digite sua resposta aqui…"
        self.reply_text.insert("1.0", self._placeholder_text)
        self.reply_text.config(fg="#9ca3af")
        self.reply_text.bind("<FocusIn>",  self._reply_focus_in)
        self.reply_text.bind("<FocusOut>", self._reply_focus_out)
        tk.Button(reply_frm, text="Enviar Resposta  ➤", font=("Segoe UI", 9, "bold"), bg="#1a73e8", fg="white", relief=tk.FLAT, padx=16, pady=6, cursor="hand2", command=self._enviar_resposta).pack(anchor="e", padx=12, pady=(0, 10))
        win.after(200, self._carregar_tickets)
        win.mainloop()

    def _reply_focus_in(self, _e):
        if self.reply_text.get("1.0", tk.END).strip() == self._placeholder_text:
            self.reply_text.delete("1.0", tk.END)
            self.reply_text.config(fg="#1e293b")

    def _reply_focus_out(self, _e):
        if not self.reply_text.get("1.0", tk.END).strip():
            self.reply_text.insert("1.0", self._placeholder_text)
            self.reply_text.config(fg="#9ca3af")

    def _carregar_tickets(self):
        email = self.email_var.get().strip()
        if not email: return
        self._email = email
        def fetch():
            try:
                data = self._api_get("/tickets/api/agent/list/", params={"email": email})
                self.window.after(0, lambda: self._render_lista(data.get("tickets", [])))
            except Exception as ex:
                logger.error(f"Erro ao carregar tickets: {ex}")
                ToastNotification.show(title="Erro", message=f"Não foi possível carregar chamados: {ex}", notif_type="error", duration=5)
        threading.Thread(target=fetch, daemon=True).start()

    def _render_lista(self, tickets):
        self._tickets = tickets
        for w in self.lista_inner.winfo_children(): w.destroy()
        if not tickets:
            tk.Label(self.lista_inner, text="Nenhum chamado encontrado.", font=("Segoe UI", 9, "italic"), bg="#1e293b", fg="#64748b", pady=24).pack()
            return
        for t in tickets: self._render_ticket_card(t)
        if tickets and self._selected is None: self._selecionar_ticket(tickets[0])

    def _render_ticket_card(self, t):
        is_sel  = self._selected and self._selected["id"] == t["id"]
        bg_base = "#2d4a7a" if is_sel else "#1e293b"
        bg_hvr  = "#253352"
        cor     = t.get("status_cor", "#64748b")
        card = tk.Frame(self.lista_inner, bg=bg_base, cursor="hand2", highlightthickness=0)
        card.pack(fill=tk.X, padx=0, pady=1)
        tk.Frame(card, bg=cor, width=4).pack(side=tk.LEFT, fill=tk.Y)
        body = tk.Frame(card, bg=bg_base, padx=10, pady=10)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(body, text=f"#{t['numero']}", font=("Segoe UI", 8, "bold"), bg=bg_base, fg="#94a3b8", anchor="w").pack(fill=tk.X)
        assunto_txt = t["assunto"][:44] + ("…" if len(t["assunto"]) > 44 else "")
        tk.Label(body, text=assunto_txt, font=("Segoe UI", 9, "bold"), bg=bg_base, fg="#f1f5f9", anchor="w", wraplength=238).pack(fill=tk.X)
        meta = tk.Frame(body, bg=bg_base)
        meta.pack(fill=tk.X, pady=(4, 0))
        tk.Label(meta, text=t["status"],     font=("Segoe UI", 8), bg=bg_base, fg=cor,      anchor="w").pack(side=tk.LEFT)
        tk.Label(meta, text=t["criado_em"],  font=("Segoe UI", 7), bg=bg_base, fg="#64748b", anchor="e").pack(side=tk.RIGHT)
        all_w = [card, body, meta] + body.winfo_children() + meta.winfo_children()
        def on_click(_e, ticket=t): self._selecionar_ticket(ticket)
        def on_enter(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in all_w:
                    try: w.config(bg=bg_hvr)
                    except Exception: pass
        def on_leave(_e):
            if not (self._selected and self._selected["id"] == t["id"]):
                for w in all_w:
                    try: w.config(bg="#1e293b")
                    except Exception: pass
        for w in all_w:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>",    on_enter)
            w.bind("<Leave>",    on_leave)

    def _selecionar_ticket(self, ticket):
        self._selected = ticket
        self.lbl_assunto.config(text=f"#{ticket['numero']}  —  {ticket['assunto']}")
        self.lbl_status_ticket.config(text=ticket["status"])
        self._render_lista(self._tickets)
        def fetch():
            try:
                data = self._api_get(f"/tickets/api/agent/{ticket['id']}/")
                self.window.after(0, lambda: self._render_historico(data.get("historico", [])))
            except Exception as ex:
                logger.error(f"Erro ao carregar histórico: {ex}")
        threading.Thread(target=fetch, daemon=True).start()

    def _render_historico(self, historico):
        self._historico = historico
        for w in self.hist_inner.winfo_children(): w.destroy()
        if not historico:
            tk.Label(self.hist_inner, text="Nenhuma mensagem ainda. Seja o primeiro a responder!", font=("Segoe UI", 9, "italic"), bg="#f1f5f9", fg="#94a3b8", pady=24).pack()
            return
        for acao in historico: self._render_balao(acao)
        self.hist_canvas.update_idletasks()
        self.hist_canvas.yview_moveto(0)

    def _render_balao(self, acao):
        is_staff = acao.get("is_staff", False)
        bg_msg   = "#1a73e8" if is_staff else "#ffffff"
        fg_msg   = "#ffffff"  if is_staff else "#1e293b"
        anchor   = "e" if is_staff else "w"
        outer = tk.Frame(self.hist_inner, bg="#f1f5f9")
        outer.pack(fill=tk.X, padx=12, pady=5)
        meta = tk.Frame(outer, bg="#f1f5f9")
        meta.pack(fill=tk.X)
        if is_staff:
            tk.Label(meta, text=acao["criado_em"], font=("Segoe UI", 7), bg="#f1f5f9", fg="#94a3b8").pack(side=tk.LEFT,  padx=4)
            tk.Label(meta, text=acao["autor"],     font=("Segoe UI", 8, "bold"), bg="#f1f5f9", fg="#475569").pack(side=tk.RIGHT)
        else:
            tk.Label(meta, text=acao["autor"],     font=("Segoe UI", 8, "bold"), bg="#f1f5f9", fg="#475569").pack(side=tk.LEFT)
            tk.Label(meta, text=acao["criado_em"], font=("Segoe UI", 7), bg="#f1f5f9", fg="#94a3b8").pack(side=tk.RIGHT, padx=4)
        tk.Label(outer, text=acao["conteudo"], font=("Segoe UI", 10), bg=bg_msg, fg=fg_msg, wraplength=520, justify=tk.LEFT, anchor="w", padx=14, pady=10, relief=tk.FLAT).pack(anchor=anchor, pady=(2, 0))

    def _enviar_resposta(self):
        if not self._selected:
            ToastNotification.show(title="Aviso", message="Selecione um chamado antes de responder.", notif_type="warning", duration=4)
            return
        conteudo = self.reply_text.get("1.0", tk.END).strip()
        if not conteudo or conteudo == self._placeholder_text: return
        email = self.email_var.get().strip()
        def send():
            try:
                data = self._api_post(f"/tickets/api/agent/{self._selected['id']}/reply/", {"email": email, "conteudo": conteudo})
                if data.get("ok"):
                    self.window.after(0, lambda: self._append_acao(data["acao"]))
                    self.window.after(0, self._limpar_reply)
                    ToastNotification.show(title="Resposta enviada", message=f"Ticket #{self._selected['numero']} atualizado.", notif_type="success", duration=4)
                else:
                    ToastNotification.show(title="Erro", message=data.get("error", "Erro desconhecido"), notif_type="error", duration=5)
            except Exception as ex:
                logger.error(f"Erro ao responder: {ex}")
                ToastNotification.show(title="Erro", message=str(ex), notif_type="error", duration=5)
        threading.Thread(target=send, daemon=True).start()

    def _append_acao(self, acao):
        self._historico.insert(0, acao)
        for w in self.hist_inner.winfo_children(): w.destroy()
        for a in self._historico: self._render_balao(a)
        self.hist_canvas.update_idletasks()
        self.hist_canvas.yview_moveto(0)

    def _limpar_reply(self):
        self.reply_text.delete("1.0", tk.END)
        self.reply_text.insert("1.0", self._placeholder_text)
        self.reply_text.config(fg="#9ca3af")

    def _abrir_novo_ticket(self):
        NovoTicketModal(self)

    def _on_close(self):
        self.alive = False
        ChamadosWindow._instance = None
        self.window.destroy()


# ─────────────────────────────────────────────
# Modal: Novo Ticket
# ─────────────────────────────────────────────

class NovoTicketModal:
    def __init__(self, parent: ChamadosWindow):
        self.parent = parent
        win = tk.Toplevel(parent.window)
        self.window = win
        win.title("Abrir Novo Chamado")
        win.geometry("460x420")
        win.resizable(False, False)
        win.configure(bg="#f8fafc")
        win.grab_set()
        pad = {"padx": 18, "pady": 3}
        tk.Label(win, text="Novo Chamado", font=("Segoe UI", 13, "bold"), bg="#f8fafc", fg="#0f172a").pack(pady=(16, 8))
        def lbl(text):
            tk.Label(win, text=text, font=("Segoe UI", 9), bg="#f8fafc", fg="#374151", anchor="w").pack(fill=tk.X, **pad)
        def entry_var():
            var = tk.StringVar()
            tk.Entry(win, textvariable=var, font=("Segoe UI", 10), relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#d1d5db", bg="#ffffff").pack(fill=tk.X, padx=18, pady=(0, 6))
            return var
        lbl("E-mail do solicitante *")
        self.email_var = entry_var()
        self.email_var.set(parent.email_var.get())
        lbl("Tipo do chamado (Serviço)  — opcional")
        self.tipo_var = entry_var()
        lbl("Assunto *")
        self.assunto_var = entry_var()
        lbl("Descrição *")
        self.desc_widget = tk.Text(win, height=5, font=("Segoe UI", 10), relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#d1d5db", bg="#ffffff", padx=8, pady=6)
        self.desc_widget.pack(fill=tk.X, padx=18, pady=(0, 10))
        btns = tk.Frame(win, bg="#f8fafc")
        btns.pack(fill=tk.X, padx=18, pady=6)
        tk.Button(btns, text="Cancelar", command=win.destroy, font=("Segoe UI", 10), bg="#e5e7eb", relief=tk.FLAT, padx=12, pady=6).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btns, text="Abrir Chamado", command=self._submit, font=("Segoe UI", 10, "bold"), bg="#1a73e8", fg="white", relief=tk.FLAT, padx=12, pady=6).pack(side=tk.RIGHT)

    def _submit(self):
        from tkinter import messagebox
        email     = self.email_var.get().strip()
        tipo      = self.tipo_var.get().strip()
        assunto   = self.assunto_var.get().strip()
        descricao = self.desc_widget.get("1.0", tk.END).strip()
        if not email or not assunto or not descricao:
            messagebox.showerror("Campos obrigatórios", "Preencha: E-mail, Assunto e Descrição.")
            return
        def send():
            try:
                data = self.parent._api_post("/tickets/api/agent/criar/", {"email_solicitante": email, "tipo_chamado": tipo, "assunto": assunto, "descricao": descricao})
                if data.get("ok"):
                    ToastNotification.show(title="Chamado aberto!", message=f"Ticket #{data['numero']} criado com sucesso.", notif_type="success", duration=5)
                    self.window.after(0, self.window.destroy)
                    self.parent.window.after(500, self.parent._carregar_tickets)
                else:
                    ToastNotification.show(title="Erro", message=data.get("error", "Erro desconhecido"), notif_type="error", duration=5)
            except Exception as ex:
                logger.error(f"NovoTicket erro: {ex}")
                ToastNotification.show(title="Erro", message=str(ex), notif_type="error", duration=5)
        threading.Thread(target=send, daemon=True).start()


# ─────────────────────────────────────────────
# Ícone do System Tray
# ─────────────────────────────────────────────

class TrayIcon:
    STATUS_COLORS = {
        "online":  (34, 197, 94),
        "offline": (239, 68, 68),
        "unknown": (148, 163, 184),
    }

    def __init__(self):
        self.icon         = None
        self._status      = "unknown"
        self._notif_count = 0

    def _make_image(self, status):
        size  = 64
        img   = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(img)
        color = self.STATUS_COLORS.get(status, self.STATUS_COLORS["unknown"])
        draw.ellipse([6, 6, 58, 58], fill=color + (255,))
        draw.ellipse([6, 6, 58, 58], outline=(255, 255, 255, 180), width=3)
        if self._notif_count > 0:
            draw.ellipse([40, 2, 62, 24], fill=(239, 68, 68, 255))
            draw.text((47, 4), str(min(self._notif_count, 9)), fill="white")
        return img

    def update_status(self, status, notif_count=0):
        self._status      = status
        self._notif_count = notif_count
        if self.icon:
            self.icon.icon  = self._make_image(status)
            label           = {"online": "Online", "offline": "Offline"}.get(status, "...")
            notif_str       = f" ({notif_count} notif)" if notif_count else ""
            self.icon.title = f"Inventory Agent — {label}{notif_str}"

    def _build_menu(self):
        return pystray.Menu(
            item("📊 Status",      lambda i, it: StatusWindow.open(self)),
            item("🎫 Chamados",    lambda i, it: self._open_chamados(), default=True),
            item("⚡ Forçar Sync", lambda i, it: self._force_sync()),
            pystray.Menu.SEPARATOR,
            item("❌ Sair",        lambda i, it: self._quit()),
        )

    def _open_chamados(self):
        status = IPCClient.get_status()
        if not status:
            logger.warning("Chamados: agent_service não respondeu via IPC")
            return
        server_url  = status.get("server_url", "").rstrip("/")
        token_hash  = status.get("token_hash", "")
        logged_user = status.get("logged_user", "")
        if not server_url or not token_hash:
            logger.warning(f"Chamados: server_url={server_url!r} token_hash={'presente' if token_hash else 'AUSENTE'}")
            return
        ChamadosManager.open(server_url=server_url, token_hash=token_hash, logged_user=logged_user, machine_name=status.get("machine", ""))

    def _force_sync(self):
        ok = IPCClient.force_sync()
        ToastNotification.show(title="Sync", message="Sincronização iniciada!" if ok else "Serviço indisponível.", notif_type="success" if ok else "error", duration=5)

    def _open_logs(self):
        try:
            if platform.system() == "Windows": os.startfile(str(LOG_DIR))
        except Exception as e:
            logger.error(e)

    def _quit(self):
        logger.info("Tray encerrado pelo usuário")
        if self.icon: self.icon.stop()

    def _on_click(self, icon, event):
        try:
            is_double = getattr(event, "double", False)
        except Exception:
            is_double = False
        if not is_double and event != "double": return
        threading.Thread(target=self._open_chamados, daemon=True).start()

    def run(self):
        self.icon = pystray.Icon(
            "inventory_agent",
            self._make_image("unknown"),
            "Inventory Agent",
            self._build_menu(),
            on_clicked=self._on_click,
        )
        threading.Thread(target=self._poll_loop,           daemon=True, name="poll").start()
        threading.Thread(target=start_webrtc_local_server, daemon=True, name="webrtc-local").start()
        logger.info(f"Tray iniciado | WebRTC local em 127.0.0.1:{WEBRTC_PORT}")
        self.icon.run()

    def _poll_loop(self):
        while True:
            try:
                status = IPCClient.get_status()
                if status:
                    s = "online" if status.get("online") else "offline"
                    self.update_status(s, status.get("pending_notifications", 0))
                    for notif in IPCClient.get_notifications():
                        self._show_notification(notif)
                        IPCClient.ack_notification(notif.get("id"))
                else:
                    self.update_status("unknown")
            except Exception as e:
                logger.error(f"Erro no poll: {e}")
                self.update_status("unknown")
            time.sleep(POLL_INTERVAL)

    def _show_notification(self, notif):
        notif_type = notif.get("type", "info")
        if notif_type not in ("info", "success", "warning", "error", "alert"):
            notif_type = "info"
        ToastNotification.show(
            title=notif.get("title", "Notificação"),
            message=notif.get("message", ""),
            notif_type=notif_type,
            duration=notif.get("duration", 360),
            action_label=notif.get("action_label"),
            action_callback=None,
        )
        logger.info(f"Notificação exibida: {notif.get('title')}")


# ─────────────────────────────────────────────
# Ponto de entrada
# ─────────────────────────────────────────────

def main():
    logger.info(f"=== AgentTray v{VERSION} iniciando ===")
    logger.info(f"WebRTC local: 127.0.0.1:{WEBRTC_PORT}")
    if not _WIN32_OK:
        logger.error("pywin32 não encontrado — controle remoto de input desabilitado. Execute: pip install pywin32")
    if not IPCClient.is_service_running():
        logger.warning("Serviço não detectado em 127.0.0.1:7070.")
    TrayIcon().run()


if __name__ == "__main__":
    main()