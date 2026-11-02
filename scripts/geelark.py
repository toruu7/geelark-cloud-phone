#!/usr/bin/env python3
"""
GeeLark Cloud Phone Controller CLI (v4.0 Ultimate Production Edition)
Engineered for Maximum Efficiency, Zero Token Waste & Unstoppable Reliability:
- Autonomous Batch Operations (scroll-find, auto-youtube, deep-link)
- Instant Deep-Linking via Android Intents (0.1s video/app load)
- Set-of-Mark (SoM) Numbered Visual Overlay (capture --annotate & tap-mark)
- Windows Native OCR (find-text, click-text, wait-text, scroll-find)
- Keyboard Management (hide-keyboard, type-and-enter)
- Token-Optimized Image Downscaling (--thumb, --low-token)
- Anti-Lag Stability & Autonomous Recovery (wait-stable, dismiss-popup, recover)
Compatible with Claude Code, Hermes, OpenClaw, Codex, and Antigravity.
"""

import sys
import os
import time
import json
import argparse
import subprocess
import threading
import ctypes
import re
import random
import uuid
import urllib.request
import urllib.error
from ctypes import wintypes
try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    Image = None
    ImageChops = None
    ImageDraw = None

# Pre-compiled Regular Expressions for Zero-Overhead Parsing
RE_XML_NODE = re.compile(r'<node[^>]+>', re.IGNORECASE)
RE_XML_TEXT = re.compile(r'text="([^"]*)"')
RE_XML_DESC = re.compile(r'content-desc="([^"]*)"')
RE_XML_BOUNDS = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
RE_PROFILE_NUM = re.compile(r'(?:profile|phone|window|#)\s*(\d+)')
RE_URL = re.compile(r"(https?://[^\s\"'<>]+)")
RE_VIDEO_COUNT = re.compile(r'(\d+)\s*(?:tiktok|video|vid|clip)')
RE_OPEN_APP = re.compile(r'\b(?:open|launch|start)\s+(youtube|tiktok|chrome|settings|playstore|files)\b')
RE_TYPE_TEXT = re.compile(r"(?:type|write|input|search\s+for)\s+[\"']?([^\"']+)[\"']?", re.IGNORECASE)
RE_CLICK_TEXT = re.compile(r"(?:click|tap|press|select)\s+(?:on\s+)?[\"']?([^\"']+)[\"']?", re.IGNORECASE)

# ---------------------------------------------------------
# Win32 Definitions & Setup (Safe Multi-Platform Guard)
# ---------------------------------------------------------
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

def set_active_target(title_or_num):
    with open(SESSION_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"active_target": str(title_or_num)}, f, indent=2)
    return {"status": "success", "active_target": str(title_or_num)}

def get_active_target():
    if os.path.exists(SESSION_CACHE_PATH):
        try:
            with open(SESSION_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("active_target")
        except Exception:
            pass
    return None

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

# ---------------------------------------------------------
# Window Management & Handle Caching
# ---------------------------------------------------------
def list_windows():
    """List all open GeeLark and phone windows with HWND, Rect, and Title."""
    if not IS_WINDOWS or not user32:
        return []
    def worker():
        windows = []
        def enum_proc(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    title_l = title.lower()
                    ignored_apps = ["zen browser", "google chrome", "firefox", "edge", "visual studio code", "vscode", "github", "powershell", "terminal", "sublime", "notepad++"]
                    if any(ig in title_l for ig in ignored_apps):
                        return True
                    if any(k in title_l for k in ["geelark", "phone", "tiktok", "[#"]):
                        r = RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(r))
                        is_iconic = bool(user32.IsIconic(hwnd))
                        is_phone = "geelarkphone" in title_l or "[#" in title_l or ("phone" in title_l and not title_l.startswith("geelark"))
                        windows.append({
                            "hwnd": int(hwnd),
                            "title": title,
                            "is_phone": is_phone,
                            "minimized": is_iconic,
                            "rect": {
                                "left": r.left,
                                "top": r.top,
                                "right": r.right,
                                "bottom": r.bottom,
                                "width": r.width,
                                "height": r.height
                            }
                        })
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumDesktopWindows(0, WNDENUMPROC(enum_proc), 0)
        return windows
    return with_desktop(worker)

def find_target_window(title_or_hwnd=None, prefer_phone=True):
    windows = list_windows()
    if not windows:
        return None
    if not title_or_hwnd:
        title_or_hwnd = get_active_target()
    if title_or_hwnd:
        try:
            target_hwnd = int(title_or_hwnd)
            for w in windows:
                if w["hwnd"] == target_hwnd: return w
        except ValueError:
            pass
        title_lower = str(title_or_hwnd).lower().strip()
        # 1. Exact title or profile pattern match (e.g. #4, profile 4)
        for w in windows:
            w_title = w["title"].lower()
            if w_title == title_lower:
                return w
            if f"#{title_lower}" in w_title or f"profile {title_lower}" in w_title or f"|{title_lower}" in w_title:
                return w
        # 2. General substring match
        for w in windows:
            if title_lower in w["title"].lower():
                return w
        return None
    if prefer_phone:
        for w in windows:
            if w["is_phone"]: return w
    return windows[0]

def focus_window(hwnd):
    if not IS_WINDOWS or not user32:
        return False
    def worker():
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return True
    return with_desktop(worker)

# ---------------------------------------------------------
# Screen Capture & Token Optimization
# ---------------------------------------------------------
def capture_rect(x, y, w, h):
    if not IS_WINDOWS or not user32 or not gdi32:
        raise RuntimeError("Screen capture is only supported on Windows host.")
    if Image is None:
        raise RuntimeError("Pillow is required for image operations. Install with 'pip install pillow'")
    def worker():
        hScreenDC = user32.GetDC(0)
        hMemDC = 0
        hBitmap = 0
        hOldBitmap = 0
        try:
            hMemDC = gdi32.CreateCompatibleDC(hScreenDC)
            hBitmap = gdi32.CreateCompatibleBitmap(hScreenDC, w, h)
            hOldBitmap = gdi32.SelectObject(hMemDC, hBitmap)
            gdi32.BitBlt(hMemDC, 0, 0, w, h, hScreenDC, x, y, SRCCOPY)
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0
            buf_size = w * h * 4
            buffer = (ctypes.c_char * buf_size)()
            gdi32.GetDIBits(hMemDC, hBitmap, 0, h, buffer, ctypes.byref(bmi), 0)
            raw_img = Image.frombuffer('RGBA', (w, h), buffer, 'raw', 'BGRA', 0, 1)
            try:
                return raw_img.convert('RGB')
            finally:
                raw_img.close()
        finally:
            if hMemDC and hOldBitmap:
                gdi32.SelectObject(hMemDC, hOldBitmap)
            if hBitmap:
                gdi32.DeleteObject(hBitmap)
            if hMemDC:
                gdi32.DeleteDC(hMemDC)
            if hScreenDC:
                user32.ReleaseDC(0, hScreenDC)
    return with_desktop(worker)

def capture_phone(target=None, out_path=None, crop_phone_screen=True, low_token=False):
    """
    Capture phone window.
    If low_token is True, downsamples the image to ~720p height, saving up to 70% in multimodal token costs.
    """
    if not IS_WINDOWS or not user32:
        raise RuntimeError("Screen capture is only supported on Windows host.")
    if Image is None:
        raise RuntimeError("Pillow is required for image operations. Install with 'pip install pillow'")
    win = find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("No GeeLark or Phone window found. Make sure GeeLark is open.")
    hwnd = win["hwnd"]
    focus_window(hwnd)
    time.sleep(0.05)
    r = win["rect"]
    img = capture_rect(r["left"], r["top"], r["width"], r["height"])
    try:
        if crop_phone_screen and win["is_phone"]:
            top_offset = 30
            right_toolbar_width = 44
            phone_w = r["width"] - right_toolbar_width
            phone_h = r["height"] - top_offset
            if phone_w > 50 and phone_h > 50:
                cropped = img.crop((0, top_offset, phone_w, top_offset + phone_h))
                img.close()
                img = cropped

        if low_token and img.height > 800:
            ratio = 800 / img.height
            new_w = int(img.width * ratio)
            resized = img.resize((new_w, 800), Image.Resampling.LANCZOS)
            img.close()
            img = resized

        if not out_path:
            out_path = os.path.join(os.getcwd(), "phone_screen.png")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        img.save(out_path, optimize=True)
        size = [img.width, img.height]
    finally:
        img.close()
    return {
        "status": "success",
        "file": os.path.abspath(out_path),
        "window": win["title"],
        "size": size
    }

def run_ocr(image_path):
    if not os.path.exists(OCR_HELPER_PATH):
        return []
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", OCR_HELPER_PATH,
        "-ImagePath", os.path.abspath(image_path)
    ]
    res = subprocess.run(cmd, capture_output=True)
    try:
        stdout_text = res.stdout.decode('utf-8', errors='replace').strip()
        return json.loads(stdout_text, strict=False)
    except Exception:
        return []

