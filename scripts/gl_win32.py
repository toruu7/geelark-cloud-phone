"""Window discovery, focusing, raw screen-rect capture and phone-screen geometry."""
import re
import time
import ctypes
from ctypes import wintypes
import gl_base

# Window Management & Handle Caching
def list_windows():
    """List all open GeeLark and phone windows with HWND, Rect, and Title."""
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        return []
    def worker():
        windows = []
        def enum_proc(hwnd, lparam):
            if gl_base.user32.IsWindowVisible(hwnd):
                length = gl_base.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    gl_base.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    title_l = title.lower()
                    ignored_apps = ["zen browser", "google chrome", "firefox", "edge", "visual studio code", "vscode", "github", "powershell", "terminal", "sublime", "notepad++"]
                    if any(ig in title_l for ig in ignored_apps):
                        return True
                    if any(k in title_l for k in ["geelark", "phone", "tiktok", "[#"]):
                        r = gl_base.RECT()
                        gl_base.user32.GetWindowRect(hwnd, ctypes.byref(r))
                        is_iconic = bool(gl_base.user32.IsIconic(hwnd))
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
        gl_base.user32.EnumDesktopWindows(0, WNDENUMPROC(enum_proc), 0)
        return windows
    return gl_base.with_desktop(worker)

def find_target_window(title_or_hwnd=None, prefer_phone=True):
    windows = list_windows()
    if not windows:
        return None
    if not title_or_hwnd:
        title_or_hwnd = gl_base.get_active_target()
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
        # 2. A bare profile number may only match a phone window, as a whole number:
        #    "4" must never match the app window "GeeLark 4.5.3" or phone "#14".
        if title_lower.isdigit():
            whole = re.compile(r"(?<!\d)" + re.escape(title_lower) + r"(?!\d)")
            for w in windows:
                if w["is_phone"] and whole.search(w["title"].lower()):
                    return w
            return None
        # 3. General substring match for non-numeric titles
        for w in windows:
            if title_lower in w["title"].lower():
                return w
        return None
    if prefer_phone:
        for w in windows:
            if w["is_phone"]: return w
    return windows[0]

def focus_window(hwnd):
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        return False
    def worker():
        gl_base.user32.keybd_event(gl_base.VK_MENU, 0, 0, 0)
        gl_base.user32.keybd_event(gl_base.VK_MENU, 0, gl_base.KEYEVENTF_KEYUP, 0)
        gl_base.user32.ShowWindow(hwnd, gl_base.SW_RESTORE)
        gl_base.user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return True
    return gl_base.with_desktop(worker)

# Screen Capture & Token Optimization
def capture_rect(x, y, w, h):
    if not gl_base.IS_WINDOWS or not gl_base.user32 or not gl_base.gdi32:
        raise RuntimeError("Screen capture is only supported on Windows host.")
    if gl_base.Image is None:
        raise RuntimeError("Pillow is required for image operations. Install with 'pip install pillow'")
    def worker():
        hScreenDC = gl_base.user32.GetDC(0)
        hMemDC = 0
        hBitmap = 0
        hOldBitmap = 0
        try:
            hMemDC = gl_base.gdi32.CreateCompatibleDC(hScreenDC)
            hBitmap = gl_base.gdi32.CreateCompatibleBitmap(hScreenDC, w, h)
            hOldBitmap = gl_base.gdi32.SelectObject(hMemDC, hBitmap)
            gl_base.gdi32.BitBlt(hMemDC, 0, 0, w, h, hScreenDC, x, y, gl_base.SRCCOPY)
            bmi = gl_base.BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(gl_base.BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0
            buf_size = w * h * 4
            buffer = (ctypes.c_char * buf_size)()
            gl_base.gdi32.GetDIBits(hMemDC, hBitmap, 0, h, buffer, ctypes.byref(bmi), 0)
            raw_img = gl_base.Image.frombuffer('RGBA', (w, h), buffer, 'raw', 'BGRA', 0, 1)
            try:
                return raw_img.convert('RGB')
            finally:
                raw_img.close()
        finally:
            if hMemDC and hOldBitmap:
                gl_base.gdi32.SelectObject(hMemDC, hOldBitmap)
            if hBitmap:
                gl_base.gdi32.DeleteObject(hBitmap)
            if hMemDC:
                gl_base.gdi32.DeleteDC(hMemDC)
            if hScreenDC:
                gl_base.user32.ReleaseDC(0, hScreenDC)
    return gl_base.with_desktop(worker)

# Touch, Gestures, Typing & Navigation
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
