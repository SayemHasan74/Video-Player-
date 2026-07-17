"""Windows custom-frame and live aspect-lock primitives."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_DWMCOMPOSITIONCHANGED = 0x031E
WM_SIZING = 0x0214

HTCLIENT = 1
HTCAPTION = 2
HTMINBUTTON = 8
HTMAXBUTTON = 9
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTCLOSE = 20

WMSZ_LEFT = 1
WMSZ_RIGHT = 2
WMSZ_TOP = 3
WMSZ_TOPLEFT = 4
WMSZ_TOPRIGHT = 5
WMSZ_BOTTOM = 6
WMSZ_BOTTOMLEFT = 7
WMSZ_BOTTOMRIGHT = 8

WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
GWL_STYLE = -16
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

SM_CXBORDER = 5
SM_CXFRAME = 32
SM_CYFRAME = 33
SM_CXPADDEDBORDER = 92


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


MSG = wintypes.MSG


class MARGINS(ctypes.Structure):
    _fields_ = (
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    )


def native_message(message: object) -> MSG:
    # PyQt supplies a sip.voidptr to the platform MSG. ``from_address`` is the
    # supported zero-copy view; casting the sip pointer through POINTER(MSG)
    # can leave a temporary ctypes pointer involved during Qt re-entrancy.
    return MSG.from_address(int(message))


def signed_word(value: int) -> int:
    return ctypes.c_short(value & 0xFFFF).value


def point_from_lparam(lparam: int) -> tuple[int, int]:
    return signed_word(lparam), signed_word(lparam >> 16)


def classify_resize_border(
    x: int,
    y: int,
    width: int,
    height: int,
    frame_x: int,
    frame_y: int,
    diagonal: int,
) -> int | None:
    """Classify one physical-pixel point into a native resize region."""
    left = x < frame_x
    right = x >= width - frame_x
    top = y < frame_y
    bottom = y >= height - frame_y
    diagonal_left = x < diagonal
    diagonal_right = x >= width - diagonal
    diagonal_top = y < diagonal
    diagonal_bottom = y >= height - diagonal

    # Corners deliberately extend farther along either adjoining edge than a
    # plain edge. At least one axis must still be inside the real frame.
    if (top and diagonal_left) or (left and diagonal_top):
        return HTTOPLEFT
    if (top and diagonal_right) or (right and diagonal_top):
        return HTTOPRIGHT
    if (bottom and diagonal_left) or (left and diagonal_bottom):
        return HTBOTTOMLEFT
    if (bottom and diagonal_right) or (right and diagonal_bottom):
        return HTBOTTOMRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    return None


def dpi_aware_resize_hit_test(hwnd: int, screen_x: int, screen_y: int) -> int | None:
    """Return a DPI-correct Win32 resize hit code, or None for client content."""
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    handle = wintypes.HWND(hwnd)
    is_zoomed = user32.IsZoomed
    is_zoomed.argtypes = (wintypes.HWND,)
    is_zoomed.restype = wintypes.BOOL
    if is_zoomed(handle):
        return HTCLIENT

    get_dpi = user32.GetDpiForWindow
    get_dpi.argtypes = (wintypes.HWND,)
    get_dpi.restype = wintypes.UINT
    get_metric = user32.GetSystemMetricsForDpi
    get_metric.argtypes = (ctypes.c_int, wintypes.UINT)
    get_metric.restype = ctypes.c_int
    get_window_rect = user32.GetWindowRect
    get_window_rect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
    get_window_rect.restype = wintypes.BOOL

    dpi = int(get_dpi(handle))
    rect = RECT()
    if dpi <= 0 or not get_window_rect(handle, ctypes.byref(rect)):
        return None
    frame_x = int(get_metric(SM_CXFRAME, dpi)) + int(
        get_metric(SM_CXPADDEDBORDER, dpi)
    )
    frame_y = int(get_metric(SM_CYFRAME, dpi)) + int(
        get_metric(SM_CXPADDEDBORDER, dpi)
    )
    diagonal = frame_x * 2 + int(get_metric(SM_CXBORDER, dpi))
    return classify_resize_border(
        int(screen_x - rect.left),
        int(screen_y - rect.top),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
        max(1, frame_x),
        max(1, frame_y),
        max(1, diagonal),
    )


def enable_dwm_custom_frame(hwnd: int) -> bool:
    """Restore native frame capabilities and extend DWM into the client area."""
    if os.name != "nt":
        return False
    # Unit tests and headless tools can run on Windows with Qt's offscreen
    # backend. Its synthetic winIds are not Win32 HWNDs and must never be
    # passed to user32/dwmapi.
    from PyQt6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is not None and QGuiApplication.platformName().lower() != "windows":
        return False
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    handle = wintypes.HWND(hwnd)
    is_window = user32.IsWindow
    is_window.argtypes = (wintypes.HWND,)
    is_window.restype = wintypes.BOOL
    if not is_window(handle):
        return False
    # GWL_STYLE is a 32-bit value even in a 64-bit process. Using the LONG
    # API avoids LONG_PTR sign/width ambiguity for the WS_POPUP high bit.
    get_style = user32.GetWindowLongW
    set_style = user32.SetWindowLongW
    get_style.argtypes = (wintypes.HWND, ctypes.c_int)
    get_style.restype = ctypes.c_long
    set_style.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
    set_style.restype = ctypes.c_long
    extend_frame = dwmapi.DwmExtendFrameIntoClientArea
    extend_frame.argtypes = (wintypes.HWND, ctypes.POINTER(MARGINS))
    extend_frame.restype = ctypes.c_long
    set_window_pos = user32.SetWindowPos
    set_window_pos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    set_window_pos.restype = wintypes.BOOL
    style = ctypes.c_uint32(get_style(handle, GWL_STYLE)).value
    style |= WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
    set_style(handle, GWL_STYLE, ctypes.c_long(style).value)
    margins = MARGINS(1, 1, 1, 1)
    result = extend_frame(handle, ctypes.byref(margins))
    set_window_pos(
        handle,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )
    return result == 0


def correct_sizing_rect(
    rect: RECT,
    edge: int,
    aspect: float,
    extra_width: int,
    extra_height: int,
    minimum_width: int,
    minimum_height: int,
) -> None:
    """Correct a live WM_SIZING rectangle in place around the video content."""
    if aspect <= 0:
        return
    width = max(minimum_width, int(rect.right - rect.left))
    height = max(minimum_height, int(rect.bottom - rect.top))
    from_width_height = max(
        minimum_height,
        round(max(1, width - extra_width) / aspect) + extra_height,
    )
    from_height_width = max(
        minimum_width,
        round(max(1, height - extra_height) * aspect) + extra_width,
    )
    horizontal_edge = edge in {WMSZ_LEFT, WMSZ_RIGHT}
    vertical_edge = edge in {WMSZ_TOP, WMSZ_BOTTOM}
    if horizontal_edge or (
        not vertical_edge and abs(from_width_height - height) <= abs(from_height_width - width)
    ):
        target_width, target_height = width, from_width_height
    else:
        target_width, target_height = from_height_width, height

    if edge in {WMSZ_LEFT, WMSZ_TOPLEFT, WMSZ_BOTTOMLEFT}:
        rect.left = rect.right - target_width
    else:
        rect.right = rect.left + target_width
    if edge in {WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT}:
        rect.top = rect.bottom - target_height
    else:
        rect.bottom = rect.top + target_height


def video_aspect_from_probe(data: dict) -> float:
    """Extract display aspect from an ffprobe payload."""
    streams = data.get("streams", []) if isinstance(data, dict) else []
    for stream in streams if isinstance(streams, list) else []:
        if not isinstance(stream, dict) or stream.get("codec_type") != "video":
            continue
        display = str(stream.get("display_aspect_ratio") or "")
        if ":" in display:
            left, right = display.split(":", 1)
            try:
                ratio = float(left) / float(right)
                if ratio > 0:
                    return ratio
            except (ValueError, ZeroDivisionError):
                pass
        try:
            width = float(stream.get("width") or 0)
            height = float(stream.get("height") or 0)
            if width > 0 and height > 0:
                return width / height
        except (TypeError, ValueError):
            pass
    return 0.0