def capture_and_annotate(target=None, out_path=None, low_token=False):
    """
    Set-of-Mark (SoM): Captures phone, overlays numbered badges,
    and returns a compact text summary of all marks so the agent
    can act immediately without analyzing pixels!
    """
    clean_cap = capture_phone(target=target, out_path=out_path, low_token=low_token)
    img_path = clean_cap["file"]
    words = run_ocr(img_path)

    with Image.open(img_path) as src_img:
        img = src_img.convert("RGB")
    try:
        draw = ImageDraw.Draw(img)

        filtered = [w for w in words if len(w.get("text", "").strip()) > 1]
        marks = {}
        summary_list = []

        for idx, w in enumerate(filtered, 1):
            x, y, bw, bh = w["x"], w["y"], w["w"], w["h"]
            center_x = x + (bw / 2)
            center_y = y + (bh / 2)
            norm_x = round(center_x / img.width, 3)
            norm_y = round(center_y / img.height, 3)

            mark_data = {
                "text": w["text"],
                "box": [x, y, bw, bh],
                "norm": [norm_x, norm_y]
            }
            marks[str(idx)] = mark_data
            summary_list.append(f"[{idx}] \"{w['text']}\" ({norm_x}, {norm_y})")

            draw.rectangle([x, y, x + bw, y + bh], outline="#00E5FF", width=2)
            draw.rectangle([x, max(0, y - 14), x + 20, y], fill="#00E5FF")
            draw.text((x + 2, max(0, y - 14)), str(idx), fill="black")

        annotated_path = img_path.replace(".png", "_annotated.png") if ".png" in img_path else img_path + "_annotated.png"
        img.save(annotated_path, optimize=True)
    finally:
        img.close()

    with open(MARKS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"window": clean_cap["window"], "marks": marks}, f, indent=2)

    return {
        "status": "success",
        "clean_image": clean_cap["file"],
        "annotated_image": os.path.abspath(annotated_path),
        "total_marks": len(marks),
        "quick_summary": summary_list[:25],
        "marks": marks
    }

def tap_mark(mark_id, target=None):
    """Tap a numbered mark from previous 'capture --annotate'."""
    if not os.path.exists(MARKS_CACHE_PATH):
        return {"status": "error", "message": "No marks cache found. Run 'capture --annotate' first."}
    try:
        with open(MARKS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"status": "error", "message": f"Failed to read marks cache: {str(e)}"}
    marks = data.get("marks", {})
    mark = marks.get(str(mark_id))
    if not mark:
        return {"status": "error", "message": f"Mark '{mark_id}' not found in active marks."}
    norm_x, norm_y = mark["norm"]
    return tap(norm_x, norm_y, target=target, normalized=True)

# ---------------------------------------------------------
# Dynamic Stability & Verification
# ---------------------------------------------------------
def wait_screen_stable(target=None, timeout=6.0, poll_interval=0.35, threshold=0.015):
    if not IS_WINDOWS or not user32:
        raise RuntimeError("Screen stability check is only supported on Windows host.")
    if Image is None:
        raise RuntimeError("Pillow is required for image operations. Install with 'pip install pillow'")
    start_time = time.time()
    last_img = None
    temp_path = os.path.join(SCRIPT_DIR, ".temp_stable.png")
    try:
        while (time.time() - start_time) < timeout:
            res = capture_phone(target=target, out_path=temp_path)
            img = Image.open(res["file"])
            if last_img is not None:
                diff = ImageChops.difference(img, last_img)
                try:
                    diff_pixels = sum(1 for p in diff.getdata() if any(c > 20 for c in p))
                    ratio = diff_pixels / (img.width * img.height)
                finally:
                    diff.close()
                last_img.close()
                last_img = None
                if ratio < threshold:
                    img.close()
                    return {"status": "success", "stable": True, "elapsed": round(time.time() - start_time, 2)}
            last_img = img
            time.sleep(poll_interval)
        return {"status": "success", "stable": False, "timeout": timeout}
    finally:
        if last_img is not None:
            try:
                last_img.close()
            except Exception:
                pass
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

# ---------------------------------------------------------
# Touch, Gestures, Typing & Navigation
# ---------------------------------------------------------
def get_phone_screen_bounds(win):
    r = win["rect"]
    if win["is_phone"]:
        top_offset = 30
        right_toolbar_width = 44
        return {
            "x": r["left"],
            "y": r["top"] + top_offset,
            "width": r["width"] - right_toolbar_width,
            "height": r["height"] - top_offset
        }
    return {"x": r["left"], "y": r["top"], "width": r["width"], "height": r["height"]}

def tap(x, y, target=None, normalized=False):
    if not IS_WINDOWS or not user32:
        raise RuntimeError("Touch input operations are only supported on Windows host.")
    win = find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("Target window not found")
    focus_window(win["hwnd"])
    bounds = get_phone_screen_bounds(win)
    if normalized:
        abs_x = bounds["x"] + int(float(x) * bounds["width"])
        abs_y = bounds["y"] + int(float(y) * bounds["height"])
    else:
        abs_x = bounds["x"] + int(x)
        abs_y = bounds["y"] + int(y)
    def worker():
        user32.SetCursorPos(abs_x, abs_y)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.06)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    with_desktop(worker)
    return {"status": "success", "action": "tap", "coords": [abs_x, abs_y]}

def swipe(x1, y1, x2, y2, target=None, normalized=False, steps=22, duration=0.25, human=True):
    if not IS_WINDOWS or not user32:
        raise RuntimeError("Swipe gesture operations are only supported on Windows host.")
    win = find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("Target window not found")
    focus_window(win["hwnd"])
    bounds = get_phone_screen_bounds(win)
    if normalized:
        start_x = bounds["x"] + int(float(x1) * bounds["width"])
        start_y = bounds["y"] + int(float(y1) * bounds["height"])
        end_x = bounds["x"] + int(float(x2) * bounds["width"])
        end_y = bounds["y"] + int(float(y2) * bounds["height"])
    else:
        start_x = bounds["x"] + int(x1)
        start_y = bounds["y"] + int(y1)
        end_x = bounds["x"] + int(x2)
        end_y = bounds["y"] + int(y2)

    if human:
        import random
        dev_x = random.uniform(-16, 16)
        dev_y = random.uniform(-8, 8)
        p0 = (start_x, start_y)
        p3 = (end_x, end_y)
        p1 = (start_x + dev_x, start_y + (end_y - start_y) * 0.35 + dev_y)
        p2 = (end_x + dev_x * 0.6, end_y - (end_y - start_y) * 0.35)
        points = [bezier_point(p0, p1, p2, p3, ease_in_out(i / float(steps))) for i in range(1, steps + 1)]
    else:
        points = [(int(start_x + (end_x - start_x) * (i / steps)), int(start_y + (end_y - start_y) * (i / steps))) for i in range(1, steps + 1)]

    def worker():
        user32.SetCursorPos(start_x, start_y)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        delay = duration / max(1, steps)
        for px, py in points:
            user32.SetCursorPos(px, py)
            time.sleep(delay)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    with_desktop(worker)
    return {"status": "success", "action": "swipe", "from": [start_x, start_y], "to": [end_x, end_y], "human_curve": human}

def set_clipboard_text(text):
    if not IS_WINDOWS or not kernel32 or not user32:
        raise RuntimeError("Clipboard operations are only supported on Windows host.")
    text_bytes = (text + '\0').encode('utf-16le')
    h_mem = kernel32.GlobalAlloc(0x0042, len(text_bytes))
    if not h_mem:
        raise RuntimeError("GlobalAlloc failed to allocate clipboard memory.")
    p_mem = kernel32.GlobalLock(h_mem)
    if not p_mem:
        kernel32.GlobalFree(h_mem)
        raise RuntimeError("GlobalLock failed on clipboard handle.")
    try:
        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
    finally:
        kernel32.GlobalUnlock(h_mem)
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.03)
    if not opened:
        kernel32.GlobalFree(h_mem)
        raise RuntimeError("Failed to open Windows clipboard after 10 retries.")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(13, h_mem):
            kernel32.GlobalFree(h_mem)
            raise RuntimeError("SetClipboardData failed.")
    finally:
        user32.CloseClipboard()

def type_text(text, target=None):
    win = find_target_window(target, prefer_phone=True)
    if win: focus_window(win["hwnd"])
    set_clipboard_text(text)
    def worker():
        time.sleep(0.06)
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    with_desktop(worker)
    return {"status": "success", "action": "type", "text": text}

def send_key(key_name, target=None):
    key_lower = key_name.lower().strip()
    if key_lower == "back":
        return tap(0.18, 0.97, target=target, normalized=True)
    elif key_lower == "home":
        return tap(0.50, 0.97, target=target, normalized=True)
    elif key_lower in ["recent", "appswitch"]:
        return tap(0.82, 0.97, target=target, normalized=True)
    if not IS_WINDOWS or not user32:
        raise RuntimeError("Keyboard key operations are only supported on Windows host.")
    win = find_target_window(target, prefer_phone=True)
    if win: focus_window(win["hwnd"])
    vk_map = {"enter": VK_RETURN, "tab": VK_TAB, "esc": VK_ESCAPE, "backspace": VK_BACK}
    vk = vk_map.get(key_lower, VK_RETURN)
    def worker():
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    with_desktop(worker)
    return {"status": "success", "action": "key", "key": key_name}

def hide_keyboard(target=None):
    """Safely collapse virtual keyboard so obscured buttons become clickable."""
    return send_key("back", target=target)

# ---------------------------------------------------------
# OCR Search, Click, & Autonomous Scroll-Find
# ---------------------------------------------------------
def find_text_on_screen(query, target=None):
    cap = capture_phone(target=target, out_path=os.path.join(SCRIPT_DIR, ".ocr_cap.png"))
    words = run_ocr(cap["file"])
    query_lower = query.lower().strip()
    matches = []
    for w in words:
        if query_lower in w.get("text", "").lower():
            center_x = w["x"] + (w["w"] / 2)
            center_y = w["y"] + (w["h"] / 2)
            norm_x = center_x / cap["size"][0]
            norm_y = center_y / cap["size"][1]
            matches.append({
                "text": w["text"],
                "box": [w["x"], w["y"], w["w"], w["h"]],
                "center": [center_x, center_y],
                "norm_center": [round(norm_x, 3), round(norm_y, 3)]
            })
    return {"status": "success", "query": query, "matches": matches, "count": len(matches)}

def click_text_on_screen(query, target=None):
    res = find_text_on_screen(query, target=target)
    if not res["matches"]:
        return {"status": "error", "message": f"Text '{query}' not found on phone screen"}
    match = res["matches"][0]
    norm_x, norm_y = match["norm_center"]
    tap_res = tap(norm_x, norm_y, target=target, normalized=True)
    return {"status": "success", "action": "click-text", "matched": match["text"], "coords": [norm_x, norm_y], "tap_result": tap_res}

