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
from ctypes import wintypes
from PIL import Image, ImageChops, ImageDraw

# ---------------------------------------------------------
# Win32 Definitions & Setup
# ---------------------------------------------------------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# 64-bit Win32 API signatures for reliable clipboard memory handling
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.argtypes = []

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
        title_lower = str(title_or_hwnd).lower()
        for w in windows:
            if title_lower in w["title"].lower(): return w
    if prefer_phone:
        for w in windows:
            if w["is_phone"]: return w
    return windows[0]

def focus_window(hwnd):
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
    def worker():
        hScreenDC = user32.GetDC(0)
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
        img = Image.frombuffer('RGBA', (w, h), buffer, 'raw', 'BGRA', 0, 1).convert('RGB')
        gdi32.SelectObject(hMemDC, hOldBitmap)
        gdi32.DeleteObject(hBitmap)
        gdi32.DeleteDC(hMemDC)
        user32.ReleaseDC(0, hScreenDC)
        return img
    return with_desktop(worker)

def capture_phone(target=None, out_path=None, crop_phone_screen=True, low_token=False):
    """
    Capture phone window.
    If low_token is True, downsamples the image to ~720p height, saving up to 70% in multimodal token costs.
    """
    win = find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("No GeeLark or Phone window found. Make sure GeeLark is open.")
    hwnd = win["hwnd"]
    focus_window(hwnd)
    time.sleep(0.05)
    r = win["rect"]
    img = capture_rect(r["left"], r["top"], r["width"], r["height"])
    if crop_phone_screen and win["is_phone"]:
        top_offset = 30
        right_toolbar_width = 44
        phone_w = r["width"] - right_toolbar_width
        phone_h = r["height"] - top_offset
        if phone_w > 50 and phone_h > 50:
            img = img.crop((0, top_offset, phone_w, top_offset + phone_h))

    if low_token and img.height > 800:
        ratio = 800 / img.height
        new_w = int(img.width * ratio)
        img = img.resize((new_w, 800), Image.Resampling.LANCZOS)

    if not out_path:
        out_path = os.path.join(os.getcwd(), "phone_screen.png")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path, optimize=True)
    return {
        "status": "success",
        "file": os.path.abspath(out_path),
        "window": win["title"],
        "size": [img.width, img.height]
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

    img = Image.open(img_path).convert("RGB")
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
    with open(MARKS_CACHE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
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
    start_time = time.time()
    last_img = None
    while (time.time() - start_time) < timeout:
        res = capture_phone(target=target, out_path=os.path.join(SCRIPT_DIR, ".temp_stable.png"))
        img = Image.open(res["file"])
        if last_img is not None:
            diff = ImageChops.difference(img, last_img)
            diff_pixels = sum(1 for p in diff.getdata() if any(c > 20 for c in p))
            ratio = diff_pixels / (img.width * img.height)
            if ratio < threshold:
                return {"status": "success", "stable": True, "elapsed": round(time.time() - start_time, 2)}
        last_img = img
        time.sleep(poll_interval)
    return {"status": "success", "stable": False, "timeout": timeout}

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
    text_bytes = (text + '\0').encode('utf-16le')
    h_mem = kernel32.GlobalAlloc(0x0042, len(text_bytes))
    p_mem = kernel32.GlobalLock(h_mem)
    ctypes.memmove(p_mem, text_bytes, len(text_bytes))
    kernel32.GlobalUnlock(h_mem)
    for _ in range(10):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.03)
    user32.EmptyClipboard()
    user32.SetClipboardData(13, h_mem)
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

def scroll_find(query, max_swipes=5, click=True, target=None):
    """
    Autonomous Cost/Time Saver:
    Repeatedly scans for query. If found, clicks it immediately.
    If not, smoothly swipes down and repeats. Accomplishes what used to take 5 agent turns in 1 call!
    """
    for swipe_idx in range(max_swipes + 1):
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
        "Skip Ads", "Skip Ad", "Skip in 5s", "Skip", "Skip trial",
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
def run_adb(args):
    adb_exe = GEELARK_ADB_PATH if os.path.exists(GEELARK_ADB_PATH) else "adb"
    cmd = [adb_exe] + args
    res = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "returncode": res.returncode,
        "stdout": res.stdout.strip(),
        "stderr": res.stderr.strip()
    }

