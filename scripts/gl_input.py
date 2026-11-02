"""Taps, swipes, typing and navigation keys (GUI mouse events or ADB injection)."""
import os
import time
import ctypes
import random
import gl_adb
import gl_base
import gl_win32

def _adb_input_device():
    """ADB serial to inject input through, only when GEELARK_INPUT_MODE=adb."""
    if gl_base.input_mode() != "adb":
        return None
    return gl_adb.resolve_device(gl_base.get_active_adb_device())

def tap(x, y, target=None, normalized=False):
    dev = _adb_input_device() if normalized else None
    if dev:
        hit = gl_adb.tap_normalized(dev, x, y)
        if hit:
            return {"status": "success", "action": "tap", "coords": hit["coords"], "via": "adb"}
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        raise RuntimeError("Touch input operations are only supported on Windows host.")
    win = gl_win32.find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("Target window not found")
    gl_win32.focus_window(win["hwnd"])
    bounds = gl_win32.get_phone_screen_bounds(win)
    if normalized:
        abs_x = bounds["x"] + int(float(x) * bounds["width"])
        abs_y = bounds["y"] + int(float(y) * bounds["height"])
    else:
        abs_x = bounds["x"] + int(x)
        abs_y = bounds["y"] + int(y)
    def worker():
        gl_base.user32.SetCursorPos(abs_x, abs_y)
        time.sleep(0.03)
        gl_base.user32.mouse_event(gl_base.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.06)
        gl_base.user32.mouse_event(gl_base.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    gl_base.with_desktop(worker)
    return {"status": "success", "action": "tap", "coords": [abs_x, abs_y]}

def swipe(x1, y1, x2, y2, target=None, normalized=False, steps=22, duration=0.25, human=True):
    dev = _adb_input_device() if normalized else None
    if dev:
        hit = gl_adb.swipe_normalized(dev, x1, y1, x2, y2, duration_ms=int(duration * 1000))
        if hit:
            return {"status": "success", "action": "swipe", "from": hit["from"], "to": hit["to"], "human_curve": False, "via": "adb"}
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        raise RuntimeError("Swipe gesture operations are only supported on Windows host.")
    win = gl_win32.find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("Target window not found")
    gl_win32.focus_window(win["hwnd"])
    bounds = gl_win32.get_phone_screen_bounds(win)
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
        points = [gl_base.bezier_point(p0, p1, p2, p3, gl_base.ease_in_out(i / float(steps))) for i in range(1, steps + 1)]
    else:
        points = [(int(start_x + (end_x - start_x) * (i / steps)), int(start_y + (end_y - start_y) * (i / steps))) for i in range(1, steps + 1)]

    def worker():
        gl_base.user32.SetCursorPos(start_x, start_y)
        time.sleep(0.03)
        gl_base.user32.mouse_event(gl_base.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        delay = duration / max(1, steps)
        for px, py in points:
            gl_base.user32.SetCursorPos(px, py)
            time.sleep(delay)
        time.sleep(0.03)
        gl_base.user32.mouse_event(gl_base.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    gl_base.with_desktop(worker)
    return {"status": "success", "action": "swipe", "from": [start_x, start_y], "to": [end_x, end_y], "human_curve": human}

def set_clipboard_text(text):
    if not gl_base.IS_WINDOWS or not gl_base.kernel32 or not gl_base.user32:
        raise RuntimeError("Clipboard operations are only supported on Windows host.")
    text_bytes = (text + '\0').encode('utf-16le')
    h_mem = gl_base.kernel32.GlobalAlloc(0x0042, len(text_bytes))
    if not h_mem:
        raise RuntimeError("GlobalAlloc failed to allocate clipboard memory.")
    p_mem = gl_base.kernel32.GlobalLock(h_mem)
    if not p_mem:
        gl_base.kernel32.GlobalFree(h_mem)
        raise RuntimeError("GlobalLock failed on clipboard handle.")
    try:
        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
    finally:
        gl_base.kernel32.GlobalUnlock(h_mem)
    opened = False
    for _ in range(10):
        if gl_base.user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.03)
    if not opened:
        gl_base.kernel32.GlobalFree(h_mem)
        raise RuntimeError("Failed to open Windows clipboard after 10 retries.")
    try:
        gl_base.user32.EmptyClipboard()
        if not gl_base.user32.SetClipboardData(13, h_mem):
            gl_base.kernel32.GlobalFree(h_mem)
            raise RuntimeError("SetClipboardData failed.")
    finally:
        gl_base.user32.CloseClipboard()

def type_text(text, target=None):
    win = gl_win32.find_target_window(target, prefer_phone=True)
    if win: gl_win32.focus_window(win["hwnd"])
    set_clipboard_text(text)
    def worker():
        time.sleep(0.06)
        gl_base.user32.keybd_event(gl_base.VK_CONTROL, 0, 0, 0)
        time.sleep(0.02)
        gl_base.user32.keybd_event(gl_base.VK_V, 0, 0, 0)
        time.sleep(0.02)
        gl_base.user32.keybd_event(gl_base.VK_V, 0, gl_base.KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)
        gl_base.user32.keybd_event(gl_base.VK_CONTROL, 0, gl_base.KEYEVENTF_KEYUP, 0)
    gl_base.with_desktop(worker)
    return {"status": "success", "action": "type", "text": text}

def send_key(key_name, target=None):
    key_lower = key_name.lower().strip()
    # Preferred path: real Android keyevents over ADB (layout-independent, no mouse/focus takeover).
    # Falls back to window-coordinate taps if ADB has no unambiguous device.
    if key_lower in ("back", "home", "recent", "appswitch") and os.environ.get("GEELARK_ADB_KEYS", "1") != "0":
        if gl_adb.keyevent(gl_adb.resolve_device(gl_base.get_active_adb_device()), key_lower):
            return {"status": "success", "action": "key", "key": key_name, "via": "adb"}
    if key_lower == "back":
        return tap(0.18, 0.97, target=target, normalized=True)
    elif key_lower == "home":
        return tap(0.50, 0.97, target=target, normalized=True)
    elif key_lower in ["recent", "appswitch"]:
        return tap(0.82, 0.97, target=target, normalized=True)
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        raise RuntimeError("Keyboard key operations are only supported on Windows host.")
    win = gl_win32.find_target_window(target, prefer_phone=True)
    if win: gl_win32.focus_window(win["hwnd"])
    vk_map = {"enter": gl_base.VK_RETURN, "tab": gl_base.VK_TAB, "esc": gl_base.VK_ESCAPE, "backspace": gl_base.VK_BACK}
    vk = vk_map.get(key_lower, gl_base.VK_RETURN)
    def worker():
        gl_base.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.04)
        gl_base.user32.keybd_event(vk, 0, gl_base.KEYEVENTF_KEYUP, 0)
    gl_base.with_desktop(worker)
    return {"status": "success", "action": "key", "key": key_name}

def hide_keyboard(target=None):
    """Safely collapse virtual keyboard so obscured buttons become clickable."""
    return send_key("back", target=target)