def wait_and_click_text(query, target=None, timeout=30.0, poll_interval=1.2):
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        res = find_text_on_screen(query, target=target)
        if res["matches"]:
            match = res["matches"][0]
            norm_x, norm_y = match["norm_center"]
            tap(norm_x, norm_y, target=target, normalized=True)
            return {"status": "success", "clicked": match["text"], "coords": [norm_x, norm_y], "elapsed": round(time.time() - start_time, 2)}
        time.sleep(poll_interval)
    return {"status": "error", "message": f"Timeout waiting for text '{query}'"}

def scroll_find(query, max_swipes=5, click=True, target=None, skip_initial_check=False):
    """
    Autonomous Cost/Time Saver:
    Repeatedly scans for query. If found, clicks it immediately.
    If not, smoothly swipes down and repeats. Accomplishes what used to take 5 agent turns in 1 call!
    When skip_initial_check is True, skips OCR on the initial un-scrolled screen (saving 1 redundant capture+OCR pass).
    """
    for swipe_idx in range(max_swipes + 1):
        if not (swipe_idx == 0 and skip_initial_check):
            res = find_text_on_screen(query, target=target)
            if res["matches"]:
                match = res["matches"][0]
                norm_x, norm_y = match["norm_center"]
                if click:
                    tap(norm_x, norm_y, target=target, normalized=True)
                return {
                    "status": "success",
                    "found": True,
                    "clicked": click,
                    "matched": match["text"],
                    "coords": [norm_x, norm_y],
                    "swipes_performed": swipe_idx
                }
        if swipe_idx < max_swipes:
            # Swipe up to scroll down
            swipe(0.5, 0.72, 0.5, 0.35, target=target, normalized=True)
            time.sleep(0.8)

    return {"status": "error", "found": False, "swipes_performed": max_swipes, "message": f"Could not find '{query}' after {max_swipes} scrolls"}

# ---------------------------------------------------------
# App Launching & Deep-Linking (0.1s Fast-Path)
# ---------------------------------------------------------
def deep_link(url_or_uri, target=None):
    """
    Instant 0.1s Deep Linker via Android Intent VIEW:
    Directly opens YouTube videos, web links, or app schemes without UI typing!
    """
    # 1. Try fast ADB intent dispatch
    adb_res = run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url_or_uri])
    if adb_res["returncode"] == 0 and "Error" not in adb_res["stderr"]:
        return {"status": "success", "method": "adb_intent", "url": url_or_uri}

    # 2. Visual fallback: Open Chrome -> paste URL -> enter
    open_app("chrome", target=target)
    time.sleep(1.2)
    # Tap omnibox near top (x: 0.5, y: 0.09)
    tap(0.5, 0.09, target=target, normalized=True)
    time.sleep(0.4)
    type_text(url_or_uri, target=target)
    time.sleep(0.4)
    send_key("enter", target=target)
    return {"status": "success", "method": "chrome_visual", "url": url_or_uri}

def open_app(app_name, target=None):
    package = COMMON_APPS.get(app_name.lower().strip(), app_name.strip())
    adb_res = run_adb(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
    if adb_res["returncode"] == 0 and "Events injected: 1" in adb_res["stdout"]:
        return {"status": "success", "method": "adb", "package": package}

    send_key("home", target=target)
    time.sleep(0.6)
    swipe(0.5, 0.8, 0.5, 0.2, target=target, normalized=True)
    time.sleep(0.8)
    click_res = click_text_on_screen(app_name, target=target)
    if click_res["status"] == "success":
        return {"status": "success", "method": "visual_ocr", "app": app_name}

    return {"status": "error", "message": f"Could not launch app '{app_name}'"}

def dismiss_popups(target=None):
    common_dismissals = [
        "Skip Ads", "Skip Ad", "Skip in 5s", "Skip trial", "Skip",
        "Not now", "No thanks", "Later", "Cancel", "Close", "Dismiss",
        "Don't allow", "While using the app", "Allow", "OK"
    ]
    cap = capture_phone(target=target, out_path=os.path.join(SCRIPT_DIR, ".ocr_cap.png"))
    words = run_ocr(cap["file"])
    for word in common_dismissals:
        word_lower = word.lower()
        for w in words:
            if word_lower in w.get("text", "").lower():
                center_x = w["x"] + (w["w"] / 2)
                center_y = w["y"] + (w["h"] / 2)
                norm_x = center_x / cap["size"][0]
                norm_y = center_y / cap["size"][1]
                tap(norm_x, norm_y, target=target, normalized=True)
                return {"status": "success", "dismissed_via": word, "matched_text": w["text"]}
    send_key("back", target=target)
    return {"status": "success", "dismissed_via": "back_key"}

def emergency_recover(target=None):
    send_key("back", target=target)
    time.sleep(0.4)
    send_key("back", target=target)
    time.sleep(0.4)
    send_key("home", target=target)
    time.sleep(0.8)
    cap = capture_phone(target=target, out_path=os.path.join(os.getcwd(), "recovered_home.png"))
    return {"status": "recovered", "current_state": cap}

# ---------------------------------------------------------
# ADB Integration & UI Tree
# ---------------------------------------------------------
def run_adb(args, device=None):
    adb_exe = GEELARK_ADB_PATH if os.path.exists(GEELARK_ADB_PATH) else "adb"
    cmd = [adb_exe]
    if device:
        cmd.extend(["-s", str(device)])
    cmd.extend(args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "returncode": res.returncode,
        "stdout": res.stdout.strip(),
        "stderr": res.stderr.strip()
    }

def dump_ui_tree(device=None):
    res = run_adb(["exec-out", "uiautomator", "dump", "/dev/tty"], device=device)
    if res["returncode"] != 0 or not res["stdout"]:
        return {"status": "error", "message": "ADB UIAutomator not available."}
    return {"status": "success", "xml": res["stdout"]}

# ---------------------------------------------------------
# ---------------------------------------------------------
# Automated Compound Recipes (One-Click Flows)
# ---------------------------------------------------------
def recipe_youtube_flow(url, click_link=None, skip_ads=True, target=None):
    """Complete 1-click autonomous YouTube recipe:
    1. Instant deep link (0.1s)
    2. Waits for playback & auto-skips any pre-roll ads
    3. Expands description if click_link requested
    4. Scrolls and clicks the link via local OCR
    """
    start_time = time.time()
    steps = []
    
    # 1. Deep link
    dl = deep_link(url, target=target)
    steps.append({"step": "deep-link", "result": dl})
    time.sleep(1.8)
    
    # 2. Skip ads
    if skip_ads:
        ad_res = wait_and_click_text("Skip", target=target, timeout=12.0, poll_interval=1.0)
        if ad_res.get("status") == "success":
            steps.append({"step": "skip-ad", "result": ad_res})
    
    # 3. Dismiss any premium promos
    dismiss_popups(target=target)
    
    # 4. If click_link, expand description and find link
    if click_link:
        time.sleep(0.6)
        more_res = click_text_on_screen("more", target=target)
        steps.append({"step": "expand-description", "result": more_res})
        time.sleep(0.8)
        
        query = click_link if click_link != "true" else "http"
        find_res = scroll_find(query, max_swipes=4, click=True, target=target)
        steps.append({"step": "click-link", "result": find_res})
        
    return {
        "status": "success",
        "recipe": "youtube-flow",
        "url": url,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "steps": steps
    }

def recipe_tiktok_feed(videos=5, min_watch=4.0, max_watch=10.0, like_ratio=0.25, target=None):
    """Autonomous TikTok human-warmup recipe:
    - Opens TikTok
    - Watches N videos for realistic random durations
    - Performs natural Bézier vertical swipes
    - Randomly double-taps to like based on like_ratio
    """
    import random
    start_time = time.time()
    open_app("tiktok", target=target)
    time.sleep(3.0)
    dismiss_popups(target=target)
    
    actions = []
    for i in range(1, videos + 1):
        watch_time = round(random.uniform(min_watch, max_watch), 1)
        time.sleep(watch_time)
        
        liked = False
        if random.random() < like_ratio:
            tap(0.5, 0.5, target=target, normalized=True)
            time.sleep(0.08)
            tap(0.5, 0.5, target=target, normalized=True)
            liked = True
            
        swipe(0.5, 0.78, 0.5, 0.22, target=target, normalized=True, human=True)
        actions.append({"video_index": i, "watch_seconds": watch_time, "liked": liked})
        
    return {
        "status": "success",
        "recipe": "tiktok-feed",
        "videos_watched": videos,
        "actions": actions,
        "elapsed_seconds": round(time.time() - start_time, 2)
    }

def get_system_status():
    wins = list_windows()
    active = get_active_target()
    adb_status = run_adb(["devices"])
    adb_devices = [line.strip().split("\t")[0].strip() for line in adb_status.get("stdout", "").splitlines() if "\tdevice" in line]
    
    phone_wins = [w for w in wins if w["is_phone"]]
    app_wins = [w for w in wins if not w["is_phone"]]
    
    return {
        "status": "success",
        "active_profile": active,
        "total_windows": len(wins),
        "phone_windows": [{"hwnd": w["hwnd"], "title": w["title"], "rect": w["rect"]} for w in phone_wins],
        "app_windows": [{"hwnd": w["hwnd"], "title": w["title"], "rect": w["rect"]} for w in app_wins],
        "adb_connected_devices": adb_devices,
        "adb_ready": len(adb_devices) > 0
    }

def execute_batch_steps(steps_data, target=None):
    """Executes a list of action dicts sequentially on target device.
    Accepts JSON file path, raw JSON string, list of dicts, or single dict.
    """
    if isinstance(steps_data, str):
        if os.path.exists(steps_data):
            try:
                with open(steps_data, "r", encoding="utf-8") as f:
                    steps = json.load(f)
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse batch JSON file: {str(e)}"}
        else:
            try:
                steps = json.loads(steps_data)
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse batch JSON string: {str(e)}"}
    elif isinstance(steps_data, dict):
        steps = [steps_data]
    elif isinstance(steps_data, list):
        steps = steps_data
    else:
        return {"status": "error", "message": f"Invalid steps data type: {type(steps_data).__name__}"}

    results = []
    start_time = time.time()

    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            results.append({"step_index": idx, "status": "error", "message": f"Step {idx} is not an action object"})
            continue

        action = step.get("action", "").lower().strip()
        step_target = step.get("window", step.get("target", target))
        res = {"step_index": idx, "action": action}

        try:
            if action == "sleep":
                dur = float(step.get("duration", step.get("seconds", 1.0)))
                time.sleep(dur)
                res["status"] = "success"
                res["slept"] = dur

            elif action == "tap":
                res["result"] = tap(step["x"], step["y"], target=step_target, normalized=step.get("norm", False))

            elif action == "swipe":
                res["result"] = swipe(
                    step["x1"], step["y1"], step["x2"], step["y2"],
                    target=step_target,
                    normalized=step.get("norm", False),
                    steps=step.get("steps", 22),
                    duration=step.get("duration", 0.25),
                    human=step.get("human", True)
                )

            elif action == "type":
                res["result"] = type_text(step["text"], target=step_target)
                if step.get("enter", False):
                    time.sleep(0.1)
                    send_key("enter", target=step_target)

            elif action == "key":
                key_name = step.get("name", step.get("key", "home"))
                res["result"] = send_key(key_name, target=step_target)

            elif action == "open-app":
                app_name = step.get("name", step.get("app", ""))
                res["result"] = open_app(app_name, target=step_target)

            elif action == "deep-link":
                url = step.get("url", step.get("link", ""))
                res["result"] = deep_link(url, target=step_target)

            elif action == "click-text":
                query = step.get("query", step.get("text", ""))
                res["result"] = click_text_on_screen(query, target=step_target)

            elif action == "wait-text":
                query = step.get("query", step.get("text", ""))
                res["result"] = wait_and_click_text(query, target=step_target, timeout=step.get("timeout", 30.0))

            elif action == "scroll-find":
                query = step.get("query", step.get("text", ""))
                res["result"] = scroll_find(
                    query,
                    max_swipes=step.get("max_swipes", 5),
                    click=step.get("click", True),
                    target=step_target
                )

            elif action == "dismiss-popup":
                res["result"] = dismiss_popups(target=step_target)

            elif action == "hide-keyboard":
                res["result"] = hide_keyboard(target=step_target)

            elif action == "wait-stable":
                res["result"] = wait_screen_stable(target=step_target, timeout=step.get("timeout", 6.0))

            elif action == "capture":
                out = step.get("out", f"batch_step_{idx}.png")
                if step.get("annotate", False):
                    res["result"] = capture_and_annotate(target=step_target, out_path=out, low_token=step.get("low_token", False))
                else:
                    res["result"] = capture_phone(target=step_target, out_path=out, low_token=step.get("low_token", False))

            elif action == "youtube-flow":
                res["result"] = recipe_youtube_flow(step["url"], click_link=step.get("click_link"), skip_ads=step.get("skip_ads", True), target=step_target)

            elif action == "tiktok-feed":
                res["result"] = recipe_tiktok_feed(videos=step.get("videos", 5), min_watch=step.get("min_watch", 4.0), max_watch=step.get("max_watch", 10.0), like_ratio=step.get("like_ratio", 0.25), target=step_target)

            elif action == "smart-click":
                query = step.get("query", step.get("text", ""))
                res["result"] = smart_click(query, target=step_target, scroll_fallback=step.get("scroll", True))

            elif action == "prompt":
                p_text = step.get("prompt", step.get("text", ""))
                res["result"] = execute_natural_prompt(p_text, target=step_target)

            else:
                res["status"] = "error"
                res["message"] = f"Unknown action '{action}'"

            if "status" not in res:
                if isinstance(res.get("result"), dict) and res["result"].get("status") == "error":
                    res["status"] = "error"
                    res["message"] = res["result"].get("message", "Step failed")
                else:
                    res["status"] = "success"

        except Exception as e:
            res["status"] = "error"
            res["error"] = str(e)

        results.append(res)

    return {
        "status": "success",
        "total_steps": len(steps),
        "elapsed_seconds": round(time.time() - start_time, 2),
        "steps": results
    }

def broadcast_action(command_name, command_args=None):
    """Executes an action across ALL open cloud phone windows."""
    if command_args is None:
        command_args = []
    wins = list_windows()
    phones = [w for w in wins if w["is_phone"]]
    if not phones:
        return {"status": "error", "message": "No active phone windows found to broadcast to."}

    results = []
    for p in phones:
        hwnd = p["hwnd"]
        focus_window(hwnd)
        time.sleep(0.1)

        try:
            if command_name == "tap":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 2:
                    raise ValueError("Tap broadcast requires x and y coordinates")
                r = tap(float(coords[0]), float(coords[1]), target=hwnd, normalized=norm)
            elif command_name == "swipe":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 4:
                    raise ValueError("Swipe broadcast requires x1, y1, x2, and y2 coordinates")
                r = swipe(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]), target=hwnd, normalized=norm)
            elif command_name == "key":
                if not command_args:
                    raise ValueError("Key broadcast requires a key name")
                r = send_key(command_args[0], target=hwnd)
            elif command_name == "type":
                clean_args = [a for a in command_args if a != "--norm"]
                r = type_text(" ".join(clean_args), target=hwnd)
            elif command_name == "open-app":
                if not command_args:
                    raise ValueError("open-app broadcast requires an app name")
                r = open_app(command_args[0], target=hwnd)
            elif command_name == "deep-link":
                if not command_args:
                    raise ValueError("deep-link broadcast requires a URL")
                r = deep_link(command_args[0], target=hwnd)
            elif command_name == "dismiss-popup":
                r = dismiss_popups(target=hwnd)
            elif command_name == "hide-keyboard":
                r = hide_keyboard(target=hwnd)
            elif command_name == "recover":
                r = emergency_recover(target=hwnd)
            else:
                r = {"status": "error", "message": f"Command '{command_name}' not supported in broadcast mode"}
            results.append({"phone": p["title"], "hwnd": hwnd, "result": r})
        except Exception as e:
            results.append({"phone": p["title"], "hwnd": hwnd, "error": str(e)})

    return {"status": "success", "broadcast_count": len(phones), "results": results}