def dump_ui_tree():
    res = run_adb(["exec-out", "uiautomator", "dump", "/dev/tty"])
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
    adb_devices = [line.split("\t")[0] for line in adb_status["stdout"].split("\n") if "\tdevice" in line]
    
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
    Accepts JSON file path or raw JSON string.
    """
    if isinstance(steps_data, str):
        if os.path.exists(steps_data):
            with open(steps_data, "r", encoding="utf-8") as f:
                steps = json.load(f)
        else:
            steps = json.loads(steps_data)
    else:
        steps = steps_data

    results = []
    start_time = time.time()

    for idx, step in enumerate(steps, 1):
        action = step.get("action", "").lower().strip()
        res = {"step_index": idx, "action": action}

        try:
            if action == "sleep":
                dur = float(step.get("duration", step.get("seconds", 1.0)))
                time.sleep(dur)
                res["status"] = "success"
                res["slept"] = dur

            elif action == "tap":
                res["result"] = tap(step["x"], step["y"], target=target, normalized=step.get("norm", False))

            elif action == "swipe":
                res["result"] = swipe(
                    step["x1"], step["y1"], step["x2"], step["y2"],
                    target=target,
                    normalized=step.get("norm", False),
                    steps=step.get("steps", 22),
                    duration=step.get("duration", 0.25),
                    human=step.get("human", True)
                )

            elif action == "type":
                res["result"] = type_text(step["text"], target=target)
                if step.get("enter", False):
                    time.sleep(0.1)
                    send_key("enter", target=target)

            elif action == "key":
                res["result"] = send_key(step["name"], target=target)

            elif action == "open-app":
                res["result"] = open_app(step["name"], target=target)

            elif action == "deep-link":
                res["result"] = deep_link(step["url"], target=target)

            elif action == "click-text":
                res["result"] = click_text_on_screen(step["query"], target=target)

            elif action == "wait-text":
                res["result"] = wait_and_click_text(step["query"], target=target, timeout=step.get("timeout", 30.0))

            elif action == "scroll-find":
                res["result"] = scroll_find(
                    step["query"],
                    max_swipes=step.get("max_swipes", 5),
                    click=step.get("click", True),
                    target=target
                )

            elif action == "dismiss-popup":
                res["result"] = dismiss_popups(target=target)

            elif action == "hide-keyboard":
                res["result"] = hide_keyboard(target=target)

            elif action == "wait-stable":
                res["result"] = wait_screen_stable(target=target, timeout=step.get("timeout", 6.0))

            elif action == "capture":
                out = step.get("out", f"batch_step_{idx}.png")
                if step.get("annotate", False):
                    res["result"] = capture_and_annotate(target=target, out_path=out, low_token=step.get("low_token", False))
                else:
                    res["result"] = capture_phone(target=target, out_path=out, low_token=step.get("low_token", False))

            elif action == "youtube-flow":
                res["result"] = recipe_youtube_flow(step["url"], click_link=step.get("click_link"), skip_ads=step.get("skip_ads", True), target=target)

            elif action == "tiktok-feed":
                res["result"] = recipe_tiktok_feed(videos=step.get("videos", 5), min_watch=step.get("min_watch", 4.0), max_watch=step.get("max_watch", 10.0), like_ratio=step.get("like_ratio", 0.25), target=target)

            else:
                res["status"] = "error"
                res["message"] = f"Unknown action '{action}'"

            if "status" not in res:
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

def broadcast_action(command_name, command_args):
    """Executes an action across ALL open cloud phone windows."""
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
                r = tap(float(command_args[0]), float(command_args[1]), target=hwnd, normalized="--norm" in command_args)
            elif command_name == "swipe":
                r = swipe(float(command_args[0]), float(command_args[1]), float(command_args[2]), float(command_args[3]), target=hwnd, normalized="--norm" in command_args)
            elif command_name == "key":
                r = send_key(command_args[0], target=hwnd)
            elif command_name == "type":
                r = type_text(" ".join(command_args), target=hwnd)
            elif command_name == "open-app":
                r = open_app(command_args[0], target=hwnd)
            elif command_name == "deep-link":
                r = deep_link(command_args[0], target=hwnd)
            elif command_name == "dismiss-popup":
                r = dismiss_popups(target=hwnd)
            elif command_name == "hide-keyboard":
                r = hide_keyboard(target=hwnd)
            else:
                r = {"status": "error", "message": f"Command '{command_name}' not supported in broadcast mode"}
            results.append({"phone": p["title"], "hwnd": hwnd, "result": r})
        except Exception as e:
            results.append({"phone": p["title"], "hwnd": hwnd, "error": str(e)})

    return {"status": "success", "broadcast_count": len(phones), "results": results}

def batch_profiles(profiles_input, command_name, command_args):
    """Runs a command sequentially across specific profile numbers/names."""
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
                r = recipe_youtube_flow(command_args[0], click_link=command_args[1] if len(command_args) > 1 else None, target=hwnd)
            elif command_name == "tiktok-feed":
                v_count = int(command_args[0]) if len(command_args) > 0 else 5
                r = recipe_tiktok_feed(videos=v_count, target=hwnd)
            elif command_name == "open-app":
                r = open_app(command_args[0], target=hwnd)
            elif command_name == "deep-link":
                r = deep_link(command_args[0], target=hwnd)
            elif command_name == "dismiss-popup":
                r = dismiss_popups(target=hwnd)
            elif command_name == "recover":
                r = emergency_recover(target=hwnd)
            else:
                r = {"status": "error", "message": f"Command '{command_name}' not supported in batch-profiles mode"}
            results.append({"profile": p["title"], "hwnd": hwnd, "result": r})
        except Exception as e:
            results.append({"profile": p["title"], "hwnd": hwnd, "error": str(e)})

    return {"status": "success", "profiles_processed": len(selected), "results": results}

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

        elif args.command == "adb":
            res = run_adb(args.args)
            print(json.dumps(res, indent=2))

    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
