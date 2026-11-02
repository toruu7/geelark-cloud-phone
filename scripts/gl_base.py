"""Shared foundation: Win32 handles, constants, paths, active-target session, gesture math."""
import sys
import os
import json
import threading
import ctypes
from ctypes import wintypes

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    Image = None
    ImageChops = None
    ImageDraw = None

# Win32 Definitions & Setup (Safe Multi-Platform Guard)
IS_WINDOWS = sys.platform == "win32" and hasattr(ctypes, "windll")

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    # 64-bit Win32 API signatures for reliable clipboard memory handling
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
else:
    user32 = None
    gdi32 = None
    kernel32 = None

SRCCOPY = 0x00CC0020

SM_XVIRTUALSCREEN = 76

SM_YVIRTUALSCREEN = 77

SM_CXVIRTUALSCREEN = 78

SM_CYVIRTUALSCREEN = 79

SW_RESTORE = 9

MOUSEEVENTF_LEFTDOWN = 0x0002

MOUSEEVENTF_LEFTUP = 0x0004

VK_RETURN = 0x0D

VK_BACK = 0x08

VK_TAB = 0x09

VK_ESCAPE = 0x1B

VK_CONTROL = 0x11

VK_MENU = 0x12  # ALT

VK_V = 0x56

KEYEVENTF_KEYUP = 0x0002

GEELARK_PATH = r"C:\Program Files (x86)\GeeLark\GeeLark.exe"

GEELARK_ADB_PATH = os.path.expandvars(r"%APPDATA%\GeeLark\scrcpy\adb.exe")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OCR_HELPER_PATH = os.path.join(SCRIPT_DIR, "ocr_helper.ps1")

MARKS_CACHE_PATH = os.path.join(SCRIPT_DIR, ".marks_cache.json")

SESSION_CACHE_PATH = os.path.join(SCRIPT_DIR, ".active_session.json")

def _read_session():
    if os.path.exists(SESSION_CACHE_PATH):
        try:
            with open(SESSION_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def _write_json_atomic(path, data):
    """Write JSON via temp file + os.replace so concurrent readers never see a half-written file."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def set_active_target(title_or_num, adb_device=None):
    data = _read_session()
    data["active_target"] = str(title_or_num)
    if adb_device:
        data["adb_device"] = str(adb_device)
    _write_json_atomic(SESSION_CACHE_PATH, data)
    res = {"status": "success", "active_target": str(title_or_num)}
    if adb_device:
        res["adb_device"] = str(adb_device)
    return res

def get_active_target():
    return _read_session().get("active_target")

def get_active_adb_device():
    """Explicit ADB serial only (env GEELARK_ADB_DEVICE or `use --device`); never shells out."""
    env = os.environ.get("GEELARK_ADB_DEVICE", "").strip()
    return env or _read_session().get("adb_device")

def input_mode():
    """'gui' (default): real mouse events on the phone window. 'adb': inject taps/swipes via ADB."""
    return os.environ.get("GEELARK_INPUT_MODE", "gui").strip().lower()

def bezier_point(p0, p1, p2, p3, t):
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t
    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return (int(x), int(y))

def ease_in_out(t):
    return t * t * (3.0 - 2.0 * t)

COMMON_APPS = {
    "youtube": "com.google.android.youtube",
    "tiktok": "com.zhiliaoapp.musically",
    "chrome": "com.android.chrome",
    "settings": "com.android.settings",
    "playstore": "com.android.vending",
    "files": "com.google.android.documentsui"
}

class RECT(ctypes.Structure):
    _fields_ = [
        ('left', wintypes.LONG),
        ('top', wintypes.LONG),
        ('right', wintypes.LONG),
        ('bottom', wintypes.LONG)
    ]
    @property
    def width(self): return self.right - self.left
    @property
    def height(self): return self.bottom - self.top

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD)
    ]

def with_desktop(func):
    """Run a callable on a fresh thread attached to the interactive 'default' desktop."""
    if not IS_WINDOWS or not user32:
        raise RuntimeError("Win32 desktop operations are only supported on Windows host.")
    result = [None]
    exception = [None]
    def runner():
        hDesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if hDesk:
            user32.SetThreadDesktop(hDesk)
        try:
            result[0] = func()
        except Exception as e:
            exception[0] = e
        finally:
            if hDesk:
                user32.CloseDesktop(hDesk)
    t = threading.Thread(target=runner)
    t.start()
    t.join()
    if exception[0]:
        raise exception[0]
    return result[0]