def batch_profiles(profiles_input, command_name, command_args=None):
    """Runs a command sequentially across specific profile numbers/names."""
    if command_args is None:
        command_args = []
    wins = list_windows()
    phones = [w for w in wins if w["is_phone"]]
    if not phones:
        return {"status": "error", "message": "No open phone windows found."}

    if profiles_input == "all":
        selected = phones
    else:
        profile_keys = [k.strip().lower() for k in profiles_input.split(",")]
        selected = []
        for pk in profile_keys:
            for p in phones:
                title = p["title"].lower()
                if pk in title or f"#{pk}" in title:
                    if p not in selected:
                        selected.append(p)

    if not selected:
        return {"status": "error", "message": f"No open phone windows matched profiles: {profiles_input}"}

    results = []
    for p in selected:
        hwnd = p["hwnd"]
        focus_window(hwnd)
        time.sleep(0.2)
        try:
            if command_name == "youtube-flow":
                if not command_args:
                    raise ValueError("youtube-flow requires a video URL")
                r = recipe_youtube_flow(command_args[0], click_link=command_args[1] if len(command_args) > 1 else None, target=hwnd)
            elif command_name == "tiktok-feed":
                v_count = int(command_args[0]) if len(command_args) > 0 else 5
                r = recipe_tiktok_feed(videos=v_count, target=hwnd)
            elif command_name == "open-app":
                if not command_args:
                    raise ValueError("open-app requires an app name")
                r = open_app(command_args[0], target=hwnd)
            elif command_name == "deep-link":
                if not command_args:
                    raise ValueError("deep-link requires a URL")
                r = deep_link(command_args[0], target=hwnd)
            elif command_name == "dismiss-popup":
                r = dismiss_popups(target=hwnd)
            elif command_name == "recover":
                r = emergency_recover(target=hwnd)
            elif command_name == "key":
                if not command_args:
                    raise ValueError("key requires a key name")
                r = send_key(command_args[0], target=hwnd)
            elif command_name == "hide-keyboard":
                r = hide_keyboard(target=hwnd)
            elif command_name == "tap":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 2:
                    raise ValueError("tap requires x and y coordinates")
                r = tap(float(coords[0]), float(coords[1]), target=hwnd, normalized=norm)
            elif command_name == "swipe":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 4:
                    raise ValueError("swipe requires x1, y1, x2, and y2 coordinates")
                r = swipe(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]), target=hwnd, normalized=norm)
            elif command_name == "type":
                clean_args = [a for a in command_args if a != "--norm"]
                r = type_text(" ".join(clean_args), target=hwnd)
            elif command_name == "batch-run":
                if not command_args:
                    raise ValueError("batch-run requires a JSON file path or steps string")
                r = execute_batch_steps(command_args[0], target=hwnd)
            elif command_name == "click-text":
                if not command_args:
                    raise ValueError("click-text requires a search query")
                r = click_text_on_screen(command_args[0], target=hwnd)
            elif command_name == "scroll-find":
                if not command_args:
                    raise ValueError("scroll-find requires a search query")
                r = scroll_find(command_args[0], target=hwnd)
            else:
                r = {"status": "error", "message": f"Command '{command_name}' not supported in batch-profiles mode"}
            results.append({"profile": p["title"], "hwnd": hwnd, "result": r})
        except Exception as e:
            results.append({"profile": p["title"], "hwnd": hwnd, "error": str(e)})

    return {"status": "success", "profiles_processed": len(selected), "results": results}


# ---------------------------------------------------------
# Multi-Path Fallback Routing, Cloud API & Natural Language Engine
# ---------------------------------------------------------
KNOWN_UI_ANCHORS = {
    "home": (0.50, 0.97),
    "back": (0.18, 0.97),
    "recent": (0.82, 0.97),
    "appswitch": (0.82, 0.97),
    "omnibox": (0.50, 0.09),
    "address bar": (0.50, 0.09),
    "url bar": (0.50, 0.09),
    "search bar": (0.50, 0.09),
    "like": (0.92, 0.52),
    "heart": (0.92, 0.52),
    "center": (0.50, 0.50),
    "play": (0.50, 0.50),
    "pause": (0.50, 0.50),
}

def smart_click(query, target=None, scroll_fallback=True):
    """Multi-Path Fallback Element Grounding & Clicking (inspired by MobileRun & AppAgent v2):
    Path 1: Structural UI Accessibility Tree (ADB UIAutomator XML bounds)
    Path 2: Local Windows Native OCR (click_text_on_screen)
    Path 3: Autonomous Scroll-Find OCR Loop (scroll_find with skip_initial_check=True)
    Path 4: Pre-Calibrated Normalized Coordinate Anchor Fallback
    """
    paths_tried = []
    q_clean = str(query).strip()
    q_lower = q_clean.lower()

    # Path 1: ADB UI Automator Accessibility Tree
    paths_tried.append("adb_ui_tree")
    try:
        ui_res = dump_ui_tree()
        if ui_res.get("status") == "success" and ui_res.get("xml"):
            xml_str = ui_res["xml"]
            for node_match in RE_XML_NODE.finditer(xml_str):
                node_tag = node_match.group(0)
                text_m = RE_XML_TEXT.search(node_tag)
                desc_m = RE_XML_DESC.search(node_tag)
                bounds_m = RE_XML_BOUNDS.search(node_tag)
                node_text = (text_m.group(1) if text_m else "") + " " + (desc_m.group(1) if desc_m else "")
                if q_lower in node_text.lower() and bounds_m:
                    x1, y1, x2, y2 = map(int, bounds_m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    adb_tap = run_adb(["shell", "input", "tap", str(cx), str(cy)])
                    if adb_tap.get("returncode") == 0:
                        return {
                            "status": "success",
                            "action": "smart-click",
                            "path": "adb_ui_tree",
                            "matched": node_text.strip(),
                            "coords": [cx, cy],
                            "paths_tried": paths_tried
                        }
    except Exception:
        pass

    # Path 2: Local Windows Native OCR
    paths_tried.append("local_ocr")
    try:
        ocr_res = click_text_on_screen(q_clean, target=target)
        if ocr_res.get("status") == "success":
            return {
                "status": "success",
                "action": "smart-click",
                "path": "local_ocr",
                "matched": ocr_res.get("matched", q_clean),
                "coords": ocr_res.get("coords"),
                "paths_tried": paths_tried
            }
    except Exception:
        pass

    # Path 3: Autonomous Scroll-Find Loop (skip_initial_check=True avoids re-OCR-ing the current screen)
    if scroll_fallback:
        paths_tried.append("scroll_find_ocr")
        try:
            sf_res = scroll_find(q_clean, max_swipes=3, click=True, target=target, skip_initial_check=True)
            if sf_res.get("status") == "success":
                return {
                    "status": "success",
                    "action": "smart-click",
                    "path": "scroll_find_ocr",
                    "matched": sf_res.get("matched", q_clean),
                    "coords": sf_res.get("coords"),
                    "swipes_performed": sf_res.get("swipes_performed", 0),
                    "paths_tried": paths_tried
                }
        except Exception:
            pass

    # Path 4: Pre-Calibrated Normalized Coordinate Anchor
    paths_tried.append("normalized_anchor")
    if q_lower in KNOWN_UI_ANCHORS:
        nx, ny = KNOWN_UI_ANCHORS[q_lower]
        try:
            tap(nx, ny, target=target, normalized=True)
            return {
                "status": "success",
                "action": "smart-click",
                "path": "normalized_anchor",
                "matched": q_lower,
                "coords": [nx, ny],
                "paths_tried": paths_tried
            }
        except Exception as e:
            return {"status": "error", "message": f"Anchor tap failed: {str(e)}", "paths_tried": paths_tried}

    return {
        "status": "error",
        "action": "smart-click",
        "message": f"All fallback paths failed to locate element '{q_clean}'",
        "paths_tried": paths_tried
    }

def cloud_api_request(endpoint, payload=None, api_token=None):
    """Hybrid Cloud OpenAPI Client for https://openapi.geelark.com.
    Automatically attaches UUID v4 traceId and Bearer token.
    """
    import uuid
    import urllib.request
    import urllib.error

    token = api_token or os.environ.get("GEELARK_API_TOKEN", "").strip()
    trace_id = str(uuid.uuid4())
    if not token:
        return {
            "status": "error",
            "code": "missing_api_token",
            "traceId": trace_id,
            "message": "GEELARK_API_TOKEN is not set. Set GEELARK_API_TOKEN environment variable or pass --token to use Cloud OpenAPI."
        }

    url = f"https://openapi.geelark.com{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    body_bytes = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "traceId": trace_id
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {"status": "success", "traceId": trace_id, "endpoint": endpoint, "response": resp_data}
    except Exception as e:
        return {"status": "error", "traceId": trace_id, "endpoint": endpoint, "message": str(e)}

def ensure_device_ready(target=None, auto_boot=True):
    """Multi-Path Device Lifecycle Resolver:
    Path 1: Active / Cached Phone Window
    Path 2: Restore Minimized Phone Window
    Path 3: Auto-Scan Any Open Phone Window
    Path 4: Cloud OpenAPI Remote Boot (openapi.geelark.com)
    Path 5: Local GeeLark Desktop App Launch
    """
    paths_tried = []
    eff_target = target or get_active_target()

    # Path 1 & 2: Check target window
    paths_tried.append("cached_or_target_window")
    win = find_target_window(eff_target, prefer_phone=True)
    if win:
        if win.get("minimized"):
            paths_tried.append("restore_minimized_window")
            try:
                focus_window(win["hwnd"])
            except Exception:
                pass
            return {"status": "ready", "path": "restore_minimized_window", "window": win, "paths_tried": paths_tried}
        return {"status": "ready", "path": "cached_or_target_window", "window": win, "paths_tried": paths_tried}

    # Path 3: Auto-scan any open phone window
    paths_tried.append("auto_discover_open_phone")
    wins = list_windows()
    phones = [w for w in wins if w.get("is_phone")]
    if phones:
        return {"status": "ready", "path": "auto_discover_open_phone", "window": phones[0], "paths_tried": paths_tried}

    if not auto_boot:
        return {"status": "error", "message": "No open phone window found and auto_boot is disabled", "paths_tried": paths_tried}

    # Path 4: Cloud OpenAPI Remote Boot
    if os.environ.get("GEELARK_API_TOKEN"):
        paths_tried.append("cloud_openapi_boot")
        c_res = cloud_api_request("/open/v1/phone/start", {"ids": [str(eff_target or "1")]})
        if c_res.get("status") == "success":
            return {"status": "booting", "path": "cloud_openapi_boot", "cloud_result": c_res, "paths_tried": paths_tried}

    # Path 5: Local Desktop App Launch
    paths_tried.append("local_desktop_launch")
    if os.path.exists(GEELARK_PATH):
        try:
            subprocess.Popen([GEELARK_PATH])
            return {"status": "launching_desktop", "path": "local_desktop_launch", "executable": GEELARK_PATH, "paths_tried": paths_tried}
        except Exception as e:
            return {"status": "error", "message": f"Failed to launch GeeLark desktop: {str(e)}", "paths_tried": paths_tried}

    return {"status": "error", "message": "Device unavailable across all lifecycle paths", "paths_tried": paths_tried}

def execute_natural_prompt(prompt_text, target=None):
    """Built-in Plain-Text Semantic Intent Transpiler:
    Translates casual natural language prompts (from x.ai/bot, Telegram, small LLMs, or humans)
    into deterministic GeeLark recipes, batch steps, or multi-path actions.
    """
    if not prompt_text or not str(prompt_text).strip():
        return {"status": "error", "message": "Empty prompt provided"}

    raw = str(prompt_text).strip()
    low = raw.lower()

    # 1. Extract profile / phone number if mentioned (e.g., "on profile 4", "phone #2")
    prof_match = RE_PROFILE_NUM.search(low)
    eff_target = target
    profile_locked = None
    if prof_match:
        profile_locked = prof_match.group(1)
        eff_target = profile_locked
        set_active_target(profile_locked)

    # 2. Extract URL if present
    url_match = RE_URL.search(raw)
    extracted_url = url_match.group(1) if url_match else None

    # 3. Route by semantic intent
    # Case A: TikTok Warmup / Feed
    if "tiktok" in low and any(w in low for w in ["watch", "feed", "warm", "video", "scroll", "swipe", "like"]):
        vid_match = RE_VIDEO_COUNT.search(low)
        videos = int(vid_match.group(1)) if vid_match else 5
        like_ratio = 0.5 if "like" in low else 0.25
        res = recipe_tiktok_feed(videos=videos, like_ratio=like_ratio, target=eff_target)
        return {"status": "success", "transpiled_intent": "tiktok-feed", "profile": eff_target, "result": res}

    # Case B: YouTube Flow
    if ("youtube" in low or (extracted_url and ("youtube.com" in extracted_url or "youtu.be" in extracted_url))):
        url = extracted_url or "https://www.youtube.com"
        click_link = "http" if any(w in low for w in ["link", "description", "desc"]) else None
        res = recipe_youtube_flow(url, click_link=click_link, skip_ads=True, target=eff_target)
        return {"status": "success", "transpiled_intent": "youtube-flow", "profile": eff_target, "result": res}

    # Case C: Direct URL Deep-Link
    if extracted_url:
        res = deep_link(extracted_url, target=eff_target)
        return {"status": "success", "transpiled_intent": "deep-link", "profile": eff_target, "result": res}

    # Case D: Dismiss Popups / Skip Ads
    if any(w in low for w in ["dismiss", "popup", "pop-up", "skip ad", "close ad", "modal"]):
        if "all" in low or "every" in low or "broadcast" in low:
            res = broadcast_action("dismiss-popup", [])
            return {"status": "success", "transpiled_intent": "broadcast:dismiss-popup", "result": res}
        res = dismiss_popups(target=eff_target)
        return {"status": "success", "transpiled_intent": "dismiss-popup", "profile": eff_target, "result": res}

    # Case E: Status Check
    if any(w in low for w in ["status", "what is open", "connected", "list window", "check phone"]):
        res = get_system_status()
        return {"status": "success", "transpiled_intent": "status", "result": res}

    # Case F: Emergency Recover
    if any(w in low for w in ["recover", "emergency", "reset phone", "clean home"]):
        res = emergency_recover(target=eff_target)
        return {"status": "success", "transpiled_intent": "recover", "profile": eff_target, "result": res}

    # Case G: Navigation Keys (Home, Back, Keyboard)
    if "hide keyboard" in low or "close keyboard" in low:
        res = hide_keyboard(target=eff_target)
        return {"status": "success", "transpiled_intent": "hide-keyboard", "profile": eff_target, "result": res}
    if any(w in low for w in ["go home", "home screen", "press home"]):
        res = send_key("home", target=eff_target)
        return {"status": "success", "transpiled_intent": "key:home", "profile": eff_target, "result": res}
    if any(w in low for w in ["go back", "press back"]):
        res = send_key("back", target=eff_target)
        return {"status": "success", "transpiled_intent": "key:back", "profile": eff_target, "result": res}

    # Case H: Open App
    app_match = RE_OPEN_APP.search(low)
    if app_match:
        app_name = app_match.group(1)
        res = open_app(app_name, target=eff_target)
        return {"status": "success", "transpiled_intent": f"open-app:{app_name}", "profile": eff_target, "result": res}

    # Case I: Type Text
    type_match = RE_TYPE_TEXT.search(raw)
    if type_match:
        txt = type_match.group(1).strip()
        res = type_text(txt, target=eff_target)
        if "enter" in low or "search" in low or "submit" in low:
            send_key("enter", target=eff_target)
        return {"status": "success", "transpiled_intent": "type", "text": txt, "profile": eff_target, "result": res}

    # Case J: Click / Tap Element by Name (Smart Multi-Path Click)
    click_match = RE_CLICK_TEXT.search(raw)
    if click_match:
        query = click_match.group(1).strip()
        res = smart_click(query, target=eff_target)
        return {"status": "success" if res.get("status") == "success" else "error", "transpiled_intent": "smart-click", "query": query, "profile": eff_target, "result": res}

    # Case K: Only profile switch requested ("use profile 4", "switch to phone 4")
    if profile_locked:
        return {"status": "success", "transpiled_intent": "use", "active_profile": profile_locked}

    # Default Fallback: Try smart_click with the raw query
    res = smart_click(raw, target=eff_target, scroll_fallback=False)
    return {
        "status": res.get("status", "error"),
        "transpiled_intent": "fallback_smart_click",
        "query": raw,
        "profile": eff_target,
        "result": res
    }

def export_agent_schemas(fmt="all", server_url="http://localhost:5055"):
    """Exports universal tool schemas for ANY agent ecosystem:
    - OpenAI / xAI (Grok Bot) Function Calling tools array
    - Model Context Protocol (MCP) tools/list schema
    - OpenAPI 3.1.0 specification (Custom GPTs, Dify, Coze, LangChain)
    """
    mcp_tools = [
        {
            "name": "geelark_prompt",
            "description": "Control GeeLark cloud phone using plain natural language instructions (e.g., 'watch 5 tiktoks on profile 4', 'open youtube link and skip ads', 'dismiss popups on all phones').",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Plain text instruction to execute on the cloud phone."},
                    "window": {"type": "string", "description": "Optional target profile number or window title."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "geelark_smart_click",
            "description": "Multi-path element clicker: tries ADB UI tree bounds -> Local Windows OCR -> Scroll-Find loop -> Normalized anchor fallback.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text label, content description, or anchor name (e.g. 'Skip', 'Search', 'home')."},
                    "window": {"type": "string", "description": "Optional target profile number."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "geelark_command",
            "description": "Execute any GeeLark CLI command or compound recipe (use, status, youtube-flow, tiktok-feed, batch-run, broadcast, deep-link, dismiss-popup, recover).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["use", "status", "youtube-flow", "tiktok-feed", "batch-run", "broadcast", "batch-profiles", "deep-link", "open-app", "smart-click", "click-text", "scroll-find", "dismiss-popup", "hide-keyboard", "recover", "capture"],
                        "description": "Command or recipe name."
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Arguments for the command."
                    }
                },
                "required": ["command"]
            }
        }
    ]

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"]
            }
        }
        for t in mcp_tools
    ]

    openapi_spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "GeeLark Cloud Phone Universal Agent Gateway",
            "version": "4.2.0",
            "description": "Universal REST, Webhook, and Remote MCP gateway for controlling GeeLark cloud phones from x.ai/bot (Grok), OpenAI Custom GPTs, Claude, n8n, Dify, CrewAI, and LangChain."
        },
        "servers": [{"url": server_url}],
        "paths": {
            "/prompt": {
                "post": {
                    "operationId": "geelarkPrompt",
                    "summary": "Execute plain-text natural language phone instruction",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": mcp_tools[0]["inputSchema"]
                            }
                        }
                    },
                    "responses": {"200": {"description": "Execution result"}}
                }
            },
            "/run": {
                "post": {
                    "operationId": "geelarkRunCommand",
                    "summary": "Execute structured GeeLark CLI command or recipe",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": mcp_tools[2]["inputSchema"]
                            }
                        }
                    },
                    "responses": {"200": {"description": "Command output"}}
                }
            },
            "/mcp": {
                "post": {
                    "operationId": "geelarkMcpJsonRpc",
                    "summary": "Model Context Protocol (MCP) JSON-RPC 2.0 endpoint",
                    "responses": {"200": {"description": "JSON-RPC 2.0 response"}}
                }
            }
        }
    }

    if fmt in ["openai", "xai"]:
        return {"format": fmt, "tools": openai_tools}
    elif fmt == "mcp":
        return {"format": "mcp", "tools": mcp_tools}
    elif fmt == "openapi":
        return openapi_spec
    return {
        "openai_xai_tools": openai_tools,
        "mcp_tools": mcp_tools,
        "openapi_3_1": openapi_spec
    }

def get_feature_manifest():
    """Returns structured catalog of all capabilities, recipes, batch actions, and configuration."""
    return {
        "version": "4.1 Production Edition",
        "name": "geelark-cloud-phone",
        "description": "Universal GeeLark cloud phone controller for AI agents and automation orchestrators",
        "keywords": [
            "geelark", "cloud-phone", "android-automation", "mobile-agent", "agent-skill",
            "claude-code", "antigravity", "hermes-agent", "openclaw", "codex", "adb",
            "ocr", "n8n", "set-of-mark", "antidetect", "tiktok-automation", "youtube-automation",
            "bezier-gestures", "anti-bot"
        ],
        "supported_agents": [
            "Claude Code & Claude Desktop (SKILL.md + MCP)",
            "Google Antigravity (SKILL.md + MCP)",
            "xAI Grok Bot / https://x.ai/bot (Remote MCP + OpenAPI + Plain-Text Prompt)",
            "Cursor & Windsurf (SKILL.md + Stdio/Remote MCP)",
            "OpenClaw & Hermes Agent (SKILL.md + CLI)",
            "OpenAI Codex & Custom GPTs (SKILL.md + OpenAPI 3.1)",
            "Cline, Roo Code & Zed (Stdio MCP)",
            "LangChain, CrewAI, AutoGen, Dify & Coze (OpenAPI + Function Calling)",
            "n8n, Make, Zapier & Telegram/Discord Bots (Webhook /prompt & /run)"
        ],
        "capabilities": {
            "target_management": {
                "description": "Lock onto specific cloud phone profiles without repetitive arguments",
                "commands": ["use", "status", "list-windows", "focus", "launch-app"]
            },
            "visual_screen_capture": {
                "description": "Screen capture with auto-crop, Set-of-Mark numbered badges, and low-token optimization",
                "commands": ["capture", "tap-mark"],
                "features": ["--annotate (SoM badges)", "--low-token (~70% vision token reduction)", "auto-crop toolbar/titlebar"]
            },
            "touch_gestures_navigation": {
                "description": "Human-like gesture curves and navigation controls",
                "commands": ["tap", "swipe", "type", "key", "hide-keyboard"],
                "features": ["Cubic Bézier curve interpolation with easing", "Normalized coordinates (0.0 to 1.0)", "Clipboard paste injection"]
            },
            "windows_native_ocr": {
                "description": "Zero-dependency local Windows OCR engine for fast, free text recognition",
                "commands": ["find-text", "click-text", "wait-text", "scroll-find"],
                "features": ["80ms local execution", "$0 token cost", "Autonomous scroll-find loop"]
            },
            "app_launcher_deep_links": {
                "description": "0.1s instant deep-linking via Android Intents and ADB monkey launching",
                "commands": ["open-app", "deep-link"],
                "common_apps": COMMON_APPS
            },
            "automated_compound_recipes": {
                "description": "1-click high-level mobile workflows",
                "commands": ["youtube-flow", "tiktok-feed"],
                "features": ["Auto ad skipping", "Description link finder", "Anti-bot randomized watch times & likes"]
            },
            "multi_device_orchestration": {
                "description": "Execute actions across multiple profiles or all devices at once",
                "commands": ["batch-run", "broadcast", "batch-profiles"]
            },
            "self_healing_failsafes": {
                "description": "Obstacle detection, render stability checking, and emergency recovery",
                "commands": ["wait-stable", "dismiss-popup", "recover"]
            },
            "external_integrations": {
                "description": "HTTP Webhook bridge and n8n workflows for Docker and orchestrator triggers",
                "commands": ["webhook_bridge", "n8n-trigger"],
                "components": ["scripts/webhook_bridge.py", "examples/n8n_trigger.json", "examples/sample_batch.json"]
            }
        },
        "supported_batch_actions": [
            "tap", "swipe", "type", "key", "open-app", "deep-link",
            "smart-click", "click-text", "wait-text", "scroll-find",
            "dismiss-popup", "hide-keyboard", "wait-stable", "sleep",
            "capture", "youtube-flow", "tiktok-feed", "prompt"
        ],
        "common_apps": COMMON_APPS,
        "key_mappings": {
            "back": "Normalized tap (0.18, 0.97) / VK_BACK",
            "home": "Normalized tap (0.50, 0.97)",
            "recent / appswitch": "Normalized tap (0.82, 0.97)",
            "enter": "VK_RETURN (0x0D)",
            "tab": "VK_TAB (0x09)",
            "esc": "VK_ESCAPE (0x1B)",
            "backspace": "VK_BACK (0x08)"
        },
        "environment": {
            "is_windows": IS_WINDOWS,
            "geelark_exe_path": GEELARK_PATH,
            "adb_path": GEELARK_ADB_PATH,
            "active_target": get_active_target()
        }
    }

# CLI Router
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="GeeLark Cloud Phone Controller (Production v4.0)")
    subparsers = parser.add_subparsers(dest="command")

    # list-windows
    p_list = subparsers.add_parser("list-windows", help="List all GeeLark and phone windows")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    # launch-app
    subparsers.add_parser("launch-app", help="Launch GeeLark desktop app")

    # focus
    p_focus = subparsers.add_parser("focus", help="Focus a GeeLark or Phone window")
    p_focus.add_argument("--window", "-w", help="Window title substring or HWND")

    # capture
    p_cap = subparsers.add_parser("capture", help="Capture phone screen")
    p_cap.add_argument("--window", "-w", help="Window title substring or HWND")
    p_cap.add_argument("--out", "-o", default="phone_screen.png", help="Output path for PNG")
    p_cap.add_argument("--no-crop", action="store_true", help="Capture full window instead of cropped phone display")
    p_cap.add_argument("--annotate", action="store_true", help="Overlay Set-of-Mark (SoM) numbered badges")
    p_cap.add_argument("--low-token", action="store_true", help="Downsample image to save up to 70 percent LLM vision tokens")

    # tap-mark (SoM)
    p_tm = subparsers.add_parser("tap-mark", help="Tap a numbered mark from previous 'capture --annotate'")
    p_tm.add_argument("mark_id", type=int, help="Mark number (e.g. 1, 2, 3)")
    p_tm.add_argument("--window", "-w", help="Window title substring or HWND")

    # open-app
    p_oa = subparsers.add_parser("open-app", help="Fast App Launcher (youtube, tiktok, chrome, settings)")
    p_oa.add_argument("name", help="App name or Android package")
    p_oa.add_argument("--window", "-w", help="Window title substring or HWND")

    # deep-link
    p_dl = subparsers.add_parser("deep-link", help="0.1s Instant URL/Video loader via Android Intent")
    p_dl.add_argument("url", help="URL or intent URI to open directly")
    p_dl.add_argument("--window", "-w", help="Window title substring or HWND")

    # scroll-find
    p_sf = subparsers.add_parser("scroll-find", help="Scrolls and finds text automatically in 1 command")
    p_sf.add_argument("query", help="Text to search for")
    p_sf.add_argument("--max-swipes", type=int, default=5, help="Max scrolls")
    p_sf.add_argument("--no-click", action="store_true", help="Find coordinates only without clicking")
    p_sf.add_argument("--window", "-w", help="Window title substring or HWND")

    # hide-keyboard
    p_hk = subparsers.add_parser("hide-keyboard", help="Collapse virtual keyboard to reveal hidden buttons")
    p_hk.add_argument("--window", "-w", help="Window title substring or HWND")

    # dump-ui
    subparsers.add_parser("dump-ui", help="Dump UI accessibility tree via ADB")

    # wait-stable
    p_stable = subparsers.add_parser("wait-stable", help="Wait until screen rendering finishes")
    p_stable.add_argument("--window", "-w", help="Window title substring or HWND")
    p_stable.add_argument("--timeout", type=float, default=6.0, help="Max wait seconds")

    # tap
    p_tap = subparsers.add_parser("tap", help="Tap on phone screen")
    p_tap.add_argument("x", type=float, help="X coordinate (pixels or 0.0-1.0 if --norm)")
    p_tap.add_argument("y", type=float, help="Y coordinate (pixels or 0.0-1.0 if --norm)")
    p_tap.add_argument("--window", "-w", help="Window title substring or HWND")
    p_tap.add_argument("--norm", action="store_true", help="Treat coordinates as normalized floats (0.0 to 1.0)")

    # swipe
    p_sw = subparsers.add_parser("swipe", help="Swipe/drag on phone screen")
    p_sw.add_argument("x1", type=float, help="Start X")
    p_sw.add_argument("y1", type=float, help="Start Y")
    p_sw.add_argument("x2", type=float, help="End X")
    p_sw.add_argument("y2", type=float, help="End Y")
    p_sw.add_argument("--window", "-w", help="Window title substring or HWND")
    p_sw.add_argument("--norm", action="store_true", help="Treat coordinates as normalized floats (0.0 to 1.0)")
    p_sw.add_argument("--steps", type=int, default=20, help="Interpolation steps")

    # type
    p_type = subparsers.add_parser("type", help="Type/paste text into focused element")
    p_type.add_argument("text", help="Text string to type")
    p_type.add_argument("--enter", action="store_true", help="Immediately press Enter after typing")
    p_type.add_argument("--window", "-w", help="Window title substring or HWND")

    # key
    p_key = subparsers.add_parser("key", help="Press Android navigation key (home, back, recent, enter)")
    p_key.add_argument("name", choices=["home", "back", "recent", "appswitch", "enter", "tab", "esc"], help="Key name")
    p_key.add_argument("--window", "-w", help="Window title substring or HWND")

    # find-text
    p_find = subparsers.add_parser("find-text", help="Search for text labels using Windows Native OCR")
    p_find.add_argument("query", help="Text to search for")
    p_find.add_argument("--window", "-w", help="Window title substring or HWND")

    # click-text
    p_click_text = subparsers.add_parser("click-text", help="Click on a text label directly via OCR")
    p_click_text.add_argument("query", help="Text to search and click")
    p_click_text.add_argument("--window", "-w", help="Window title substring or HWND")

    # wait-text
    p_wait_text = subparsers.add_parser("wait-text", help="Wait for text label to appear and click it")
    p_wait_text.add_argument("query", help="Text to wait for (e.g. 'Skip', 'Install')")
    p_wait_text.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds")
    p_wait_text.add_argument("--window", "-w", help="Window title substring or HWND")

    # dismiss-popup
    p_dismiss = subparsers.add_parser("dismiss-popup", help="Dismiss obstacle popups or modals")
    p_dismiss.add_argument("--window", "-w", help="Window title substring or HWND")

    # recover
    p_rec = subparsers.add_parser("recover", help="Emergency recovery: back, back, home, verify")
    p_rec.add_argument("--window", "-w", help="Window title substring or HWND")

    # adb
    p_adb = subparsers.add_parser("adb", help="Run ADB command via GeeLark's bundled ADB")
    p_adb.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to adb")

    # use (set active profile)
    p_use = subparsers.add_parser("use", help="Set active phone window or profile number")
    p_use.add_argument("target", help="Profile number, HWND, or window title substring")

    # features
    p_feat = subparsers.add_parser("features", help="Display full catalog of skill features, capabilities, and batch actions")
    p_feat.add_argument("--json", action="store_true", help="Output feature catalog in JSON format")

    # status
    subparsers.add_parser("status", help="Get overview of connected phones, active profile, and ADB status")

    # youtube-flow
    p_yt = subparsers.add_parser("youtube-flow", help="1-Click YouTube recipe: Deep-link, auto-skip ads, click link")
    p_yt.add_argument("url", help="YouTube video URL")
    p_yt.add_argument("--click-link", help="Text/domain of link in description to click (e.g. 'http')")
    p_yt.add_argument("--no-skip-ads", action="store_true", help="Do not wait for or skip pre-roll ads")
    p_yt.add_argument("--window", "-w", help="Window title substring or HWND")

    # tiktok-feed
    p_tt = subparsers.add_parser("tiktok-feed", help="1-Click TikTok warmup: Natural Bézier swipes and realistic watch time")
    p_tt.add_argument("--videos", type=int, default=5, help="Number of videos to watch")
    p_tt.add_argument("--min-watch", type=float, default=4.0, help="Min seconds per video")
    p_tt.add_argument("--max-watch", type=float, default=10.0, help="Max seconds per video")
    p_tt.add_argument("--like-ratio", type=float, default=0.25, help="Probability (0.0 - 1.0) of liking a video")
    p_tt.add_argument("--window", "-w", help="Window title substring or HWND")

    # batch-run
    p_br = subparsers.add_parser("batch-run", help="Run a sequence of actions from a JSON file or JSON string")
    p_br.add_argument("steps", help="Path to JSON file or raw JSON array of action objects")
    p_br.add_argument("--window", "-w", help="Window title substring or HWND")

    # broadcast
    p_bc = subparsers.add_parser("broadcast", help="Broadcast an action across ALL open cloud phones simultaneously")
    p_bc.add_argument("action", help="Action name (tap, swipe, key, type, open-app, deep-link, dismiss-popup)")
    p_bc.add_argument("action_args", nargs=argparse.REMAINDER, help="Arguments passed to the action")

    # batch-profiles
    p_bp = subparsers.add_parser("batch-profiles", help="Run a command sequentially across multiple profiles")
    p_bp.add_argument("--profiles", "-p", default="all", help="Comma-separated profile numbers/names (e.g. '1,2,4' or 'all')")
    p_bp.add_argument("command_name", help="Command to run (youtube-flow, tiktok-feed, open-app, deep-link, dismiss-popup, recover)")
    p_bp.add_argument("command_args", nargs=argparse.REMAINDER, help="Arguments for the command")

    # smart-click (Multi-path element grounding)
    p_sc = subparsers.add_parser("smart-click", help="Multi-path element clicker (ADB XML Tree -> Local OCR -> Scroll-Find -> Anchor)")
    p_sc.add_argument("query", help="Element text, content-desc, or anchor name")
    p_sc.add_argument("--no-scroll", action="store_true", help="Disable scroll-find fallback")
    p_sc.add_argument("--window", "-w", help="Window title substring or HWND")

    # ensure-device (Multi-path lifecycle resolver)
    p_ed = subparsers.add_parser("ensure-device", help="Multi-path device readiness resolver (Active -> Restore -> Scan -> Cloud Boot -> Desktop Launch)")
    p_ed.add_argument("--window", "-w", help="Target profile number or window title")
    p_ed.add_argument("--no-boot", action="store_true", help="Do not attempt auto-boot/launch if window is closed")

    # prompt (Built-in plain-text semantic intent transpiler)
    p_pr = subparsers.add_parser("prompt", help="Execute a plain-text natural language instruction deterministically")
    p_pr.add_argument("text", help="Plain text instruction (e.g. 'watch 5 tiktoks on profile 4')")
    p_pr.add_argument("--window", "-w", help="Optional target profile override")

    # export-schema (Universal agent schema exporter)
    p_es = subparsers.add_parser("export-schema", help="Export tool schemas for OpenAI, xAI Grok Bot, MCP, or OpenAPI 3.1")
    p_es.add_argument("--format", "-f", choices=["all", "openai", "xai", "mcp", "openapi"], default="all", help="Schema format")
    p_es.add_argument("--server-url", default="http://localhost:5055", help="Base URL for OpenAPI spec")

    # cloud-list / cloud-start / cloud-stop (Hybrid Cloud OpenAPI)
    p_cl = subparsers.add_parser("cloud-list", help="List cloud phones via GeeLark Cloud OpenAPI")
    p_cl.add_argument("--token", help="GeeLark API Bearer token (or set GEELARK_API_TOKEN)")

    p_cstart = subparsers.add_parser("cloud-start", help="Remotely start a cloud phone profile via GeeLark OpenAPI")
    p_cstart.add_argument("profile_id", help="Cloud phone profile ID")
    p_cstart.add_argument("--token", help="GeeLark API Bearer token")

    p_cstop = subparsers.add_parser("cloud-stop", help="Remotely stop a cloud phone profile via GeeLark OpenAPI")
    p_cstop.add_argument("profile_id", help="Cloud phone profile ID")
    p_cstop.add_argument("--token", help="GeeLark API Bearer token")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "list-windows":
            wins = list_windows()
            if getattr(args, "json", False):
                print(json.dumps(wins, indent=2))
            else:
                print(f"Found {len(wins)} GeeLark / Phone window(s):")
                for w in wins:
                    ptype = "[PHONE]" if w["is_phone"] else "[APP]"
                    print(f"  {ptype} HWND: {w['hwnd']} | Rect: ({w['rect']['left']}, {w['rect']['top']}, {w['rect']['width']}x{w['rect']['height']}) | Title: {w['title']}")

        elif args.command == "use":
            res = set_active_target(args.target)
            print(json.dumps(res, indent=2))

        elif args.command == "features":
            manifest = get_feature_manifest()
            if getattr(args, "json", False):
                print(json.dumps(manifest, indent=2))
            else:
                print("=======================================================")
                print(f"  {manifest['name']} ({manifest['version']})")
                print("  " + manifest['description'])
                print("=======================================================")
                agents_str = ", ".join(manifest["supported_agents"])
                print(f"Supported Agents: {agents_str}")
                print()
                print("Feature Capabilities:")
                for cat, info in manifest["capabilities"].items():
                    cat_name = cat.upper().replace("_", " ")
                    cmds = info.get("commands") or info.get("components", [])
                    cmd_list = ", ".join(cmds)
                    print(f"  * {cat_name}:")
                    print(f"    - Description: {info.get('description', '')}")
                    print(f"    - Commands / Components: {cmd_list}")
                batch_str = ", ".join(manifest["supported_batch_actions"])
                print()
                print("Supported Batch Actions ('batch-run'):")
                print(f"  {batch_str}")
                print()
                print("Common Android Apps ('open-app'):")
                for app, pkg in manifest["common_apps"].items():
                    print(f"  - {app:10s} -> {pkg}")
                tgt = manifest["environment"]["active_target"] or "None (auto-select)"
                print()
                print(f"Active Target Profile: {tgt}")
                print(f"Platform: {'Windows Host' if manifest['environment']['is_windows'] else 'Non-Windows (Safe CLI/Metadata mode)'}")
                print("=======================================================")

        elif args.command == "status":
            res = get_system_status()
            print(json.dumps(res, indent=2))

        elif args.command == "youtube-flow":
            res = recipe_youtube_flow(args.url, click_link=args.click_link, skip_ads=not args.no_skip_ads, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "tiktok-feed":
            res = recipe_tiktok_feed(videos=args.videos, min_watch=args.min_watch, max_watch=args.max_watch, like_ratio=args.like_ratio, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "batch-run":
            res = execute_batch_steps(args.steps, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "broadcast":
            res = broadcast_action(args.action, args.action_args)
            print(json.dumps(res, indent=2))

        elif args.command == "batch-profiles":
            res = batch_profiles(args.profiles, args.command_name, args.command_args)
            print(json.dumps(res, indent=2))

        elif args.command == "launch-app":
            if os.path.exists(GEELARK_PATH):
                try:
                    os.startfile(GEELARK_PATH)
                    print(json.dumps({"status": "success", "message": "GeeLark launched via startfile"}))
                except Exception:
                    subprocess.Popen([GEELARK_PATH])
                    print(json.dumps({"status": "success", "message": "GeeLark launched via Popen"}))
            else:
                print(json.dumps({"status": "error", "message": f"GeeLark executable not found at {GEELARK_PATH}"}))

        elif args.command == "focus":
            win = find_target_window(args.window)
            if win:
                focus_window(win["hwnd"])
                print(json.dumps({"status": "success", "focused": win["title"], "hwnd": win["hwnd"]}))
            else:
                print(json.dumps({"status": "error", "message": "Target window not found"}))

        elif args.command == "capture":
            if args.annotate:
                res = capture_and_annotate(target=args.window, out_path=args.out, low_token=args.low_token)
            else:
                res = capture_phone(target=args.window, out_path=args.out, crop_phone_screen=not args.no_crop, low_token=args.low_token)
            print(json.dumps(res, indent=2))

        elif args.command == "tap-mark":
            res = tap_mark(args.mark_id, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "open-app":
            res = open_app(args.name, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "deep-link":
            res = deep_link(args.url, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "scroll-find":
            res = scroll_find(args.query, max_swipes=args.max_swipes, click=not args.no_click, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "hide-keyboard":
            res = hide_keyboard(target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "dump-ui":
            res = dump_ui_tree()
            print(json.dumps(res, indent=2))

        elif args.command == "wait-stable":
            res = wait_screen_stable(target=args.window, timeout=args.timeout)
            print(json.dumps(res, indent=2))

        elif args.command == "tap":
            res = tap(args.x, args.y, target=args.window, normalized=args.norm)
            print(json.dumps(res))

        elif args.command == "swipe":
            res = swipe(args.x1, args.y1, args.x2, args.y2, target=args.window, normalized=args.norm, steps=args.steps)
            print(json.dumps(res))

        elif args.command == "type":
            res = type_text(args.text, target=args.window)
            if args.enter:
                time.sleep(0.1)
                send_key("enter", target=args.window)
            print(json.dumps(res))

        elif args.command == "key":
            res = send_key(args.name, target=args.window)
            print(json.dumps(res))

        elif args.command == "find-text":
            res = find_text_on_screen(args.query, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "click-text":
            res = click_text_on_screen(args.query, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "wait-text":
            res = wait_and_click_text(args.query, target=args.window, timeout=args.timeout)
            print(json.dumps(res, indent=2))

        elif args.command == "dismiss-popup":
            res = dismiss_popups(target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "recover":
            res = emergency_recover(target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "smart-click":
            res = smart_click(args.query, target=args.window, scroll_fallback=not args.no_scroll)
            print(json.dumps(res, indent=2))

        elif args.command == "ensure-device":
            res = ensure_device_ready(target=args.window, auto_boot=not args.no_boot)
            print(json.dumps(res, indent=2))

        elif args.command == "prompt":
            res = execute_natural_prompt(args.text, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "export-schema":
            res = export_agent_schemas(fmt=args.format, server_url=args.server_url)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-list":
            res = cloud_api_request("/open/v1/phone/list", {"page": 1, "pageSize": 100}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-start":
            res = cloud_api_request("/open/v1/phone/start", {"ids": [args.profile_id]}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-stop":
            res = cloud_api_request("/open/v1/phone/stop", {"ids": [args.profile_id]}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "adb":
            res = run_adb(args.args)
            print(json.dumps(res, indent=2))

    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
